"""HTTP server for the kiosk and admin views.

The kiosk (`/`) serves one thing: a full-color collage of the species seen in
the recent window, full-screen. It never reloads; instead it polls `/state` and
swaps the image only when the collage actually changed, so a new bird appears
within one poll interval with no flash. Presentation settings live at `/admin`
(#2) - rotation, lookback window, poll interval - and are read per request
from the shared SettingsStore, so a change takes effect without a restart. No
auth: both views are open on the LAN.

Stdlib http.server only, but threaded with a socket timeout: a serial server is
one silent client away from a dead kiosk, since a connection that never sends a
request blocks the accept loop forever. The server opens its own SQLite
connection; WAL lets it coexist with the render loop's connection.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .collage import collage_key, collage_png_bytes, collage_token, render_rng
from .config import BIRDNET_PORT, WEB_RESOLUTIONS
from .db import Database, Detection
from .names import available_sources, image_for, resolve, variants_for
from .panel import Panel
from .settings import LOOKBACK_OPTIONS, ROTATIONS, Settings, SettingsStore

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


def _kiosk_html(refresh_seconds: int) -> str:
    return f"""<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fugleramme</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #faf9f6; }}
  body {{ display: flex; align-items: center; justify-content: center; }}
  img {{ max-width: 100%; max-height: 100vh; object-fit: contain; }}
</style>
</head>
<body>
<img id="collage" src="/collage.png" alt="Fugler sett nylig">
<script>
  // The interval comes from /state: without a reload, nothing else picks up an admin change.
  let token = null, delay = {refresh_seconds};
  async function tick() {{
    try {{
      const state = await (await fetch("/state", {{cache: "no-store"}})).json();
      delay = state.refresh;
      if (state.token !== token) {{
        token = state.token;
        const next = new Image();  // decode before swapping, so the frame never blanks
        next.onload = () => {{ document.getElementById("collage").src = next.src; }};
        next.src = "/collage.png?v=" + encodeURIComponent(token);
      }}
    }} catch (e) {{}}  // transient: retry next tick
    setTimeout(tick, delay * 1000);
  }}
  tick();
</script>
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


def _species_li(name: str, pick: Path | None, candidates: list[Path]) -> str:
    # Marks species counted in the window but omitted from the collage (#9); else
    # names the source of the artwork actually on the frame, plus which candidate.
    if pick is None:
        return f'<li class="noart">{name} <small>no art</small></li>'
    note = _source_label(pick.parent.name)
    if len(candidates) > 1:
        note += f" ({candidates.index(pick) + 1})"
    return f'<li>{name} <small>{note}</small></li>'


_ASPECT = {0: "(landscape)", 90: "(portrait)"}

_SOURCE_LABELS = {"vonwright": "von Wright", "gould": "Gould"}


def _source_label(name: str) -> str:
    return _SOURCE_LABELS.get(name, name.replace("-", " ").title())


def _checkboxes(available: list[str], active: list[str]) -> str:
    return "".join(
        f'<label class="src"><input type="checkbox" name="sources" value="{s}"'
        f'{" checked" if s in active else ""}> {_source_label(s)}</label>'
        for s in available
    )


def _admin_html(
    settings: Settings,
    species: list[tuple[str, Path | None, list[Path]]],
    latest: Detection | None,
    panel_size: tuple[int, int] | None,
    available: list[str],
    active: list[str],
) -> str:
    resolutions = _options(
        WEB_RESOLUTIONS,
        settings.web_resolution,
        lambda r: f"{r} ({WEB_RESOLUTIONS[r][0]}×{WEB_RESOLUTIONS[r][1]})",
    )
    rotations = _options(ROTATIONS, settings.rotation, lambda r: f"{r}° {_ASPECT[r % 180]}")
    # A hand-edited non-preset value stays selectable so Save doesn't drop it.
    labels = dict(LOOKBACK_OPTIONS)
    labels.setdefault(settings.lookback_hours, f"{settings.lookback_hours} hours")
    lookbacks = _options(sorted(labels), settings.lookback_hours, labels.get)
    sources_field = (
        f'<div class="field"><span>Artwork sources</span>'
        f"{_checkboxes(available, active)}</div>"
    )
    w, h = settings.web_size()
    panel_status = (
        f"detected · {panel_size[0]}×{panel_size[1]}" if panel_size
        else "not detected (web-only)"
    )
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
  .field {{ margin: 0 0 1.25rem; }}
  label.src {{ display: flex; align-items: center; gap: 0.4rem; font-weight: 400; margin: 0 0 0.3rem; }}
  label.src input {{ width: auto; padding: 0; }}
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
    <label><span>Kiosk resolution <small>(web view only)</small></span>
      <select name="web_resolution">{resolutions}</select></label>
    <label><span>Rotation <small>(how the frame hangs)</small></span>
      <select name="rotation">{rotations}</select></label>
    <label><span>Lookback window</span>
      <select name="lookback_hours">{lookbacks}</select></label>
    <label><span>Kiosk poll <small>(seconds between checks)</small></span>
      <input type="number" name="kiosk_refresh_seconds" min="1" max="3600" value="{settings.kiosk_refresh_seconds}"></label>
    {sources_field}
    <button type="submit">Save</button>
  </form>
  <aside class="side">
    <dl class="status">
      <dt>Last detection</dt><dd>{last}</dd>
      <dt>Inky panel</dt><dd>{panel_status}</dd>
      <dt>Kiosk render</dt><dd>{w}×{h}</dd>
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


def make_handler(db: Database, images_dir: Path, store: SettingsStore, panel: Panel | None):
    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def log_error(self, fmt, *args):
            log.warning("%s %s", self.address_string(), fmt % args)

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
                sources = resolve(settings.sources, images_dir)
                png = collage_png_bytes(
                    db, images_dir, sources, settings.web_size(), False, settings.lookback_hours
                )
                self._send_png(png)
            elif route == "/state":
                # Cheap enough to poll every second: one grouped query, no render.
                key = collage_key(
                    db, resolve(settings.sources, images_dir), settings.web_size(),
                    False, settings.lookback_hours,
                )
                body = json.dumps(
                    {"token": collage_token(key), "refresh": settings.kiosk_refresh_seconds}
                )
                self._send(200, body.encode(), "application/json")
            elif route == "/admin":
                available = available_sources(images_dir)
                sources = resolve(settings.sources, images_dir)
                # Same seed as the render, so the picks listed are the ones on the frame.
                names = [n for n, _c in db.species_since(settings.lookback_hours)]
                rng = render_rng(names)
                species = [
                    (name, image_for(name, images_dir, sources, rng),
                     variants_for(name, images_dir, sources))
                    for name in names
                ]
                html = _admin_html(
                    settings, species, db.latest(),
                    panel.resolution if panel else None, available, sources,
                )
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
            # `sources` is a multi-value checkbox group (absent when all unchecked);
            # the rest are single values. _coerce validates + clamps.
            changes = {k: v[0] for k, v in form.items() if k != "sources"}
            changes["sources"] = form.get("sources", [])
            store.update(**changes)
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
    panel: Panel | None = None,
) -> None:
    """Blocking server loop. Opens its own DB connection."""
    db = Database(db_path)
    httpd = ThreadingHTTPServer((host, port), make_handler(db, images_dir, store, panel))
    httpd.serve_forever()
