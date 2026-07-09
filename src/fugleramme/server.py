"""HTTP server for the kiosk view.

Serves one thing: a full-color collage of the species seen in the last 24h,
displayed full-screen and auto-refreshed. Everything else (stats, history,
config) belongs to the admin interface, tracked separately.

Stdlib http.server only. The server opens its own SQLite connection; WAL lets
it coexist with the render loop's connection in one process.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse

from .collage import DEFAULT_RESOLUTION, collage_png_bytes
from .db import Database

_KIOSK = """<!doctype html>
<html lang="no">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Fugleramme</title>
<style>
  html, body { margin: 0; height: 100%; background: #faf9f6; }
  body { display: flex; align-items: center; justify-content: center; }
  img { max-width: 100%; max-height: 100vh; object-fit: contain; }
</style>
</head>
<body>
<img src="/collage.png" alt="Fugler siste 24 timer">
</body>
</html>
"""


def make_handler(db: Database, images_dir: Path, resolution, show_names: bool):
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

        def do_GET(self):
            route = urlparse(self.path).path
            if route in ("/", "/index.html"):
                self._send(200, _KIOSK.encode(), "text/html; charset=utf-8")
            elif route == "/collage.png":
                png = collage_png_bytes(db, images_dir, resolution, show_names)
                self._send(200, png, "image/png")
            elif route == "/health":
                self._send(200, b"ok", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

    return Handler


def serve(
    db_path: Path,
    images_dir: Path,
    host: str,
    port: int,
    resolution=DEFAULT_RESOLUTION,
    show_names: bool = False,
) -> None:
    """Blocking server loop. Opens its own DB connection."""
    db = Database(db_path)
    httpd = HTTPServer((host, port), make_handler(db, images_dir, resolution, show_names))
    httpd.serve_forever()
