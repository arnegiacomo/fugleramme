"""HTTP server: serves the rendered frame and a SQLite-backed dashboard.

Stdlib http.server only - no web framework. The server opens its own SQLite
connection (separate from the render loop's); WAL mode lets both coexist in one
process without lock contention. Single-threaded HTTPServer is plenty for a
one-viewer appliance dashboard.
"""

from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .db import Database

_PAGE = """<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="30">
<title>Fugleramme</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 1.5rem;
         max-width: 900px; margin-inline: auto; line-height: 1.5; }}
  h1 {{ font-size: 1.4rem; margin: 0 0 1rem; }}
  .frame {{ width: 100%; height: auto; border: 1px solid #8884; border-radius: 8px; }}
  .stats {{ display: flex; gap: 1rem; flex-wrap: wrap; margin: 1.25rem 0; }}
  .stat {{ flex: 1 1 8rem; border: 1px solid #8884; border-radius: 8px;
           padding: 0.75rem 1rem; }}
  .stat .n {{ font-size: 1.8rem; font-weight: 600; }}
  .stat .l {{ font-size: 0.85rem; opacity: 0.7; }}
  table {{ width: 100%; border-collapse: collapse; margin: 0.5rem 0 1.5rem; }}
  th, td {{ text-align: left; padding: 0.4rem 0.5rem; border-bottom: 1px solid #8884; }}
  th {{ font-size: 0.8rem; text-transform: uppercase; opacity: 0.6; }}
  i {{ opacity: 0.9; }}
</style>
</head>
<body>
<h1>Fugleramme</h1>
<img class="frame" src="/frame.png" alt="Siste registrering">
<div class="stats">
  <div class="stat"><div class="n">{total}</div><div class="l">registreringer</div></div>
  <div class="stat"><div class="n">{species}</div><div class="l">arter</div></div>
  <div class="stat"><div class="n">{last_24h}</div><div class="l">siste 24t</div></div>
</div>
<h2>Mest sett</h2>
<table><tr><th>Art</th><th>Antall</th><th>Beste</th></tr>{top_rows}</table>
<h2>Siste registreringer</h2>
<table><tr><th>Tid</th><th>Art</th><th>Sikkerhet</th></tr>{recent_rows}</table>
</body>
</html>
"""


def render_dashboard(db: Database) -> str:
    stats = db.stats()
    top_rows = "".join(
        f"<tr><td><i>{html.escape(r['scientific_name'])}</i></td>"
        f"<td>{r['n']}</td><td>{r['best']:.0%}</td></tr>"
        for r in stats["top"]
    ) or "<tr><td colspan=3>-</td></tr>"
    recent_rows = "".join(
        f"<tr><td>{d.detected_at.astimezone():%Y-%m-%d %H:%M}</td>"
        f"<td><i>{html.escape(d.scientific_name)}</i></td>"
        f"<td>{d.confidence:.0%}</td></tr>"
        for d in db.recent(20)
    ) or "<tr><td colspan=3>-</td></tr>"
    return _PAGE.format(
        total=stats["total"],
        species=stats["species"],
        last_24h=stats["last_24h"],
        top_rows=top_rows,
        recent_rows=recent_rows,
    )


def make_handler(db: Database, frame_path: Path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # quiet by default
            pass

        def _bytes(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            route = urlparse(self.path).path
            if route == "/frame.png":
                if frame_path.exists():
                    self._bytes(200, frame_path.read_bytes(), "image/png")
                else:
                    self._bytes(404, b"no frame yet", "text/plain")
            elif route in ("/", "/index.html"):
                self._bytes(200, render_dashboard(db).encode(), "text/html; charset=utf-8")
            elif route == "/health":
                self._bytes(200, b"ok", "text/plain")
            else:
                self._bytes(404, b"not found", "text/plain")

    return Handler


def serve(db_path: Path, frame_path: Path, host: str, port: int) -> None:
    """Blocking server loop. Opens its own DB connection."""
    db = Database(db_path)
    httpd = HTTPServer((host, port), make_handler(db, frame_path))
    httpd.serve_forever()
