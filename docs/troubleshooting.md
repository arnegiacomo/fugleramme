# Troubleshooting

Symptom to cause.

## curl says the certificate is not yet valid

```
curl: (60) SSL certificate problem: certificate is not yet valid
```

The Pi has no battery-backed clock, so on a fresh install its time might still
be behind the certificate's start date until it syncs over the network. Wait a
moment and run the same command again.

If it keeps failing, check the clock has caught up:

```bash
timedatectl          # System clock synchronized: yes
sudo timedatectl set-ntp true
```

## Installation stops partway

If the repository was successfully cloned but failed on setup:

```bash
~/fugleramme/install.sh
```

It reuses the checkout and skips setup that is already complete (idempotent).

## SSH over USB

**computer sees no USB device.** Check you're in the Pi's USB-C port, not USB-A,
and not through a hub. Confirm the cable carries data by plugging a phone into
it. Then on the Pi, over the network:

```bash
cat /sys/class/udc/*/state
```

`not attached` means the Pi never saw a host - on a Pi 5 that's almost always an
old bootloader, so run the EEPROM step in [Install](install.md#4-usb-gadget-mode-optional).
`configured` means the link is up and the problem is on the computer.

**Device shows up, but no gadget.** `sudo dmesg | grep -i gadget` should say
`bound driver g_ether`. If not, check for leftover manual `dtoverlay=dwc2` lines
in `/boot/firmware/config.txt` fighting the package - there should be one at most.

**Device shows up, SSH hangs.** Check your computer got an address on the link:
`ifconfig | grep 10.12.194`. Use `10.12.194.1`, not `<host>.local`, which
resolves to the Wi-Fi address. Disable any VPN - they tend to swallow local
subnets.

## apt can't resolve deb.debian.org

The Pi has no route out. The USB link only joins your computer and the Pi, so share
the computer's connection over it:

- **macOS**: System Settings → General → Sharing → Internet Sharing. Share from
  your active connection, to **Raspberry Pi USB Gadget**.
- **Windows**: enable ICS, per the
  [rpi-usb-gadget README](https://github.com/raspberrypi/rpi-usb-gadget?tab=readme-ov-file#windows-setup--troubleshooting-ics--rndis).

**SSH dies the moment sharing is enabled.** Its DHCP replaces `10.12.194.1` with
a leased address. Reconnect as `<host>.local`, or look up the lease your computer
handed out (macOS: `cat /var/db/dhcpd_leases`).

## Computer loses internet with the cable plugged in

The Pi hands out a default route over USB and the computer prefers it over Wi-Fi.
Demote the gadget interface in your computer's network service order, so Wi-Fi
comes first. On macOS, list every service with the gadget last:

```bash
sudo networksetup -ordernetworkservices "Wi-Fi" ... "Raspberry Pi USB Gadget"
```

SSH keeps working - `10.12.194.1` is a directly connected route.

## Page is empty, or the detector is unreachable

```bash
ssh <user>@<host>.local
cd ~/fugleramme
uv run fugleramme-check
```

A line per question the frame asks BirdNET-Go, and the address it asked. Add
`--detector http://<host>:<port>` to try another without saving it.

If nothing answers, check that address on the admin page's Detector tab -
**Test connection** says whether it is reachable, needs credentials, or is fine.
The password field is right below the address. If Fugleramme runs
BirdNET-Go for you, `docker ps` should show it. If it answers but finds no
birds, that's BirdNET-Go's side - open its own page and check the mic.

The frame holds its last page while the detector is away rather than wiping the
glass, so a short outage looks like nothing happening at all.

## Only scientific/latin bird names are available

BirdNET-Go keeps its settings behind a password even when detections are public, and the species names come from those settings. Set the
password on the Detector tab. (OIDC not supported yet)

## Locked out of the admin page

Set a new password in the settings file:

```bash
ssh <user>@<host>.local
nano ~/fugleramme/detector/data/settings.json   # "admin_password": "a-new-one"
```

The frame reads the file as you save it (no restart needed). Keep it valid
JSON: a broken file is ignored, and after a restart the admin page is open.

In the container the file is `/data/settings.json` in the volume, so edit it
from inside:

```bash
docker compose exec fugleramme sed -i 's/"admin_password": "[^"]*"/"admin_password": "a-new-one"/' /data/settings.json
```

Changing `FUGLERAMME_ADMIN_PASSWORD` in the compose file does nothing once that
file exists. The variables only seed a setting the file doesn't carry yet, and a
saved file carries every one of them.
See [Settings from environment variables](container.md#settings-from-environment-variables).

## "Too many attempts" on the login page

After five wrong passwords the frame refuses sign-ins from that address for
fifteen minutes. (Your own typos count too). Wait it out, or restart the frame:

```bash
ssh <user>@<host>.local
sudo systemctl restart fugleramme-frame
```

In the container, `docker compose restart fugleramme` does the same.

If you get blocked without typing anything wrong, someone else's guesses are
being counted against you. That usually happens behind a reverse proxy, where every
visitor has the proxy's address (same as you). Tick **The frame is behind a reverse proxy**
under [Security → Admin access](operations.md#behind-a-reverse-proxy).

## Frame won't start after an update

The detector (BirdNET-Go) keeps running, but the page is gone and
`journalctl -u fugleramme-frame -n 20` shows something like:

```
error: Failed to read metadata from: `.../fugleramme-<version>.dist-info`
  cause: EOF while parsing a value at line 1 column 0
```

A file in the Python environment was likely left empty during the update.
Try to rebuild the environment:

```bash
ssh <user>@<host>.local
cd ~/fugleramme
rm -rf .venv
uv sync --extra panel
sudo systemctl restart fugleramme-frame
```

If this happens to you, please open a [bug report](https://github.com/arnegiacomo/fugleramme/issues/new/choose) - the cause isn't known yet.

## Panel stays blank

```bash
journalctl -u fugleramme-frame -f
```

Look for `Inky panel initialised`. If it says not detected, check `ls /dev/spidev*`
and that your login picked up the `spi`, `i2c` and `gpio` groups (`id`) - the
first install needs a reboot. The kiosk on `:8080` works either way, so a
live web view with a blank panel points here.
