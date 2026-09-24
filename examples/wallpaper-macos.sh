#!/bin/sh
# Keeps the collage as the macOS desktop picture, fetched again every 15 minutes.
# The last five pages stay in ~/Pictures/Fugleramme, for a photo screen saver.
#
#   sh wallpaper-macos.sh http://<host>.local:8080             start, and set it now
#   sh wallpaper-macos.sh http://<host>.local:8080 --every 5   the same, fetched every 5 minutes
#   sh wallpaper-macos.sh --remove                             stop; the desktop keeps its last picture
set -eu

LABEL=local.fugleramme.wallpaper
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
JOB="$HOME/Library/Application Support/Fugleramme/wallpaper.sh"
FOLDER="$HOME/Pictures/Fugleramme"
DOMAIN="gui/$(id -u)"

if [ "${1:-}" = "--remove" ]; then
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  rm -f "$PLIST" "$JOB"
  echo "Stopped. The desktop keeps its current picture."
  exit 0
fi

MINUTES=15
case "${1:-}" in
  http://* | https://*) FRAME="${1%/}" ;;
  *) echo "usage: $0 http://<host>.local:8080 [--every MINUTES] | --remove" >&2; exit 2 ;;
esac
if [ "${2:-}" = "--every" ]; then
  case "${3:-}" in
    *[!0-9]* | "" | 0) echo "--every takes a number of minutes, 1 or more" >&2; exit 2 ;;
    *) MINUTES=$3 ;;
  esac
fi

mkdir -p "$(dirname "$JOB")" "$(dirname "$PLIST")" "$FOLDER"

# What launchd runs. A new filename each time: macOS does not redraw a picture
# set to the path it already shows. The newest five stay for a photo screen saver.
cat > "$JOB" <<'JOB'
#!/bin/sh
set -eu
FRAME="$1"; FOLDER="$2"
NEXT="$FOLDER/collage-$(date +%Y%m%d-%H%M%S).png"
# Nothing is written, and nothing changes, while the page is the one last fetched.
curl -fsS --etag-compare "$FOLDER/.etag" --etag-save "$FOLDER/.etag" -o "$NEXT.part" "$FRAME/collage.png"
[ -f "$NEXT.part" ] || exit 0
mv "$NEXT.part" "$NEXT"
osascript -e "tell application \"System Events\" to tell every desktop to set picture to POSIX file \"$NEXT\""
set -- "$FOLDER"/collage-*.png  # by name, so by time
while [ $# -gt 5 ]; do rm -f "$1"; shift; done
JOB

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string><string>$JOB</string><string>$FRAME</string><string>$FOLDER</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>StartInterval</key><integer>$((MINUTES * 60))</integer>
</dict>
</plist>
PLIST

launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
launchctl bootstrap "$DOMAIN" "$PLIST"
# The same script, however it was run: a file, or piped from the repo.
if [ -f "$0" ]; then STOP="sh $0 --remove"; else STOP="curl -fsSL https://raw.githubusercontent.com/arnegiacomo/fugleramme/main/examples/wallpaper-macos.sh | sh -s -- --remove"; fi
[ "$MINUTES" = 1 ] && EVERY="minute" || EVERY="$MINUTES minutes"
echo "Done. The desktop follows $FRAME, checked every $EVERY."
echo "To stop: $STOP"
