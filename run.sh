#!/usr/bin/env bash
# Brings the appliance up from an existing checkout: BirdNET-Go (container) plus
# the render loop + kiosk (systemd). Re-run after a git pull or a repo move.
# install.sh handles the one-time machine setup and calls this at the end.
# Idempotent. --no-start enables the frame without starting it;
# --skip-mic-check allows BirdNET-Go to start without a capture device.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$REPO_ROOT/detector/config/config.yaml"

# Per-Pi install choices. A checkout from before install.sh asked has no
# frame.env, and the self-update never re-runs this script, so these defaults
# must stay what such a frame already runs on.
FRAME_PORT=8080
BIRDNET_PORT=8090
DETECTOR_MODE=bundled
DETECTOR_URL="http://127.0.0.1:8090"
if [[ -f "$REPO_ROOT/frame.env" ]]; then
  # shellcheck source=/dev/null
  source "$REPO_ROOT/frame.env"
fi

SKIP_MIC_CHECK=0
NO_START=0
for arg in "$@"; do
  case "$arg" in
    --skip-mic-check) SKIP_MIC_CHECK=1 ;;
    --no-start) NO_START=1 ;;
    *) echo "unknown argument: $arg (accepts --skip-mic-check, --no-start)" >&2; exit 1 ;;
  esac
done

# From the source, not the venv - this runs before uv sync.
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' "$REPO_ROOT/src/fugleramme/__init__.py")

have() { command -v "$1" >/dev/null 2>&1; }

require_linux() {
  [[ "$(uname -s)" == "Linux" ]] && return 0
  echo "run.sh provisions the Pi (Linux). For local development, run the pieces by hand with 'uv run'." >&2
  exit 1
}

require_deps() {
  local missing=()
  have uv || missing+=(uv)
  if [[ $DETECTOR_MODE == bundled ]]; then
    have docker || missing+=(docker)
    have arecord || missing+=(alsa-utils)
  fi
  [[ ${#missing[@]} -eq 0 ]] && return 0
  echo "missing: ${missing[*]} - run ./install.sh first" >&2
  exit 1
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
  if [[ $NO_START == 1 ]]; then
    echo "   enabled; starts on the next boot"
  else
    # restart (not just start) so re-running picks up pulled code
    sudo systemctl restart "$1"
  fi
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
BIRDNET_PORT=$BIRDNET_PORT
EOF
}

sync_python() {
  echo "==> python env"
  # Panel extra is Pi-only; if its driver can't build, the frame still runs
  # web-only, so fall back rather than fail the whole bootstrap.
  uv sync --directory "$REPO_ROOT" --extra panel || uv sync --directory "$REPO_ROOT"
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

  echo "==> birdnet-go"
  sudo rm -f /etc/tmpfiles.d/fugleramme.conf  # the old tmpfs rule, if present
  # force-recreate so a changed config.yaml or .env reloads. Started even under
  # --no-start: restart:unless-stopped only revives a container that was running.
  write_env
  docker_compose --env-file "$REPO_ROOT/detector/.env" \
    -f "$REPO_ROOT/detector/docker-compose.yml" up -d --force-recreate
}

converge_frame() {
  echo "==> frame service"
  install_service fugleramme-frame \
    "Fugleramme frame service (render loop + kiosk)" \
    "fugleramme-frame --port $FRAME_PORT --detector $DETECTOR_URL"
}

require_linux
require_deps
echo "==> fugleramme v$VERSION"
sync_python
echo "==> data dir"
# Settings, artwork picks and name caches; also BirdNET-Go's bind mount, which
# docker would otherwise create as root.
mkdir -p "$REPO_ROOT/detector/data"
if [[ $DETECTOR_MODE == bundled ]]; then
  converge_detector
else
  echo "==> detector: $DETECTOR_URL (not ours to run)"
fi
converge_frame
if [[ $NO_START == 0 ]]; then
  echo "==> up. Kiosk: http://$(hostname -I | awk '{print $1}'):$FRAME_PORT"
  echo "    Logs: journalctl -u fugleramme-frame -f"
  if [[ $DETECTOR_MODE == bundled ]]; then
    echo "    BirdNET-Go: http://$(hostname -I | awk '{print $1}'):$BIRDNET_PORT  (docker logs -f birdnet-go)"
  fi
fi
