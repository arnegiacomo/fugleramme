#!/usr/bin/env bash
# One-command bootstrap for a fresh Pi:
#   curl -fsSL https://raw.githubusercontent.com/arnegiacomo/fugleramme/main/install.sh | bash
# Clones the repo, installs missing dependencies, optionally enables USB gadget
# mode, then hands off to run.sh. The split is the reboot: what only takes effect
# on boot lives here, what is safe to re-run against a live frame lives in run.sh.
# Idempotent. Pass options through the pipe with `bash -s -- -y`.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

REPO_URL="https://github.com/arnegiacomo/fugleramme.git"
REPO_DIR="${FUGLERAMME_DIR:-$HOME/fugleramme}"
REPO_REF="${FUGLERAMME_REF:-main}"
ASSUME_YES=0
NEEDS_REBOOT=0
APT_UPDATED=0
RUN_ARGS=()

# Per-Pi install choices, written to frame.env for run.sh. The defaults are what
# every frame installed before the ports were a question already runs on.
FRAME_PORT=8080
BIRDNET_PORT=8090
DETECTOR_MODE=bundled
DETECTOR_URL=""

have() { command -v "$1" >/dev/null 2>&1; }

# curl|bash leaves stdin on the script itself, so prompts must read the terminal.
# The node can exist and still be unopenable, so probe it rather than test -r.
has_tty() { (exec </dev/tty) 2>/dev/null; }

# Nothing to ask with -y or without a terminal: take the default and move on.
unattended() { [[ $ASSUME_YES == 1 ]] || ! has_tty; }

confirm() {
  [[ $ASSUME_YES == 1 ]] && return 0
  if ! has_tty; then
    echo "   no terminal to ask '$1' - assuming no (re-run with -y to auto-accept)"
    return 1
  fi
  local ans=""
  read -rp "$1 [y/N] " ans </dev/tty || return 1
  [[ "$ans" == [yY] || "$ans" == [yY][eE][sS] ]]
}

# Answer on stdout; read's prompt and every diagnostic go to stderr, so the
# caller's command substitution captures the value alone.
ask() {  # $1 = prompt, $2 = default
  local ans=""
  if unattended; then
    echo "$2"
    return 0
  fi
  read -rp "   $1 [$2] " ans </dev/tty || ans=""
  echo "${ans:-$2}"
}

listener() {  # $1 = port; prints what holds it, non-zero when free
  have ss || return 1
  local row
  # Columns are State Recv-Q Send-Q Local Peer, plus Process when sudo can see it.
  row="$(sudo ss -ltnp 2>/dev/null | awk -v p=":$1\$" '$4 ~ p {print (NF >= 6 ? $NF : "another process"); exit}')"
  [[ -n "$row" ]] || return 1
  echo "$row"
}

ask_port() {  # $1 = prompt, $2 = default
  local port held
  while true; do
    port="$(ask "$1" "$2")"
    if [[ ! "$port" =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
      echo "   not a port number: $port" >&2
      unattended && { echo "$2"; return 0; }
      continue
    fi
    held="$(listener "$port")" || { echo "$port"; return 0; }
    echo "   port $port is already in use by $held" >&2
    unattended && { echo "$port"; return 0; }
  done
}

probe_detector() {  # $1 = base URL
  if ! have curl; then
    echo "   no curl to check $1 with - trusting it"
    return 0
  fi
  if curl -fsS -m 5 -o /dev/null "$1/api/v2/health" 2>/dev/null; then
    echo "   $1 answered"
    return 0
  fi
  echo "   $1 did not answer. Installing anyway - point the frame somewhere else"
  echo "   later from http://<this pi>:$FRAME_PORT/admin"
}

# Asked before anything is installed: option 1 needs docker and a mic, the
# others need neither.
choose_detector() {
  echo "==> detector"
  # A re-run offers what this machine already runs on, so -y cannot quietly move
  # an external install back onto a container of its own.
  if [[ -f "$REPO_DIR/frame.env" ]]; then
    # shellcheck source=/dev/null
    source "$REPO_DIR/frame.env"
  fi
  local default=1 choice=""
  [[ $DETECTOR_MODE == external ]] && default=3
  if unattended; then
    choice=$default
  else
    cat <<'EOF'
   Where does BirdNET-Go listen for birds?
     1) install it here, alongside the frame
     2) it already runs on this machine
     3) it runs on another machine
