"""HTTP server for the kiosk and admin views.

The kiosk (`/`) serves one thing: a full-color collage of the species seen in
the recent window, full-screen and auto-refreshed. Presentation settings live
at `/admin` (#2) - orientation, lookback window, refresh interval - and are
read per request from the shared SettingsStore, so a change takes effect on the
next kiosk refresh without a restart. No auth: both views are open on the LAN.

Stdlib http.server only. The server opens its own SQLite connection; WAL lets
it coexist with the render loop's connection in one process.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .collage import collage_png_bytes
from .config import BIRDNET_PORT, PANEL_RESOLUTIONS
from .db import Database, Detection
from .names import variants_for
from .settings import ORIENTATIONS, Settings, SettingsStore


def _kiosk_html(refresh_seconds: int) -> str:
    return f"""<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{refresh_seconds}">
<title>Fugleramme</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #faf9f6; }}
  body {{ display: flex; align-items: center; justify-content: center; }}
  img {{ max-width: 100%; max-height: 100vh; object-fit: contain; }}
</style>
</head>
<body>
<img src="/collage.png" alt="Fugler siste {refresh_seconds}s">
</body>
</html>
"""


def _options(values, selected, label=str) -> str:
    return "".join(
        f'<option value="{v}"{" selected" if v == selected else ""}>{label(v)}</option>'
        for v in values
    )


def _ago(dt: datetime) -> str:
    s = int((datetime.now(timezone.utc) - dt).total_seconds())
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if s >= size:
            return f"{s // size}{unit} ago"
    return f"{s}s ago"


def _species_li(name: str, count: int, has_art: bool) -> str:
    # Species detected but without artwork are counted here yet omitted from the
    # collage (#9), so mark them - it explains any "detected > drawn" gap.
    cls = "" if has_art else ' class="noart"'
    note = "" if has_art else " · no art"
    return f'<li{cls}>{name} <small>×{count}{note}</small></li>'


def _admin_html(
    settings: Settings,
    species: list[tuple[str, int, bool]],
    latest: Detection | None,
    panel_present: bool,
) -> str:
    panels = _options(
        PANEL_RESOLUTIONS,
        settings.panel,
        lambda p: f'{p}" ({PANEL_RESOLUTIONS[p][0]}×{PANEL_RESOLUTIONS[p][1]})',
    )
    orientations = _options(ORIENTATIONS, settings.orientation)
    w, h = settings.resolution()
    last = f"{latest.scientific_name} · {_ago(latest.detected_at)}" if latest else "none yet"
    rows = "".join(_species_li(*s) for s in species) or '<li class="empty">none yet</li>'
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fugleramme admin</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 56rem; margin: 3rem auto; padding: 0 1rem; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap;
           gap: 0.5rem; border-bottom: 1px solid #e5e2dc; padding-bottom: 0.75rem; margin-bottom: 2rem; }}
  header h1 {{ margin: 0; }}
  header nav a {{ margin-left: 1.25rem; }}
  h2 {{ font-size: 1.05rem; margin: 0 0 0.5rem; }}
  .cols {{ display: flex; gap: 2.5rem; align-items: flex-start; }}
  form.settings {{ flex: 0 0 15rem; }}
  aside.side {{ flex: 1; min-width: 0; }}
  label {{ display: block; margin: 0 0 1.25rem; }}
  span {{ display: block; font-weight: 600; margin-bottom: 0.25rem; }}
  small {{ color: #666; font-weight: 400; }}
  select {{ font-size: 1rem; padding: 0.4rem; }}
  input {{ font-size: 1rem; padding: 0.4rem; width: 8rem; }}
  button {{ font-size: 1rem; padding: 0.5rem 1.25rem; margin-top: 0.5rem; }}
  a {{ color: #446; }}
  dl.status {{ display: grid; grid-template-columns: auto 1fr; gap: 0.35rem 1rem;
              background: #f4f2ee; padding: 1rem 1.25rem; border-radius: 6px; margin: 0 0 1.75rem; }}
  dl.status dt {{ color: #666; }}
  dl.status dd {{ margin: 0; }}
  ul.species {{ list-style: none; padding: 0; margin: 0 0 1.75rem;
               display: grid; grid-template-columns: repeat(auto-fill, minmax(13rem, max-content));
               justify-content: start; gap: 0.15rem 2.5rem; }}
  ul.species li {{ padding: 0.1rem 0; }}
  ul.species li.noart {{ color: #aaa; }}
  ul.species li.noart small {{ color: #aaa; }}
  ul.species li.empty {{ color: #999; }}
  details.preview {{ margin-top: 2rem; border-top: 1px solid #e5e2dc; padding-top: 1rem; }}
  details.preview summary {{ font-size: 1.05rem; font-weight: 600; cursor: pointer; }}
  details.preview img {{ display: block; max-width: 100%; max-height: 75vh; margin: 1rem auto 0;
                        border: 1px solid #ddd; border-radius: 6px; }}
  @media (max-width: 40rem) {{
    .cols {{ flex-direction: column; }}
    form.settings {{ flex: none; }}
  }}
</style>
</head>
<body>
<header>
  <h1>Display settings</h1>
  <nav><a href="/">Kiosk</a><a id="birdnet" href="#" title="detection &amp; stats">BirdNET-Go</a></nav>
</header>
<div class="cols">
  <form class="settings" method="post" action="/admin">
    <label><span>Inky panel</span>
      <select name="panel">{panels}</select></label>
    <label><span>Orientation</span>
      <select name="orientation">{orientations}</select></label>
    <label><span>Lookback window <small>(hours)</small></span>
      <input type="number" name="lookback_hours" min="1" max="720" value="{settings.lookback_hours}"></label>
    <label><span>Kiosk refresh <small>(seconds)</small></span>
      <input type="number" name="kiosk_refresh_seconds" min="5" max="3600" value="{settings.kiosk_refresh_seconds}"></label>
    <button type="submit">Save</button>
  </form>
  <aside class="side">
    <dl class="status">
      <dt>Last detection</dt><dd>{last}</dd>
      <dt>Inky panel</dt><dd>{"detected" if panel_present else "not detected (web-only)"}</dd>
      <dt>Render size</dt><dd>{w}×{h}</dd>
    </dl>
    <h2>Species in window ({len(species)})</h2>
    <ul class="species">{rows}</ul>
  </aside>
</div>
<details class="preview">
  <summary>Preview</summary>
  <img src="/collage.png" alt="Current collage" loading="lazy">
</details>
<script>
  // Same host as this page, BirdNET-Go's own port - the bind host (0.0.0.0) is not reachable.
  document.getElementById("birdnet").href = location.protocol + "//" + location.hostname + ":{BIRDNET_PORT}/";
</script>
</body>
</html>
"""


