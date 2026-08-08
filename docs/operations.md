# Operations

Services and logs. To be written.

## Buttons

Four buttons down the back edge of the panel:

| Button | What it does |
| --- | --- |
| A | Nothing yet |
| B | Show species names on/off |
| C | Rotate the display 90° clockwise |
| D | Next artwork style |

These settings are saved and will override any settings set in the admin panel.
Give the panel up to a minute to catch up - it redraws slowly.

## Updates

The frame checks GitHub hourly for new releases and shows it in the admin
page's System box. Press **Install** to update, or toggle on *Install new releases automatically* so that the frame updates itself.

Installing takes a minute. The frame restarts itself and comes back on the new
version. If an update fails, the
reason shows in place of the version and the frame keeps running as it was.

The frame has to be online to check for or install updates, whichever way you do
it. The System box tells you whether it is.

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

Run it if you move the repo, swap the mic, or a release changes BirdNET-Go's
container.

## Changing Wi-Fi in gadget mode (USB-C)

For moving the frame to a new network, or onto one you can't reach it over yet.

> [!IMPORTANT]
> Will only be possible if gadget mode has been enabled.

```bash
ssh <user>@10.12.194.1 # or <user>@<host>.local if you've enabled internet sharing on your computer 
nmcli device wifi list
sudo nmcli --ask device wifi connect "<SSID>"
```

## Kiosk mode without the e-ink panel

The frame serves the same collage over HTTP, so an HDMI display does the job
instead of the panel:

```bash
chromium-browser --kiosk --app=http://localhost:8080/
```

> [!NOTE]
> Raspberry Pi OS Lite ships no browser, so this needs the desktop image or
> `sudo apt install chromium-browser`.

From any other machine on the network, open `http://<host>.local:8080/`.
