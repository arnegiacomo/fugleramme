# Install

From a blank SD card to a running frame.

## 1. Flash the OS

**Raspberry Pi OS Lite (64-bit)**, Trixie or newer. Lite because the frame is
headless. Trixie because USB gadget mode needs it.

In Raspberry Pi Imager, set the hostname (e.g. `fugleramme`) and username (e.g.
`admin`), enable SSH, and configure Wi-Fi if you want it.

## 2. USB gadget mode (optional)

Lets you SSH in over a single USB-C cable, no network needed. Recommended - it
saves you when Wi-Fi isn't around. The install itself still needs internet.

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

## 3. SSH in

Over the network:

```bash
ssh <user>@<host>.local
```

Over the USB cable, if you did step 2. Use the Pi's **USB-C port** - the USB-A
ports can't act as a USB device. Approve the device prompt if your OS shows one:

```bash
ssh <user>@10.12.194.1
```

Use the IP, not the hostname - `<host>.local` points at the Wi-Fi address.

## 4. Install the frame

Install git if not present

```bash
sudo apt update && sudo apt install git
```

```bash
git clone https://github.com/arnegiacomo/fugleramme.git ~/fugleramme
cd ~/fugleramme
./setup.sh          # add -y to auto-accept dependency installs
```

This installs missing deps, brings up BirdNET-Go, and enables the frame as a
systemd service serving the kiosk on `:8080`. It also enables SPI and I2C, so
the first run needs a **reboot** before the panel will drive.

`setup.sh` bakes the repo path into the systemd unit - re-run it if you move the
repo.

Detector detail: [`detector/README.md`](https://github.com/arnegiacomo/fugleramme/blob/main/detector/README.md).
If something doesn't come up, see [Troubleshooting](troubleshooting.md).