EOF
    read -rp "   choice [$default] " choice </dev/tty || choice=$default
  fi
  case "${choice:-$default}" in
    2) DETECTOR_MODE=external
       DETECTOR_URL="$(ask "its address" "${DETECTOR_URL:-http://127.0.0.1:8080}")" ;;
    3) DETECTOR_MODE=external
       DETECTOR_URL="$(ask "its address" "${DETECTOR_URL:-http://birdnet.local:8080}")" ;;
    *) DETECTOR_MODE=bundled ;;
  esac

  FRAME_PORT="$(ask_port "port for the frame's kiosk and admin" "$FRAME_PORT")"
  if [[ $DETECTOR_MODE == bundled ]]; then
    BIRDNET_PORT="$(ask_port "port to publish BirdNET-Go on" "$BIRDNET_PORT")"
    DETECTOR_URL="http://127.0.0.1:$BIRDNET_PORT"
  else
    DETECTOR_URL="${DETECTOR_URL%/}"
    probe_detector "$DETECTOR_URL"
  fi
}

# run.sh reads this back on every converge; the self-update never re-runs it, so
# the values here outlive every release.
write_frame_env() {
  cat > "$REPO_DIR/frame.env" <<EOF
FRAME_PORT=$FRAME_PORT
BIRDNET_PORT=$BIRDNET_PORT
DETECTOR_MODE=$DETECTOR_MODE
DETECTOR_URL="$DETECTOR_URL"
EOF
}

need() {
  echo "cannot continue without $1" >&2
  exit 1
}

require_pi() {
  if [[ "$(uname -s)" != "Linux" ]]; then
    echo "install.sh provisions the Pi (Linux). For local development, clone the repo and use 'uv run'." >&2
    exit 1
  fi
  if [[ $EUID -eq 0 ]]; then
    echo "run as your normal user, not root - the checkout and the service unit belong to \$USER." >&2
    exit 1
  fi
  sudo -v
}

require_network() {
  getent hosts deb.debian.org >/dev/null 2>&1 && return 0
  echo "no route out - apt, docker and the BirdNET-Go image all need one." >&2
  echo "Over USB-C, share your computer's connection with the gadget interface." >&2
  exit 1
}

apt_update() {
  [[ $APT_UPDATED == 1 ]] && return 0
  sudo apt-get update
  APT_UPDATED=1
}

ensure_apt_pkg() {  # $1 = command to probe, $2 = apt package
  have "$1" && return 0
  echo "missing: $1"
  confirm "install $2 via apt?" || need "$1"
  apt_update
  sudo apt-get install -y "$2"
}

ensure_uv() {
  have uv && return 0
  echo "missing: uv"
  confirm "install uv (astral.sh installer)?" || need uv
  curl -fsSL https://astral.sh/uv/install.sh | sh
}

ensure_docker() {
  if have docker && docker compose version >/dev/null 2>&1; then return 0; fi
  echo "missing: docker + compose plugin"
  confirm "install docker (get.docker.com)?" || need docker
  curl -fsSL https://get.docker.com | sudo sh
}

ensure_repo() {
  if [[ -d "$REPO_DIR/.git" ]]; then
    git -C "$REPO_DIR" fetch --depth 1 origin "$REPO_REF"
    # --force -B: a self-update leaves HEAD detached at a tag and uv sync rewrites
    # uv.lock, either of which a plain checkout refuses to cross. Only tracked
    # files are discarded, and everything the Pi owns is gitignored.
    git -C "$REPO_DIR" checkout --force -B "$REPO_REF" "origin/$REPO_REF"
    return 0
  fi
  if [[ -e "$REPO_DIR" ]]; then
    echo "$REPO_DIR exists but is not a git checkout - move it aside or set FUGLERAMME_DIR" >&2
    exit 1
  fi
  # Shallow: the Pi only needs the current tree, not every past version of the artwork.
  git clone --depth 1 --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR"
}

