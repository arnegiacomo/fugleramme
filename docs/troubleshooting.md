# Troubleshooting

Symptom to cause.

## SSH over USB

**Laptop sees no USB device.** Check you're in the Pi's USB-C port, not USB-A,
and not through a hub. Confirm the cable carries data by plugging a phone into
it. Then on the Pi, over the network:

```bash
cat /sys/class/udc/*/state
```

`not attached` means the Pi never saw a host - on a Pi 5 that's almost always an
old bootloader, so run the EEPROM step in [Install](install.md#2-usb-gadget-mode-optional).
`configured` means the link is up and the problem is on the laptop.

**Device shows up, but no gadget.** `sudo dmesg | grep -i gadget` should say
`bound driver g_ether`. If not, check for leftover manual `dtoverlay=dwc2` lines
in `/boot/firmware/config.txt` fighting the package - there should be one at most.

**Device shows up, SSH hangs.** Check your laptop got an address on the link:
`ifconfig | grep 10.12.194`. Use `10.12.194.1`, not `<host>.local`, which
resolves to the Wi-Fi address. Disable any VPN - they tend to swallow local
subnets.

## apt can't resolve deb.debian.org

The Pi has no route out. The USB link only joins your laptop and the Pi, so share
the laptop's connection over it:

- **macOS**: System Settings → General → Sharing → Internet Sharing. Share from
  your active connection, to **Raspberry Pi USB Gadget**.
- **Windows**: enable ICS, per the
  [rpi-usb-gadget README](https://github.com/raspberrypi/rpi-usb-gadget?tab=readme-ov-file#windows-setup--troubleshooting-ics--rndis).

**SSH dies the moment sharing is enabled.** Its DHCP replaces `10.12.194.1` with
a leased address. Reconnect as `<host>.local`, or find the address on macOS with
`cat /var/db/dhcpd_leases`.

## Laptop loses internet with the cable plugged in

The Pi hands out a default route over USB and the laptop prefers it over Wi-Fi.
Demote the gadget interface. On macOS, list every service with the gadget last:

```bash
sudo networksetup -ordernetworkservices "Wi-Fi" ... "Raspberry Pi USB Gadget"
```

SSH keeps working - `10.12.194.1` is a directly connected route.

## Panel stays blank

```bash
journalctl -u fugleramme-frame -f
```

Look for `Inky panel initialised`. If it says not detected, check `ls /dev/spidev*`
and that your login picked up the `spi`, `i2c` and `gpio` groups (`id`) - the
first `setup.sh` needs a reboot. The kiosk on `:8080` works either way, so a
live web view with a blank panel points here.