def make_handler(db: Database, images_dir: Path, store: SettingsStore, panel_present: bool):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet
            pass

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_png(self, png: bytes):
            # no-cache + ETag lets an unchanged refresh return a bodyless 304 instead of re-downloading the collage.
            etag = f'"{hashlib.md5(png).hexdigest()}"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(png)

        def do_GET(self):
            route = urlparse(self.path).path
            settings = store.get()
            if route in ("/", "/index.html"):
                self._send(200, _kiosk_html(settings.kiosk_refresh_seconds).encode(), "text/html; charset=utf-8")
            elif route == "/collage.png":
                png = collage_png_bytes(db, images_dir, settings.resolution(), False, settings.lookback_hours)
                self._send_png(png)
            elif route == "/admin":
                species = [
                    (name, n, bool(variants_for(name, images_dir)))
                    for name, n in db.species_since(settings.lookback_hours)
                ]
                html = _admin_html(settings, species, db.latest(), panel_present)
                self._send(200, html.encode(), "text/html; charset=utf-8")
            elif route == "/health":
                self._send(200, b"ok", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if urlparse(self.path).path != "/admin":
                self._send(404, b"not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode())
            store.update(**{k: v[0] for k, v in form.items()})  # _coerce validates + clamps
            self.send_response(303)
            self.send_header("Location", "/admin")
            self.end_headers()

    return Handler


def serve(
    db_path: Path,
    images_dir: Path,
    host: str,
    port: int,
    store: SettingsStore,
    panel_present: bool = False,
) -> None:
    """Blocking server loop. Opens its own DB connection."""
    db = Database(db_path)
    httpd = HTTPServer((host, port), make_handler(db, images_dir, store, panel_present))
    httpd.serve_forever()
