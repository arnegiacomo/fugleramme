# Install

From a blank SD card to a running frame.

## 1. Flash the OS

**Raspberry Pi OS Lite (64-bit)**, Trixie or newer (to support gadget mode).

I recommend Lite to save memory by dropping the desktop environment. That is
the right choice if running the e-ink panel, or if you'll open the kiosk from another
device. Take Desktop only if you want the frame shown on an HDMI
screen straight from the pi - if you'd like to use HDMI with Lite see
[Showing the frame without the e-ink panel](operations.md#showing-the-frame-without-the-e-ink-panel).

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

It asks before installing anything and helps you set up the required dependencies. If no USB mic is detected, it asks whether to
continue without one. If lazy: pass `-y` to accept every prompt (installs, ports, run BirdNET-Go locally, mic-check and so on). A port that is already in use is skipped to the next free one:

```bash
... | bash -s -- -y
```

This clones the repo, installs missing deps, and enables the frame as a systemd
service serving the kiosk on `:8080` (or whatever port you configured it to). It also enables SPI and I2C, so it ends by
asking for a **reboot** before the panel will drive. Say yes - everything comes
back on its own.

### Where BirdNET-Go "lives"

The installer asks **Do you have BirdNET-Go installed?**

1. **No** - the default. Fugleramme brings up BirdNET-Go in Docker alongside the
   frame. Pick this if you're starting fresh.
2. **Yes, on this machine** - give its address. The default offered is
   `http://127.0.0.1:8080`, which is where BirdNET-Go puts itself if you follow [the official installation guide](https://github.com/tphakala/birdnet-go#quick-install).
3. **Yes, on another machine** - give its address, e.g.
   `http://birdnet.local:8080`. It can be anything the Pi can reach, https
   included (auth can be configured via the admin panel).

Answer 2 or 3 and no docker containers will be installed, and the mic check is skipped.
The installer says whether the address answered or is reachable, but continues either way (you can always edit this in the admin panel later).

### Ports

Two more prompts: the frame's web interface (`8080`) and, if it is installing
BirdNET-Go, that too (`8090`). Change the first if you already run something on
`8080`. A port that is already in use is refused, and you will have to choose another.

The ports and where BirdNET-Go "lives" are saved in `frame.env` in the checkout.
To change them later, see [Changing the ports](operations.md#changing-the-ports).

## 4. USB gadget mode (optional)

Lets you SSH in over a USB-C cable from your computer (**recommended**). It lets you interface with the frame without Wi-Fi or Ethernet (e.g. when installing in a new location or when changing Wi-Fi).

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
good-to-go!
