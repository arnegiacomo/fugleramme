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
mode - recommended, see step 4. If no USB mic is detected, it asks whether to
continue without one. If lazy: pass `-y` to accept every prompt (installs, mic-check and so on):

```bash
... | bash -s -- -y
```

This clones the repo, installs missing deps, and enables the frame as a systemd
service serving the kiosk on `:8080`. It also enables SPI and I2C, so it ends by
asking for a **reboot** before the panel will drive. Say yes - everything comes
back on its own.

### Where BirdNET-Go lives

The installer asks. Three answers:

1. **Install it here** - the default. Fugleramme brings up BirdNET-Go in Docker
   alongside the frame, published on `:8090`. Pick this if you're starting fresh.
2. **Already running on this machine** - you installed BirdNET-Go yourself. Give
   its address; the default offered is `http://127.0.0.1:8080`, which is where
   BirdNET-Go puts itself.
3. **On another machine** - a station elsewhere on your network. Give its
   address, e.g. `http://birdnet.local:8080`.

For 2 and 3, nothing is installed in Docker and no mic is needed on this Pi. The
installer checks the address answers and tells you if it doesn't, but carries on
either way - you can fix it later on the admin page.

### Ports

The installer asks which port the frame's kiosk should use, defaulting to
`8080`. If something already holds it, it says what and asks again. This is the
one to change if you already run BirdNET-Go on `8080`.

When Fugleramme installs BirdNET-Go for you, it asks for that port too,
defaulting to `8090`.

Both answers are saved to `frame.env` in the checkout. To change them later,
edit that file and re-run `./run.sh`.

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

If Fugleramme installed BirdNET-Go for you, next up is [setting up
BirdNET-Go](birdnetgo-config.md), so that you can get your audio source
connected. If you pointed the frame at a BirdNET-Go you already run, you're
done - it keeps its own settings.
