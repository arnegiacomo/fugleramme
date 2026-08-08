#!/usr/bin/env bash
# One-command Raspberry Pi bootstrap. Installs any missing dependencies
# (prompting first), then brings up the appliance: BirdNET-Go (container,
# detector) plus the render loop + kiosk (frame, systemd). The frame reads
# BirdNET-Go's DB directly - no sync process.
# Idempotent - safe to re-run. Pass -y to auto-accept installs.
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$REPO_ROOT/detector/config/config.yaml"
ASSUME_YES=0
SKIP_MIC_CHECK=0
for arg in "$@"; do
  case "$arg" in
    -y|--yes) ASSUME_YES=1 ;;
    --skip-mic-check) SKIP_MIC_CHECK=1 ;;
    *) echo "unknown argument: $arg (accepts -y/--yes, --skip-mic-check)" >&2; exit 1 ;;
  esac
done

# From the source, not the venv - this runs before uv sync.
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$REPO_ROOT/src/fugleramme/__init__.py")

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

# Per-Pi container env, read by compose even under sudo (which strips exported
# vars - the cause of the config dir flipping owner). UID/GID = host user so the
# entrypoint's chown of /config leaves files owned by us; ALSA_CARD makes the USB
# mic ALSA's default card (HDMI takes cards 0/1, which have no capture stream) so
# BirdNET-Go can enumerate it. The mic itself is picked in the BirdNET-Go UI.
write_env() {
  local card
  card="$(arecord -l 2>/dev/null | sed -nE 's/^card [0-9]+: ([^ ]+) \[.*/\1/p' | head -1)"
  cat > "$REPO_ROOT/detector/.env" <<EOF
BIRDNET_UID=$(id -u)
BIRDNET_GID=$(id -g)
ALSA_CARD=$card
EOF
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
  if [[ $SKIP_MIC_CHECK == 1 ]]; then
    echo "==> mic pre-flight (skipped)"
  else
    echo "==> mic pre-flight"
    "$REPO_ROOT/detector/preflight.sh"
  fi

  echo "==> config"
  ensure_config

  echo "==> data dir"
  # Persistent bind mount for BirdNET-Go's DB; drop the old tmpfs rule if present.
  mkdir -p "$REPO_ROOT/detector/data"
  sudo rm -f /etc/tmpfiles.d/fugleramme.conf

  echo "==> birdnet-go"
  # force-recreate so a changed config.yaml or .env reloads
  write_env
  docker_compose --env-file "$REPO_ROOT/detector/.env" \
    -f "$REPO_ROOT/detector/docker-compose.yml" up -d --force-recreate
}

# SPI for the pixels, I2C for the EEPROM inky.auto() identifies the board from.
# Overlays and raspi-config calls mirror pimoroni/inky's own installer.
ensure_panel_bus() {
  local boot_config="/boot/firmware/config.txt" line changed=0
  [[ -f "$boot_config" ]] || boot_config="/boot/config.txt"
  [[ -f "$boot_config" ]] || return 0

  # Not fatal: without the buses the frame still serves the kiosk.
  if have raspi-config; then
    sudo raspi-config nonint do_i2c 0 || echo "   could not enable I2C"
    sudo raspi-config nonint do_spi 0 || echo "   could not enable SPI"
  fi

  for line in dtoverlay=i2c1 dtoverlay=i2c1-pi5 dtoverlay=spi0-0cs; do
    grep -qxF "$line" "$boot_config" && continue
    echo "$line" | sudo tee -a "$boot_config" >/dev/null
    changed=1
  done
  [[ $changed == 1 ]] && echo "   $boot_config updated - reboot before the panel will drive"
  return 0
}

converge_frame() {
  echo "==> panel bus"
  ensure_panel_bus

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
echo "==> fugleramme v$VERSION"
ensure_deps
converge_detector
converge_frame
echo "==> up. Kiosk: http://$(hostname -I | awk '{print $1}'):8080"
echo "    Logs: journalctl -u fugleramme-frame -f  (BirdNET-Go: docker logs -f birdnet-go)"
