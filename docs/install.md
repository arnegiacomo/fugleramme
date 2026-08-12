# Install

From a blank SD card to a running frame.

## 1. Flash the OS

**Raspberry Pi OS Lite (64-bit)**, Trixie or newer (to support gadget mode).

I recommend Lite to save memory by dropping the desktop environment.

In Raspberry Pi Imager, set the hostname (e.g. `fugleramme`) and username (e.g.
`admin`), enable SSH, and configure Wi-Fi.

## 2. SSH in

Over wifi or ethernet:

```bash
ssh <user>@<host>.local
```

## 3. Install the frame

One command:

```bash
curl -fsSL https://raw.githubusercontent.com/arnegiacomo/fugleramme/main/install.sh | bash
```

It asks before installing anything, including whether to turn on USB gadget
mode - recommended, see step 4. Two flags, if you'd rather it didn't ask:

```bash
... | bash -s -- -y                 # accept every prompt
... | bash -s -- --skip-mic-check   # install before mic is plugged in
```

This clones the repo, installs missing deps, brings up BirdNET-Go, and enables
the frame as a systemd service serving the kiosk on `:8080`. It also enables SPI
and I2C, so it ends by asking for a **reboot** before the panel will drive. Say
yes - everything comes back on its own.

## 4. USB gadget mode (optional)

Lets you SSH in over a USB-C cable from your computer (**Strongly recommended**). It lets you interface with the frame without Wi-Fi or Ethernet (e.g. when installing in a new location or when changing Wi-Fi).

The installer turns it on if you accepted it in step 3.

> [!IMPORTANT]
> (Anecdotal) On a Pi 5 you still have to update the bootloader by hand, and
> reflashing the SD card doesn't help:

```bash
sudo rpi-eeprom-update -a
sudo rpi-eeprom-config -e     # add a line: PSU_MAX_CURRENT=3000
sudo reboot
```

`PSU_MAX_CURRENT=3000` lets the Pi run properly when your laptop powers it over
the same cable.

> [!WARNING]
> Tradeoff: it will now brown out on a weak charger instead of warning you.

Now plug the USB-C on the pi into your computer and approve the device prompt if
your computer shows one. For the pi to reach the internet through the cable,
enable Internet Sharing over the gadget interface on your computer.

---
Congrats, you've now successfully set up your frame; happy birding! 🦤 🎶

If something doesn't come up on the screen, see [Troubleshooting](troubleshooting.md).

Next up you should look at [setting up BirdNET-Go](birdnetgo-config.md), so that you can get your audio source connected.
