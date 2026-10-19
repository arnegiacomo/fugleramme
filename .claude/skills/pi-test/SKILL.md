---
name: pi-test
description: Puts the working tree on the Raspberry Pi running fugleramme and restarts the frame there, so a change is seen on the real panel before it is committed or released. Use when the user asks to test on the Pi, the device, the panel or hardware, to put a test page on the glass, or to put the Pi back on a release.
disable-model-invocation: true
---

# Test on the Pi

The Pi's checkout at `~/fugleramme` is the deploy target, as git remote `pi`:

!`git remote get-url pi || echo "no pi remote: ask the user for <user>@<host> and run git remote add pi ssh://<user>@<host>/home/<user>/fugleramme"`

`<pi>` below is the SSH target in that URL, between `ssh://` and the next `/`. Write it out
literally, and keep every `git` command on a line of its own: the worktree shell guard refuses
`git` and an SSH host in one command.

## Deploy

```bash
git stash create
git push -f pi <ref>:refs/heads/test
ssh <pi> 'export PATH="$HOME/.local/bin:$PATH" && cd ~/fugleramme && git checkout -f --detach test && uv sync --extra panel && sudo -n systemctl restart fugleramme-frame'
```

`<ref>` is what `git stash create` printed, or `HEAD` if nothing. It takes tracked files only,
so `git add` a new file first. Keep the flags: `-f` because `uv sync` rewrites `uv.lock` on the
Pi, `--detach` so the next push to `test` is accepted, `--extra panel` because a bare sync
drops the inky driver, `sudo -n` so a password prompt fails instead of hanging. If it is
refused, the user adds once, in a real terminal:
`echo "$USER ALL=(ALL) NOPASSWD: /usr/bin/systemctl" | sudo tee /etc/sudoers.d/fugleramme`.

## Verify

```bash
HOST=$(ssh <pi> hostname -I | cut -d' ' -f1)
sleep 10
ssh <pi> 'cat ~/fugleramme/.git/HEAD && systemctl is-active fugleramme-frame'
curl -fs "http://$HOST:8080/health"
ssh <pi> journalctl -u fugleramme-frame -n 30 --no-pager
```

Report done only when HEAD is the pushed commit, the unit is `active`, health answers `ok`,
and the log shows no traceback and no `running web-only`. The page is `http://$HOST:8080`;
the panel takes up to a minute to redraw.

## Faster loop

Run the reloading entrypoint on the Pi in a terminal the user keeps open; each edit is then
only the push and `git checkout -f --detach test`:

```bash
ssh <pi> 'export PATH="$HOME/.local/bin:$PATH" && sudo -n systemctl stop fugleramme-frame && cd ~/fugleramme && uv run fugleramme-dev --port 8080 --detector http://127.0.0.1:8090'
```

An external detector's address is in the Pi's `frame.env`.

## A test page on the glass

Render the page at the panel's resolution (`Inky panel initialised: ... WxH` in the log) with
the frame's own code: `PANEL_PAPER` ground, exact black through an alpha mask,
`render.dither.dither` last. Pillow and FreeType match on both machines (12.3.0 and 2.14.3
when this was written; recheck after an update), so preview the PNG locally first. Extra
fonts go to `/tmp` beside the script.

```bash
scp .claude/skills/pi-test/scripts/push_page.py page.png <pi>:/tmp/
ssh <pi> 'export PATH="$HOME/.local/bin:$PATH" && cd ~/fugleramme && sudo -n systemctl stop fugleramme-frame && uv run python /tmp/push_page.py /tmp/page.png'
```

The push blocks about 35 s on the 13.3" and ignores the rotation setting. Send the user the
PNG and ask for a close-up photo. The frame stays stopped while they look, so the final
message must say so and give `ssh <pi> 'sudo -n systemctl start fugleramme-frame'`.

## Cautions

- Never run pytest on the Pi with the frame stopped: the service tests drive the real panel,
  and one run rebooted the Pi. CI is the Linux check.
- The admin's Install button and auto-update toggle check a release out over `test`. Ask the
  user to leave both alone while testing.
- Per-Pi files (`frame.env`, `detector/.env`, `settings.json`) are gitignored and survive the
  swap. `run.sh` only matters for a change to the unit, compose or a per-Pi default
  (`.agents/install.md`).
- Artwork and `manifest.json` changes deploy the same way; the next self-update resets them.

## Put the Pi back

```bash
ssh <pi> 'export PATH="$HOME/.local/bin:$PATH" && cd ~/fugleramme && git fetch --tags && git checkout -f --detach <version> && uv sync --extra panel && sudo -n systemctl restart fugleramme-frame'
```
