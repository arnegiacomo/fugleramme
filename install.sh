#!/usr/bin/env bash
# One-command bootstrap for a fresh Pi:
#   curl -fsSL https://raw.githubusercontent.com/arnegiacomo/fugleramme/main/install.sh | bash
# Clones the repo, installs missing dependencies, optionally enables USB gadget
# mode, then hands off to run.sh. The split is the reboot: what only takes effect
# on boot lives here, what is safe to re-run against a live frame lives in run.sh.
# Idempotent. Pass options through the pipe with `bash -s -- -y`.
set -euo pipefail

REPO_URL="https://github.com/arnegiacomo/fugleramme.git"
REPO_DIR="${FUGLERAMME_DIR:-$HOME/fugleramme}"
REPO_REF="${FUGLERAMME_REF:-main}"
ASSUME_YES=0
NEEDS_REBOOT=0
APT_UPDATED=0
RUN_ARGS=()

have() { command -v "$1" >/dev/null 2>&1; }

# curl|bash leaves stdin on the script itself, so prompts must read the terminal.
# The node can exist and still be unopenable, so probe it rather than test -r.
confirm() {
  [[ $ASSUME_YES == 1 ]] && return 0
  if ! (exec </dev/tty) 2>/dev/null; then
    echo "   no terminal to ask '$1' - assuming no (re-run with -y to auto-accept)"
    return 1
  fi
  local ans=""
  read -rp "$1 [y/N] " ans </dev/tty || return 1
  [[ "$ans" == [yY] || "$ans" == [yY][eE][sS] ]]
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
  export PATH="$HOME/.local/bin:$PATH"
}

ensure_docker() {
  if have docker && docker compose version >/dev/null 2>&1; then return 0; fi
  echo "missing: docker + compose plugin"
  confirm "install docker (get.docker.com)?" || need docker
  curl -fsSL https://get.docker.com | sudo sh
}

ensure_repo() {
  if [[ -d "$REPO_DIR/.git" ]]; then
    git -C "$REPO_DIR" fetch origin "$REPO_REF"
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
  git clone --branch "$REPO_REF" "$REPO_URL" "$REPO_DIR"
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
    echo "==> up. Kiosk: http://$(hostname -I | awk '{print $1}'):8080"
    echo "    Logs: journalctl -u fugleramme-frame -f  (BirdNET-Go: docker logs -f birdnet-go)"
    return 0
  fi
  echo "==> installed, reboot needed before the panel will drive."
  echo "    BirdNET-Go is already listening; the frame starts itself on boot."
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
      --skip-mic-check) RUN_ARGS+=(--skip-mic-check) ;;
      *) echo "unknown argument: $arg (accepts -y/--yes, --skip-mic-check)" >&2; exit 1 ;;
    esac
  done

  require_pi
  require_network

  echo "==> dependencies"
  ensure_apt_pkg git git
  ensure_uv
  ensure_docker
  ensure_apt_pkg arecord alsa-utils

  echo "==> repo"
  ensure_repo

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
