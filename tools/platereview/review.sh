#!/usr/bin/env bash
# Serve a built review folder and open it.
#
#     ./review.sh                 the folder beside this script, if there is only one
#     ./review.sh review-demo     a named folder
#     ./review.sh review-demo 9000
#
# The page also opens straight off the filesystem - birds.js is a script tag, not a fetch,
# so a double-click works. This is for when a browser or an extension refuses file://.
set -euo pipefail

here=$(cd "$(dirname "$0")" && pwd)
folder=${1:-}
port=${2:-8777}

if [ -z "$folder" ]; then
  # macOS ships bash 3.2, which has no mapfile
  found=$(find "$here" -maxdepth 2 -name birds.js -exec dirname {} \;)
  if [ "$(echo "$found" | grep -c .)" -ne 1 ]; then
    echo "name the review folder: ./review.sh <folder> [port]" >&2
    echo "$found" | sed "s|^$here/|  |" >&2
    exit 1
  fi
  folder=$found
fi

[ -d "$folder" ] || folder=$here/$folder
# a folder still at the crop stage has crops.js and no birds.js yet: open its page instead
page=index.html
[ -f "$folder/birds.js" ] || page=crop.html
[ -f "$folder/birds.js" ] || [ -f "$folder/crops.js" ] || { echo "no birds.js or crops.js in $folder - run build.py or crops.py on it first" >&2; exit 1; }
# always the checked-in page: a copy left from an earlier run would miss its later fixes
cp "$here/$page" "$folder/$page"

echo "serving $folder on http://localhost:$port/$page"
command -v open >/dev/null && (sleep 1 && open "http://localhost:$port/$page") &
# A rebuild rewrites img/ and birds.js under the same names, so a cached copy would show the
# previous round's plate after a reload: serve everything as no-store.
exec python3 - "$port" "$folder" <<'PY'
import functools
import http.server
import sys


class NoStore(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


handler = functools.partial(NoStore, directory=sys.argv[2])
http.server.ThreadingHTTPServer(("127.0.0.1", int(sys.argv[1])), handler).serve_forever()
PY
