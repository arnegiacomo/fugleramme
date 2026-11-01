# Wi-Fi setup

Covers `wifi.py`, `render/setup.py` and `web/portal.py` (#308). All three import nothing else from the package, so `examples/inky` can carry copies.

## What the hardware allows (tested on a Pi 5, Raspberry Pi OS trixie, NetworkManager 1.52)

- **One mode at a time.** Hosting a hotspot while joined to a network crashes the BCM43455 firmware (raspberrypi/linux#7092), so a join drops the hotspot first and a failed one reopens it.
- **Scanning works with the hotspot up.** A connected phone loses 0-4.5 s of traffic per scan and stays on; about one scan in three comes back empty. `Setup._open` still scans before raising, which is cheaper and always full; `_retry` scans with it up.
- **No OWE.** `key-mgmt owe` makes `nmcli` report success and the radio come up plain open, with wpa_supplicant rejecting the key management in the journal. Never trust a successful `nmcli connection up` to mean the security you asked for. WPA2 (`wpa-psk`) needs no PMF tuning.
- **NetworkManager never leaves an active hotspot for a saved network that comes back**, so the app drops it (`_retry`). After a failed join it falls back to a saved network in range within seconds, which is why `_join` reopens the hotspot at once.
- Wi-Fi is rfkill-blocked until a country is set; Imager sets one. Imager's networks are netplan-generated on trixie: change them with `nmcli`, never `/etc/netplan`.

## Captive portal

- iOS opens the portal by itself once every name resolves to the frame and port 80 reaches the frame's port: the `dnsmasq-shared.d` file and the `nft` redirect in `Nmcli.open`. Android is untested; DHCP option 114 is sent for it and changes nothing on iOS.
- `dnsmasq-shared.d` is read by every shared connection's dnsmasq, and the USB gadget's (`rpi-usb-gadget`) is one. The file holds anything only while the hotspot is up, and dnsmasq reads it at start, so an already running gadget is untouched.
- A client in `wifi.SUBNET` only ever gets the portal (`server._on_hotspot`), never the admin or the kiosk, whatever path it asks for.

## Root

- Everything goes through `sudo -n`. Raspberry Pi OS images from 2026-04-13 give the first user no passwordless sudo, so `install.sh` writes a narrow rule (`ensure_sudoers`) naming exactly the commands `Nmcli` runs. A new command here needs a line there, and a frame already installed only gets it by re-running the install. `Nmcli.allowed` checks the same list with `sudo -l`.
- "Online" is a default route (`Nmcli.online`), not a device NetworkManager calls connected. The USB gadget's shared profile stays "connected" with no cable plugged in, so counting devices would keep every frame with gadget mode "online" and the hotspot shut. The gadget counts once a computer shares its connection over it, which gives a default route.

## Defaults

- `wifi_setup` is on for updated frames too, against the usual rule that a release reproduces the previous one's behaviour: it only acts on a frame with no network, which was a dead frame before.
