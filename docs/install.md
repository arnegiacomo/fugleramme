# Install

From a blank SD card to a running frame.

## 1. Flash the OS

**Raspberry Pi OS Lite (64-bit)**, Trixie or newer (to support gadget mode).

I recommend Lite to save memory by dropping the desktop environment.

In Raspberry Pi Imager, set the hostname (e.g. `fugleramme`) and username (e.g.
`admin`), enable SSH, and configure Wi-Fi.

## 2. USB gadget mode (optional)

Lets you SSH in over a single USB-C cable, no network needed. Recommended - it
saves you when Wi-Fi isn't around (e.g. when moving house or setting up a new place without access to ethernet). 

The install itself still needs internet, so
enable Internet Sharing over the gadget interface on your computer so that you can share it with the pi.

Over wifi or ethernet:

```bash
ssh <user>@<host>.local
```

```bash
sudo apt update && sudo apt install rpi-usb-gadget
sudo rpi-usb-gadget on
sudo reboot
```

On a Pi 5, also update the bootloader. Early Pi 5 EEPROMs had the USB-C data
path disabled, and reflashing the SD card doesn't touch it:

```bash
sudo rpi-eeprom-update -a
sudo rpi-eeprom-config -e     # add a line: PSU_MAX_CURRENT=3000
sudo reboot
```

`PSU_MAX_CURRENT=3000` lets the Pi run properly when your laptop powers it over
the same cable. The tradeoff: it will now brown out on a weak charger instead of
warning you.

Now plug the the USB-C on the pi into your computer, approve the device prompt if your computer shows one,

Nice! Now your pi has gadget mode enabled, letting you control it fully from the USB-C port. You 

## 3. SSH in

Over the network (WiFi, Ethernet or gadget mode with internet sharing):

```bash
ssh <user>@<host>.local
```

## 4. Install the frame

Install git if not present

```bash
sudo apt update && sudo apt install git
```

```bash
git clone https://github.com/arnegiacomo/fugleramme.git ~/fugleramme
cd ~/fugleramme
./setup.sh          # add -y to auto-accept dependency installs
                    # add --skip-mic-check to bootstrap without the mic plugged in
```

This installs missing deps, brings up BirdNET-Go, and enables the frame as a
systemd service serving the kiosk on `:8080`. It also enables SPI and I2C, so
the first run needs a **reboot** before the panel will drive.

```bash
sudo reboot
```

`setup.sh` bakes the repo path into the systemd unit - re-run it if you move the
repo.

---
Congrats, you've now successfully set up your frame; happy birding! 🦤 🎶

If something doesn't come up on the screen, see [Troubleshooting](troubleshooting.md).