ensure_mic() {
  "$REPO_DIR/detector/preflight.sh" >/dev/null 2>&1 && return 0
  echo "==> microphone"
  echo "   no ALSA capture device found"
  confirm "continue installation without a USB mic?" || need "an ALSA capture device"
  RUN_ARGS+=(--skip-mic-check)
}

# Panel access needs spi/i2c/gpio; docker saves a sudo. New groups only reach new logins.
ensure_groups() {
  local g
  for g in docker spi i2c gpio; do
    getent group "$g" >/dev/null 2>&1 || continue
    id -nG "$USER" | grep -qw "$g" && continue
    sudo usermod -aG "$g" "$USER"
    echo "   added $USER to $g"
    NEEDS_REBOOT=1
  done
}

# SPI for the pixels, I2C for the EEPROM inky.auto() identifies the board from.
# Overlays and raspi-config calls mirror pimoroni/inky's own installer.
ensure_panel_bus() {
  local boot_config="/boot/firmware/config.txt" line
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
    echo "   $line added to $boot_config"
    NEEDS_REBOOT=1
  done
  return 0
}

ensure_gadget() {
  if have rpi-usb-gadget; then
    echo "   already installed"
    return 0
  fi
  confirm "enable USB gadget mode (SSH over the USB-C cable)?" || { echo "   skipped"; return 0; }
  apt_update
  sudo apt-get install -y rpi-usb-gadget
  sudo rpi-usb-gadget on
  NEEDS_REBOOT=1
  cat <<'EOF'
   Two things gadget mode needs that this script will not do for you:
     - Pi 5 only: early EEPROMs ship with the USB-C data path disabled, and
       reflashing the card does not touch it.
           sudo rpi-eeprom-update -a
           sudo rpi-eeprom-config -e     # add a line: PSU_MAX_CURRENT=3000
     - your computer has to share its connection over the gadget interface
       before the Pi can reach the internet through the cable.
EOF
}

finish() {
  if [[ $NEEDS_REBOOT == 0 ]]; then
    echo "==> up. Kiosk: http://$(hostname -I | awk '{print $1}'):$FRAME_PORT"
    echo "    Logs: journalctl -u fugleramme-frame -f"
    return 0
  fi
  echo "==> installed, reboot needed before the panel will drive."
  if [[ $DETECTOR_MODE == bundled ]]; then
    echo "    BirdNET-Go is already listening; the frame starts itself on boot."
  else
    echo "    The frame starts itself on boot."
  fi
  if confirm "reboot now?"; then
    sudo reboot
  else
    echo "    Run 'sudo reboot' when you are ready."
  fi
}

main() {
  for arg in "$@"; do
    case "$arg" in
      -y|--yes) ASSUME_YES=1 ;;
      *) echo "unknown argument: $arg (accepts -y/--yes)" >&2; exit 1 ;;
    esac
  done

  require_pi
  require_network

  choose_detector

  echo "==> dependencies"
  ensure_apt_pkg git git
  ensure_uv
  if [[ $DETECTOR_MODE == bundled ]]; then
    ensure_docker
    ensure_apt_pkg arecord alsa-utils
  fi

  echo "==> repo"
  ensure_repo
  write_frame_env

  if [[ $DETECTOR_MODE == bundled ]]; then
    ensure_mic
  fi

  echo "==> groups"
  ensure_groups

  echo "==> panel bus"
  ensure_panel_bus

  echo "==> usb gadget"
  ensure_gadget

  echo "==> converge"
  # No SPI and no group membership until the reboot, so leave the frame enabled
  # but stopped rather than let it come up web-only and look broken.
  [[ $NEEDS_REBOOT == 1 ]] && RUN_ARGS+=(--no-start)
  "$REPO_DIR/run.sh" "${RUN_ARGS[@]}"

  finish
}

# Called last so a truncated download cannot execute half a script.
main "$@"
