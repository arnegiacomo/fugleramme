# Operations

Services and logs. To be written.

## Buttons

Four buttons down the back edge of the panel:

| Button | What it does |
| --- | --- |
| A | Next display mode |
| B | Show species names on/off |
| C | Rotate the display 90° clockwise |
| D | Next artwork style |

These settings are saved and will override any settings set in the admin panel.
Give the panel up to a minute to catch up - it redraws slowly.

## Updates

The frame checks GitHub hourly for new releases and shows it on the admin
page's System tab. Press **Install** to update, or toggle on *Install new releases automatically* so that the frame updates itself.

Installing takes a minute or two, and the page shows how far it has got. The
frame restarts itself and comes back on the new
version. If an update fails, the
reason shows in place of the version and the frame keeps running as it was.

Some updates also bring a new version of BirdNET-Go, which is a few hundred megabytes and may take a while to download. (Your detections will be automatically backed up to `detector/data/birdnet.db.bak`.) This happens only while Fugleramme is the one running BirdNET-Go (a detector you run yourself is never touched).

The frame has to be online to check for or install updates, whichever way you do
it. The System tab tells you whether it is.

### Over SSH

To update by hand, using the version shown in the admin page:

```bash
ssh <user>@<host>.local
cd ~/fugleramme
git fetch --tags
git checkout <version>
uv sync
sudo systemctl restart fugleramme-frame
```

## Re-running the install

`./run.sh` re-applies everything the installer did, minus the initial machine setup:

```bash
ssh <user>@<host>.local
cd ~/fugleramme
./run.sh
```

Run it if you move the repo or swap the mic.

## Changing the ports

`FRAME_PORT` is the web interface, `BIRDNET_PORT` is BirdNET-Go when Fugleramme
runs it. Both are located in `frame.env`:

```bash
ssh <user>@<host>.local
cd ~/fugleramme
nano frame.env
./run.sh
```

`run.sh` is what bakes the port into the service, so a plain restart isn't enough.
Moving `BIRDNET_PORT` also means changing the address under **Detector** on the
admin page. Updates never touch either.

## Pointing the frame at a different BirdNET-Go

The admin page's System tab has a Detector section: the address, and a username
and password for an instance with private mode on. Saving takes effect straight
away - no restart. **Test connection** checks before you commit to it.

The frame reads detections only. Everything about how birds are detected stays
in BirdNET-Go's own settings.

If Fugleramme was running a BirdNET-Go of its own and you move the frame to
another instance for good, re-run `./install.sh` and answer 2 or 3. It offers to stop
the old container and hand the port back, so updates stop pulling an image
 and you stop the running container. Your detections stay in `detector/data` either way. Changing only the address on the admin page leaves the old container running, which is what you want if you plan to point back in the future.

## Changing Wi-Fi in gadget mode (USB-C)

For moving the frame to a new network, or onto one you can't reach it over yet.

> [!IMPORTANT]
> Will only be possible if gadget mode has been enabled.

```bash
ssh <user>@10.12.194.1 # or <user>@<host>.local if you've enabled internet sharing on your computer 
nmcli device wifi list
sudo nmcli --ask device wifi connect "<SSID>"
```

## Showing the frame without the e-ink panel

The frame serves the same image over HTTP, so anything with a browser can show
it. Three ways, easiest first.

### From another device

Open `http://<host>.local:8080/` on a phone, tablet or laptop on the same
network. This will work on any Raspberry pi os and installation method.

### On HDMI, Raspberry Pi OS Desktop

The desktop OS already has a browser and a session to run it in:

```bash
chromium --kiosk http://localhost:8080/
```

To start it with the desktop, add the same line to `~/.config/labwc/autostart`
(create the file if it isn't there):

```bash
chromium --kiosk http://localhost:8080/ &
```

> [!NOTE]
> The package is `chromium` on Trixie. Older guides say `chromium-browser`,
> which is now an empty package that pulls in `chromium` anyway.

### On HDMI, Raspberry Pi OS Lite

Lite has no browser **and no display server**, so installing `chromium` on its
own is not enough. It needs a compositor and a
session too. [`cage`](https://www.hjdskes.nl/projects/cage/) is the smallest one
that will do: it runs a single app fullscreen and has nothing to configure.

```bash
ssh <user>@<host>.local
sudo apt install --no-install-recommends chromium cage
```

Then a service, so it comes up with the Pi. `PAMName` and `TTYPath` are what
give the browser a login session and a seat on the screen, which is the part
that is missing on Lite:

```bash
sudo tee /etc/systemd/system/fugleramme-kiosk.service <<'EOF'
[Unit]
Description=Fugleramme HDMI kiosk
After=systemd-user-sessions.service getty@tty1.service fugleramme-frame.service
Conflicts=getty@tty1.service

[Service]
User=<user>
PAMName=login
TTYPath=/dev/tty1
TTYReset=yes
TTYVHangup=yes
StandardInput=tty-force
Environment=XDG_RUNTIME_DIR=/run/user/%U
ExecStart=/usr/bin/cage -- /usr/bin/chromium --kiosk --ozone-platform=wayland --noerrdialogs --disable-infobars http://localhost:8080/
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl disable getty@tty1.service
sudo systemctl enable --now fugleramme-kiosk
```

Replace `<user>` with your username, and `8080` with `FRAME_PORT` if you changed
it.

Disabling `getty@tty1` is not optional. Without it the login prompt and the
kiosk are both pulled in by the same boot transaction, systemd drops one of the
two conflicting jobs, and often it is the kiosk - which starts fine by hand and
then doesn't come back after a reboot.

> [!IMPORTANT]
> This gives up the login prompt on the attached screen, so SSH becomes the only
> way in. `sudo systemctl enable getty@tty1.service` puts it back.

Logs, when it doesn't come up:

```bash
journalctl -u fugleramme-kiosk -f
```

> [!NOTE]
> A portrait screen is rotated by the display, not by the frame. The
> **Rotation** setting on the admin page changes the shape of the page, and only
> the e-ink panel turns its own pixels; for HDMI, rotate the output in
> `/boot/firmware/cmdline.txt` (e.g. `video=HDMI-A-1:1920x1080@60,rotate=90`).
