#!/usr/bin/env bash
# One-command setup for a Pi that shows a remote Fugleramme on its Inky Impression:
#   curl -fsSL https://raw.githubusercontent.com/arnegiacomo/fugleramme/main/examples/inky/install.sh | bash
# Asks for the frame's address and admin password, turns on the panel's buses,
# installs inky into a venv and runs main.py as the fugleramme-client service.
# Re-run it to update main.py; an empty answer keeps what config.py has. The
# answers can also come from FRAME_URL and ADMIN_PASSWORD in the environment.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

RAW="https://raw.githubusercontent.com/arnegiacomo/fugleramme/${FUGLERAMME_REF:-main}/examples/inky"
DIR="$HOME/fugleramme-client"
CONFIG="$DIR/config.py"
NEEDS_REBOOT=0

have() { command -v "$1" >/dev/null 2>&1; }

# curl|bash leaves stdin on the script itself, so prompts must read the terminal.
has_tty() { (exec </dev/tty) 2>/dev/null; }

ask() {  # $1 = prompt, $2 = default, $3 = "secret" to hide the typing
  local ans=""
  has_tty || { echo "$2"; return 0; }
  if [[ ${3:-} == secret ]]; then
    read -rsp "   $1 " ans </dev/tty || ans=""
    echo >&2
  else
    read -rp "   $1 [$2] " ans </dev/tty || ans=""
  fi
  echo "${ans:-$2}"
}

current() {  # $1 = a name in config.py
  sed -n "s/^$1 = \"\(.*\)\"$/\1/p" "$CONFIG"
}

# SPI for the pixels, I2C for the EEPROM inky.auto() identifies the board from.
# The same as install.sh, which mirrors pimoroni/inky's own installer.
ensure_panel_bus() {
  local boot_config="/boot/firmware/config.txt" line
  [[ -f "$boot_config" ]] || boot_config="/boot/config.txt"
  [[ -f "$boot_config" ]] || return 0
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
}

[[ "$(uname -s)" == Linux ]] || { echo "This sets up a Raspberry Pi." >&2; exit 1; }

echo "==> files in $DIR"
mkdir -p "$DIR"
curl -fsSL "$RAW/main.py" -o "$DIR/main.py"
[[ -f "$CONFIG" ]] || curl -fsSL "$RAW/config.py" -o "$CONFIG"

echo "==> the frame"
echo "   Enable \"External e-ink panel\" under Frame on its admin page."
url="${FRAME_URL:-$(ask "Frame address?" "$(current FRAME_URL)")}"
password="${ADMIN_PASSWORD:-$(ask "Admin password, if it requires sign-in (Enter for none or unchanged):" "" secret)}"
# Written by Python so a quote or a backslash in the password stays a valid literal.
python3 - "$CONFIG" "$url" "$password" <<'EOF'
import json, re, sys
path, url, password = sys.argv[1:]
text = open(path).read()
text = re.sub(r"^FRAME_URL = .*$", lambda _: f"FRAME_URL = {json.dumps(url)}", text, flags=re.M)
if password:
    text = re.sub(r"^ADMIN_PASSWORD = .*$", lambda _: f"ADMIN_PASSWORD = {json.dumps(password)}", text, flags=re.M)
open(path, "w").write(text)
EOF
curl -fsS -m 10 -o /dev/null "$url/health" || echo "   cannot reach $url yet; the client keeps trying"

echo "==> panel"
ensure_panel_bus

echo "==> python"
have uv || curl -fsSL https://astral.sh/uv/install.sh | sh
[[ -d "$DIR/.venv" ]] || uv venv -q "$DIR/.venv"
uv pip install -q --python "$DIR/.venv/bin/python" "inky>=2.6" "gpiod>=2.1" "gpiodevice>=0.0.5" pillow

echo "==> service"
sudo tee /etc/systemd/system/fugleramme-client.service >/dev/null <<EOF
[Unit]
Description=Fugleramme client
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$DIR
ExecStart=$DIR/.venv/bin/python main.py
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable -q fugleramme-client

if [[ $NEEDS_REBOOT == 1 ]]; then
  echo "==> done. Reboot to turn on the panel's buses: sudo reboot"
  exit 0
fi
sudo systemctl restart fugleramme-client
echo "==> done. Logs: journalctl -u fugleramme-client -f"
