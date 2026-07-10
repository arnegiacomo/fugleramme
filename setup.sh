#!/usr/bin/env bash
# One-command Raspberry Pi bootstrap. Installs any missing dependencies
# (prompting first), then brings up the whole appliance as systemd services:
# BirdNET-Go + the sync (detector) and the render loop + kiosk (frame).
# Idempotent - safe to re-run. Pass -y to auto-accept installs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$REPO_ROOT/detector/config/config.yaml"
MIC_PLACEHOLDER="PICK_WITH_SETUP"
ASSUME_YES=0
FORCE_MIC=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --mic) FORCE_MIC=1 ;;   # re-run the capture-device selection
  esac
done

have() { command -v "$1" >/dev/null 2>&1; }

confirm() {
  [[ $ASSUME_YES == 1 ]] && return 0
  local ans
  read -rp "$1 [y/N] " ans
  [[ "$ans" == [yY] || "$ans" == [yY][eE][sS] ]]
}

need() {
  echo "cannot continue without $1" >&2
  exit 1
}

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] && return 0
  echo "setup.sh provisions the Pi (Linux). On the Mac run the pieces by hand with 'uv run'." >&2
  exit 1
}

ensure_apt_pkg() {  # $1 = command to probe, $2 = apt package
  have "$1" && return 0
  echo "missing: $1"
  confirm "install $2 via apt?" || need "$1"
  sudo apt-get update
  sudo apt-get install -y "$2"
}

ensure_uv() {
  have uv && return 0
  echo "missing: uv"
  confirm "install uv (astral.sh installer)?" || need uv
  curl -fsSL https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
}

ensure_docker() {
  if have docker && docker compose version >/dev/null 2>&1; then return 0; fi
  echo "missing: docker + compose plugin"
  confirm "install docker (get.docker.com)?" || need docker
  curl -fsSL https://get.docker.com | sudo sh
  sudo usermod -aG docker "$USER"
  echo "added $USER to the docker group - log out/in later so 'docker' works without sudo"
}

# docker or sudo docker, depending on whether the group change has taken effect
docker_compose() {
  if docker info >/dev/null 2>&1; then
    docker compose "$@"
  else
    sudo docker compose "$@"
  fi
}

install_service() {  # $1 = unit name, $2 = description, $3 = `uv run` target
  local unit="/etc/systemd/system/$1.service"
  local uv_bin
  uv_bin="$(command -v uv)"
  sudo tee "$unit" >/dev/null <<EOF
[Unit]
Description=$2
After=network-online.target docker.service
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REPO_ROOT
ExecStart=$uv_bin run $3
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  sudo systemctl daemon-reload
  sudo systemctl enable "$1"
  # restart (not just start) so re-running setup.sh picks up pulled code
  sudo systemctl restart "$1"
}

# Copy the tracked template to the per-Pi config on first run.
ensure_config() {
  [[ -f "$CONFIG" ]] && return 0
  cp "$CONFIG.template" "$CONFIG"
  echo "created $CONFIG from template"
}

# Pick the ALSA capture device and write it into config.yaml. Runs on first
# setup (device still the placeholder) or when forced with --mic.
configure_mic() {
  local current
  current="$(sed -nE 's/^[[:space:]]*device:[[:space:]]*"(.*)".*/\1/p' "$CONFIG" | head -1)"
  if [[ "$current" != "$MIC_PLACEHOLDER" && $FORCE_MIC == 0 ]]; then
    echo "audio device: $current (unchanged; pass --mic to reselect)"
    return 0
  fi

  local labels=() devices=() line re='^card ([0-9]+): ([^ ]+) \[([^]]*)\], device ([0-9]+):'
  while IFS= read -r line; do
    [[ "$line" =~ $re ]] || continue
    labels+=("${BASH_REMATCH[3]} (card ${BASH_REMATCH[1]}, device ${BASH_REMATCH[4]})")
    devices+=("plughw:CARD=${BASH_REMATCH[2]},DEV=${BASH_REMATCH[4]}")
  done < <(arecord -l 2>/dev/null)

  local n=${#devices[@]} choice=1
  if (( n == 0 )); then
    echo "no ALSA capture device found - is the USB mic plugged in?" >&2
    exit 1
  elif (( n == 1 )); then
    echo "capture device: ${labels[0]}"
  elif [[ $ASSUME_YES == 1 ]]; then
    echo "multiple capture devices; using ${labels[0]} (-y). Re-run with --mic to choose."
  else
    echo "select the capture device:"
    local i
    for i in "${!labels[@]}"; do printf "  %d) %s\n" "$((i + 1))" "${labels[$i]}"; done
    read -rp "choice [1]: " choice || true
    [[ "$choice" =~ ^[0-9]+$ ]] || choice=1
  fi

  local dev="${devices[$((choice - 1))]:-}"
  [[ -n "$dev" ]] || { echo "invalid choice" >&2; exit 1; }
  sed -i -E "s|^([[:space:]]*)device:.*|\1device: \"$dev\"|" "$CONFIG"
  echo "audio device set: $dev"
}

ensure_deps() {
  echo "==> dependencies"
  ensure_uv
  ensure_docker
  ensure_apt_pkg arecord alsa-utils

  echo "==> python env"
  # Panel extra is Pi-only; if its driver can't build, the frame still runs
  # web-only, so fall back rather than fail the whole bootstrap.
  uv sync --extra panel || uv sync
}

converge_detector() {
  echo "==> mic pre-flight"
  "$REPO_ROOT/detector/preflight.sh"

  echo "==> config + capture device"
  ensure_config
  configure_mic

  echo "==> tmpfs data dir"
  sudo install -m 0644 "$REPO_ROOT/detector/fugleramme-tmpfiles.conf" \
    /etc/tmpfiles.d/fugleramme.conf
  sudo systemd-tmpfiles --create /etc/tmpfiles.d/fugleramme.conf

  echo "==> birdnet-go"
  # force-recreate so a changed config.yaml (e.g. the capture device) is reloaded
  docker_compose -f "$REPO_ROOT/detector/docker-compose.yml" up -d --force-recreate

  echo "==> sync service"
  install_service fugleramme-sync \
    "Fugleramme detector sync (BirdNET-Go notes -> detections)" fugleramme-sync
}

converge_frame() {
  # Panel access needs these groups; harmless where they don't exist. Takes
  # effect after the next login - until then the frame serves the kiosk only.
  local g
  for g in spi i2c gpio; do
    getent group "$g" >/dev/null 2>&1 && sudo usermod -aG "$g" "$USER"
  done

  echo "==> frame service"
  install_service fugleramme-frame \
    "Fugleramme frame service (render loop + kiosk)" fugleramme-frame
}

require_linux
ensure_deps
converge_detector
converge_frame
echo "==> up. Kiosk: http://$(hostname -I | awk '{print $1}'):8080"
echo "    Logs: journalctl -u fugleramme-frame -u fugleramme-sync -f"
