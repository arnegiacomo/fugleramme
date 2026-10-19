---
name: pi-test
description: Put the working tree on a Raspberry Pi running fugleramme and restart the frame there, so a change is seen on the real panel before it is committed or released. Use when the user asks to test on the Pi, on the device, on the panel, or on hardware, and to put the Pi back on a release afterwards.
disable-model-invocation: true
---

# Test on the Pi

The Pi's install is a plain git checkout at `~/fugleramme`, detached on a release tag and run
by the `fugleramme-frame` systemd unit. Treat that checkout as the deploy target: push to it
over SSH, check the pushed commit out there, restart the unit. Nothing goes through GitHub
and no commit lands in this repo's history.

## One-time setup

The Pi is a git remote named `pi`. If `git remote get-url pi` fails, ask the user for the
Pi's user and hostname and add it:

```bash
git remote add pi ssh://<user>@<host>.local/home/<user>/fugleramme
```

Remotes live in the repository's shared config, so one `pi` serves every worktree and every
agent. Everything below reads the host back out of that URL, so never hardcode one. A
`Host pi` entry in the user's `~/.ssh/config` is a fine alternative to a literal user and
hostname; the URL is then `ssh://pi/home/<user>/fugleramme`.

## Deploy the working tree

```bash
PI=$(git remote get-url pi | sed -E 's#ssh://([^/]+)/.*#\1#')
REF=$(git stash create)
git push -f pi "${REF:-HEAD}:refs/heads/test"
ssh "$PI" 'export PATH="$HOME/.local/bin:$PATH" && cd ~/fugleramme && git checkout -f --detach test && uv sync --extra panel && sudo -n systemctl restart fugleramme-frame'
```

- The `PATH` export is what `run.sh` does: `uv` lives in `~/.local/bin`, which a
  non-interactive SSH session does not have.
- `sudo -n` fails instead of hanging on a password prompt. Raspberry Pi OS gives the user
  Imager created passwordless sudo; any other user needs a rule, which the user adds once
  in a real terminal (the admin page's Reboot button needs the same):

  ```bash
  echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl" | sudo tee /etc/sudoers.d/fugleramme
  ```

- `git stash create` builds a commit of the working tree without touching the stash list,
  history or the index, so uncommitted work deploys as is. It covers tracked files only:
  `git add` a new file first. An empty result means the tree is clean and `HEAD` goes.
- `--detach` on the Pi keeps its HEAD off the `test` branch, which is what lets the next
  push to `test` be accepted.
- `-f` on the checkout matches what the self-update does: `uv sync` rewrites `uv.lock` in
  place on the Pi, and a plain checkout refuses to cross that.
- `--extra panel` is required. A bare `uv sync` removes the inky driver and the frame
  degrades to web-only without an error.
- The per-Pi files (`frame.env`, `detector/.env`, `detector/data/settings.json`) are
  gitignored, so the swap leaves the detector and the admin's state alone.

## Verify

A restart that returns cleanly says nothing about the next few seconds, so check the deploy
before reporting it done:

```bash
HOST=${PI#*@}
sleep 10
ssh "$PI" 'git -C ~/fugleramme rev-parse HEAD && systemctl is-active fugleramme-frame'
curl -fs "http://$HOST:8080/health"
ssh "$PI" journalctl -u fugleramme-frame -n 30 --no-pager
```

All four must hold: the printed commit is the one pushed (`git rev-parse "${REF:-HEAD}"`),
the unit is `active`, the kiosk answers `ok`, and the log shows no traceback and, on a Pi
with a panel, no `running web-only` warning (the inky driver was dropped or found no panel).
A `.local` host that `curl` cannot resolve is a workstation mDNS problem, not a deploy
failure; use the Pi's IP from `hostname -I` instead.

Then open `http://$HOST:8080`. The panel redraws on its own schedule, so give it a minute
before judging a render that only differs on the e-ink.

## Faster loop: the dev watcher on the Pi

For a run of small edits, stop the unit and run the reloading entrypoint on the Pi instead,
in a second terminal the user keeps open:

```bash
ssh "$PI" 'export PATH="$HOME/.local/bin:$PATH" && sudo -n systemctl stop fugleramme-frame && cd ~/fugleramme && uv run fugleramme-dev --port 8080 --detector http://127.0.0.1:8090'
```

It restarts the whole process, panel push included, whenever a source file changes, so each
iteration is only the push and `git checkout -f --detach test`. The real BirdNET-Go is
already running on the Pi; the fake detector is not needed there. A frame installed against
an external detector has its address in the Pi's `frame.env`, not `127.0.0.1`.

## Put a test page on the glass

For a rendering question the collage cannot isolate, push a page of your own to the panel
through the frame's driver wrapper. The frame has to be stopped while it shows: the loop
repaints on start, and the e-ink holds the image without power, so the user can look as
long as they like.

1. Render the page on the Pi, in the checkout, so its own FreeType and Pillow draw it. It
   must be the panel's resolution and in the frame's palette: build it on `PANEL_PAPER`,
   stamp exact black, and finish with `render.dither.dither`, which returns the mode "P"
   image the driver takes pixel for pixel. `scripts/label_variants.py` is a worked example:
   one row per vendored font and rasterisation variant, the label from discussion #76 at
   two panel sizes.
2. Copy `scripts/push_page.py` and the page over, stop the frame, push. The 13.3" blocks
   about 35 s while it refreshes:

   ```bash
   scp "${CLAUDE_SKILL_DIR}/scripts/push_page.py" "$PI:/tmp/"
   ssh "$PI" 'export PATH="$HOME/.local/bin:$PATH" && cd ~/fugleramme && sudo -n systemctl stop fugleramme-frame && uv run python /tmp/push_page.py /tmp/page.png'
   ```

3. Send the user the same PNG so they can match rows against the glass, and ask for a
   close-up photo: a phone shot of the whole panel cannot show one-pixel stems.
4. `sudo -n systemctl start fugleramme-frame` when they are done. It renders the collage
   again within half a minute.

## Cautions

- Do not run the test suite on the Pi with the frame stopped. The tests that start the
  loop then find the real panel and buttons: each one pushes to the glass, the run takes
  many minutes, and one such run ended in a reboot. With the frame running the suite is
  safe but the service tests fail on the GPIO lines being held; ci on Linux is the real
  check. The Pi is for looking at the glass.
- The admin's auto-update toggle, if on, will check a release out over `test`. It is off by
  default; tell the user to leave it off while testing.
- `run.sh` is not part of this loop. It only matters when the change is to the unit, the
  compose file or a per-Pi default, and then the breadcrumb in `.agents/install.md` applies.
- A change to artwork or `manifest.json` deploys the same way, but a later self-update
  resets both, so open the PR before the next release.

## Put the Pi back

When testing is done, return the Pi to a release, or the admin's Install button on the
System tab does it from the next release on:

```bash
ssh "$PI" 'export PATH="$HOME/.local/bin:$PATH" && cd ~/fugleramme && git fetch --tags && git checkout -f --detach <version> && uv sync --extra panel && sudo -n systemctl restart fugleramme-frame'
```

If the dev watcher was used, `sudo -n systemctl start fugleramme-frame` brings the unit back.
