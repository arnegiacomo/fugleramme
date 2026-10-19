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
agent. A `Host pi` entry in the user's `~/.ssh/config` is a fine alternative to a literal
user and hostname; the URL is then `ssh://pi/home/<user>/fugleramme`.

Everything below says `<pi>` for the SSH target: the part of that URL between `ssh://` and
the next `/`, so `user@host.local` or `pi`. Read it off `git remote get-url pi`, run on a
line of its own, and write it out literally in the commands that follow. Never hardcode a
host in this file, and never put `git` and an SSH host in one command line: in a
worktree-isolated session the shell guard refuses the mix.

## Deploy the working tree

Each line is its own command:

```bash
git stash create
git push -f pi <ref>:refs/heads/test
ssh <pi> 'export PATH="$HOME/.local/bin:$PATH" && cd ~/fugleramme && git checkout -f --detach test && uv sync --extra panel && sudo -n systemctl restart fugleramme-frame'
```

`<ref>` is what `git stash create` printed, or `HEAD` when it printed nothing.

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
HOST=$(ssh <pi> hostname -I | cut -d' ' -f1)
sleep 10
ssh <pi> 'cat ~/fugleramme/.git/HEAD && systemctl is-active fugleramme-frame'
curl -fs "http://$HOST:8080/health"
ssh <pi> journalctl -u fugleramme-frame -n 30 --no-pager
```

All four must hold: the commit in `.git/HEAD` is the one pushed, the unit is `active`, the
kiosk answers `ok`, and the log shows no traceback and, on a Pi with a panel, no
`running web-only` warning (the inky driver was dropped or found no panel). The IP comes
from the Pi itself because an SSH alias such as `pi` is not a hostname `curl` can resolve,
and a `.local` name may not resolve from the workstation either.

Then open `http://$HOST:8080`. The panel redraws on its own schedule, so give it a minute
before judging a render that only differs on the e-ink.

## Faster loop: the dev watcher on the Pi

For a run of small edits, stop the unit and run the reloading entrypoint on the Pi instead,
in a second terminal the user keeps open:

```bash
ssh <pi> 'export PATH="$HOME/.local/bin:$PATH" && sudo -n systemctl stop fugleramme-frame && cd ~/fugleramme && uv run fugleramme-dev --port 8080 --detector http://127.0.0.1:8090'
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

1. Render the page with the frame's own code: the panel's resolution (`Inky panel
   initialised: ... WxH` in the log), built on `PANEL_PAPER`, exact black stamped through
   an alpha mask, finished with `render.dither.dither`, which returns the mode "P" image the
   driver takes pixel for pixel. A script that imports `fugleramme` runs under
   `uv run python` in the checkout on either machine. The Pi and the workstation draw the
   same bytes when their Pillow and FreeType match (both 12.3.0 and 2.14.3 at the time of
   writing; compare `python -c "from PIL import Image, features; print(Image.__version__,
   features.version('freetype2'))"` on each after an update), so look at the page locally
   before stopping the frame. A font that is not in the checkout goes over with `scp` to
   `/tmp` beside the script, and the script takes its path.
2. Copy `scripts/push_page.py` (under `.claude/skills/pi-test/` when `${CLAUDE_SKILL_DIR}`
   is unset) and the page over, stop the frame, push. The 13.3" blocks about 35 s while it
   refreshes. The push is at rotation 0 whatever the admin's rotation setting, which is
   right for a test page and a surprise on a portrait frame:

   ```bash
   scp .claude/skills/pi-test/scripts/push_page.py page.png <pi>:/tmp/
   ssh <pi> 'export PATH="$HOME/.local/bin:$PATH" && cd ~/fugleramme && sudo -n systemctl stop fugleramme-frame && uv run python /tmp/push_page.py /tmp/page.png'
   ```

3. Send the user the same PNG so they can match it against the glass, and ask for a
   close-up photo: a phone shot of the whole panel cannot show one-pixel stems.
4. The frame stays stopped while they look, and the agent is usually gone by the time they
   are done. The final message must say so and give the command that brings the collage
   back, which renders again within half a minute:

   ```bash
   ssh <pi> 'sudo -n systemctl start fugleramme-frame'
   ```

## Cautions

- Do not run the test suite on the Pi with the frame stopped. The tests that start the
  loop then find the real panel and buttons: each one pushes to the glass, the run takes
  many minutes, and one such run ended in a reboot. With the frame running the suite is
  safe but the service tests fail on the GPIO lines being held; ci on Linux is the real
  check. The Pi is for looking at the glass.
- The admin page's Install button, and the auto-update toggle if it is on, check a release
  out over `test`. A person pressing Install mid-test is what the Verify step once caught.
  Tell the user to leave both alone while testing; the toggle is off by default.
- `run.sh` is not part of this loop. It only matters when the change is to the unit, the
  compose file or a per-Pi default, and then the breadcrumb in `.agents/install.md` applies.
- A change to artwork or `manifest.json` deploys the same way, but a later self-update
  resets both, so open the PR before the next release.

## Put the Pi back

When testing is done, return the Pi to a release, or the admin's Install button on the
System tab does it from the next release on:

```bash
ssh <pi> 'export PATH="$HOME/.local/bin:$PATH" && cd ~/fugleramme && git fetch --tags && git checkout -f --detach <version> && uv sync --extra panel && sudo -n systemctl restart fugleramme-frame'
```

If the dev watcher was used, `sudo -n systemctl start fugleramme-frame` brings the unit back.
