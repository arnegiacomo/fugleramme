---
name: pi-test
description: Puts the working tree on the Raspberry Pi running fugleramme and restarts the frame there, so a change is seen on the real panel before it is committed or released. Use when the user asks to test on the Pi, the device, the panel or hardware, to put a test page on the glass, or to put the Pi back on a release.
disable-model-invocation: true
---

# Test on the Pi

The Pi's checkout at `~/fugleramme` is the deploy target, as git remote `pi`:

!`git remote get-url pi || echo "no pi remote: ask the user for <user>@<host> and run git remote add pi ssh://<user>@<host>/home/<user>/fugleramme"`

Every step is a subcommand of `scripts/pi.sh`, run from the checkout. It stops at the first
check that fails and says why; report done only when it printed `ok:`.

```bash
bash .claude/skills/pi-test/scripts/pi.sh deploy          # working tree -> Pi, restart, verify
bash .claude/skills/pi-test/scripts/pi.sh verify          # the Pi runs the pushed commit and is healthy
bash .claude/skills/pi-test/scripts/pi.sh page out.png    # stop the frame, put a page on the glass
bash .claude/skills/pi-test/scripts/pi.sh start           # the frame again, after a page
bash .claude/skills/pi-test/scripts/pi.sh release v0.28.0 # back on a release
```

`deploy` sends tracked files only: `git add` a new file first. Its output ends with the
frame's log; read it. The page is at the printed URL, and the panel takes up to a minute to
redraw. If `sudo -n` is refused, the user adds once, in a real terminal:
`echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl" | sudo tee /etc/sudoers.d/fugleramme`.

## A test page on the glass

Render the page at the panel's resolution (`Inky panel initialised: ... WxH` in the log) with
the frame's own code: `PANEL_PAPER` ground, exact black through an alpha mask,
`render.dither.dither` last. `uv.lock` pins the same Pillow on both machines, so preview the
PNG locally. A font that is
not in the checkout goes to the Pi's `/tmp` with `scp`. `page` blocks about 35 s on the 13.3"
and ignores the rotation setting.

Send the user the PNG and ask for a close-up photo. The frame stays stopped while they look,
so the final message must say so and give the `start` command.

## Faster loop

For a run of small edits, the reloading entrypoint on the Pi, in a terminal the user keeps
open; each edit is then `deploy` without the restart:

```bash
ssh <pi> 'export PATH="$HOME/.local/bin:$PATH" && sudo -n systemctl stop fugleramme-frame && cd ~/fugleramme && uv run fugleramme-dev --port 8080 --detector http://127.0.0.1:8090'
```

`<pi>` is the SSH target in the remote URL above. An external detector's address is in the
Pi's `frame.env`.

## Cautions

- Never run pytest on the Pi with the frame stopped: the service tests drive the real panel.
  CI is the Linux check.
- The admin's Install button and auto-update toggle check a release out over the deploy. Ask
  the user to leave both alone while testing.
- Per-Pi files (`frame.env`, `detector/.env`, `settings.json`) are gitignored and survive the
  swap. `run.sh` only matters for a change to the unit, compose or a per-Pi default
  (`.agents/install.md`).
- Artwork and `manifest.json` changes deploy the same way; the next self-update resets them.
