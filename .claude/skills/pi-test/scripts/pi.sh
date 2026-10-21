#!/usr/bin/env bash
# Put the working tree on the Pi running fugleramme and check it came up. Run from
# the workstation, in the checkout, with the Pi's checkout as git remote `pi`:
#
#   pi.sh deploy          push the working tree, check it out on the Pi, restart, verify
#   pi.sh verify [ref]    the Pi runs <ref> (default: branch test) and the frame is healthy
#   pi.sh page <png>      stop the frame and put a page on the glass (push_page.py)
#   pi.sh start           start the frame again and verify it
#   pi.sh release <tag>   put the Pi back on a release tag and verify it
#
# Exits non-zero with the reason on the first check that fails.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UNIT=fugleramme-frame

die() {
  echo "pi.sh: $*" >&2
  exit 1
}

# The SSH target in the remote's URL: ssh://<target>/home/<user>/fugleramme.
target() {
  local url
  url=$(git remote get-url pi 2>/dev/null) \
    || die "no pi remote. Ask the user for <user>@<host>, then: git remote add pi ssh://<user>@<host>/home/<user>/fugleramme"
  url=${url#ssh://}
  echo "${url%%/*}"
}

# A command in the Pi's checkout. uv lives in ~/.local/bin, which a non-interactive
# session does not have on PATH. BatchMode: fail instead of prompting for a password.
remote() {
  ssh -o BatchMode=yes "$PI" "export PATH=\"\$HOME/.local/bin:\$PATH\" && cd ~/fugleramme && $*"
}

deploy() {
  local ref untracked
  untracked=$(git status --porcelain | grep '^??' || true)
  [[ -z $untracked ]] || echo "pi.sh: not deployed (untracked, git add first):" $'\n'"$untracked" >&2
  # A commit of the working tree, without touching history, the index or the stash list.
  ref=$(git stash create)
  git push -f pi "${ref:-HEAD}:refs/heads/test"
  # -f: uv sync rewrites uv.lock on the Pi. --detach: the next push to test is accepted.
  # --extra panel: a bare sync drops the inky driver. -n: no password prompt to hang on.
  remote "git checkout -f --detach test && uv sync --extra panel && sudo -n systemctl restart $UNIT"
  verify test
}

verify() {
  local want have state host since log
  want=$(remote "git rev-parse '${1:-test}^{commit}'")
  sleep 10 # a restart that returns says nothing about the next few seconds
  have=$(remote 'git rev-parse HEAD')
  [[ $have == "$want" ]] || die "the Pi runs $have, expected $want (the admin's Install button moves it)"
  state=$(remote "systemctl is-active $UNIT" || true)
  [[ $state == active ]] || die "$UNIT is $state"
  host=${PI#*@}
  # Asked on the Pi: its first address can be one the workstation cannot reach (usb0, docker).
  remote "curl -fs localhost:8080/health" | grep -qx ok || die "no 'ok' from /health on the Pi"
  since=$(remote "systemctl show -p ActiveEnterTimestamp --value $UNIT")
  log=$(remote "journalctl -u $UNIT --since '$since' --no-pager")
  echo "$log"
  grep -q 'Inky panel initialised\|Serving kiosk' <<<"$log" || die "no startup lines in the log since '$since'"
  if grep -qE 'Traceback|running web-only' <<<"$log"; then
    die "the log shows a traceback or a web-only fallback (the inky driver is missing or found no panel)"
  fi
  echo "ok: $PI runs ${have:0:7}, $UNIT active, http://$host:8080"
}

page() {
  [[ $# -eq 1 && -f $1 ]] || die "usage: pi.sh page <png>"
  scp -q "$HERE/push_page.py" "$1" "$PI:/tmp/"
  remote "sudo -n systemctl stop $UNIT && uv run python /tmp/push_page.py /tmp/$(basename "$1")"
  echo "the frame is STOPPED with the page on the glass. Say so to the user; bring the collage back with: bash $0 start"
}

start() {
  remote "sudo -n systemctl start $UNIT"
  verify HEAD
}

release() {
  [[ $# -eq 1 ]] || die "usage: pi.sh release <tag>"
  # One tag, shallow, as updates.apply fetches it: every tag pins a copy of the artwork.
  # --no-tags: auto-follow would add every old release still in the object store.
  remote "git fetch --depth 1 --no-tags origin tag '$1' --force && git checkout -f --detach '$1' && { git branch -D test 2>/dev/null || true; } && uv sync --extra panel && sudo -n systemctl restart $UNIT"
  verify "$1"
}

PI=$(target)
case "${1:-}" in
  deploy) deploy ;;
  verify) verify "${2:-test}" ;;
  page) shift; page "$@" ;;
  start) start ;;
  release) shift; release "$@" ;;
  *) sed -n '2,10p' "$0"; exit 1 ;;
esac
