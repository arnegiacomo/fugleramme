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
