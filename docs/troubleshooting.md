# Troubleshooting

Symptom to cause.

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

## The page is empty, or says the detector is unreachable

The frame draws what BirdNET-Go has heard, so an empty page usually means it
can't get an answer. Ask it directly:

```bash
ssh <user>@<host>.local
cd ~/fugleramme
uv run fugleramme-check
```

It prints a line per question the frame asks, and the address it asked. Pass
`--detector http://<host>:<port>` to try a different one without saving it.

- **Nothing answers.** Check the address on the admin page's System tab, under
  Detector. **Test connection** there says whether it is reachable, needs
  credentials, or answers fine. If Fugleramme installed BirdNET-Go for you,
  check the container is up: `docker ps`.
- **It answers but finds no birds.** That's BirdNET-Go's side. Open its own
  page and check the mic is picking something up.
- **Authentication required.** The instance has private mode on. Fill in the
  username and password under Detector.

The frame keeps showing its last page while the detector is away, rather than
wiping the glass, so a brief outage looks like nothing happening at all.

## Panel stays blank

```bash
journalctl -u fugleramme-frame -f
```

Look for `Inky panel initialised`. If it says not detected, check `ls /dev/spidev*`
and that your login picked up the `spi`, `i2c` and `gpio` groups (`id`) - the
first install needs a reboot. The kiosk on `:8080` works either way, so a
live web view with a blank panel points here.
