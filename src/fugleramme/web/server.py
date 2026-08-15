"""HTTP server for the kiosk and admin views.

The kiosk (`/`) serves one thing: a full-color page of what the frame is
showing, full-screen. It never reloads; instead it polls `/state` and swaps the
image only when the page actually changed, so a new bird appears within one poll
interval with no flash. Presentation settings live at `/admin` and are read per
request from the shared SettingsStore, so a change takes effect without a
restart. No auth: both views are open on the LAN.

Routing and transport only - the admin page itself is built in admin.py, and the
files under static/ are served as they are.

Stdlib http.server only, but threaded with a socket timeout: a serial server is
one silent client away from a dead kiosk, since a connection that never sends a
request blocks the accept loop forever. The server opens its own SQLite
connection; WAL lets it coexist with the render loop's connection.
"""

from __future__ import annotations

import hashlib
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

from .. import __version__, modes, updates
from ..db import Database
from ..featured import Featured
from ..languages import namer
from ..panel import Panel
from ..picks import Picks
from ..settings import Settings, SettingsStore, merged
from ..status import Status
from . import STATIC_DIR, admin

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

HTML = "text/html; charset=utf-8"
JSON = "application/json"

# Served verbatim. The admin's link carries ?v=<version>, so an update busts the cache.
FILES = {
    "/": ("kiosk.html", HTML),
    "/index.html": ("kiosk.html", HTML),
    "/admin.css": ("admin.css", "text/css; charset=utf-8"),
    "/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
}


def make_handler(
    db: Database, images_dir: Path, store: SettingsStore, picks: Picks,
    featured: Featured, panel: Panel | None, status: Status,
):
    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT
        head = False

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
            self._body(body)

        def _send_cached(self, body: bytes, content_type: str):
            # no-cache + ETag lets an unchanged refresh return a bodyless 304.
            etag = f'"{hashlib.md5(body).hexdigest()}"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            self.end_headers()
            self._body(body)

        def _body(self, body: bytes):
            if not self.head:
                self.wfile.write(body)

        def _query(self) -> dict[str, list[str]]:
            return parse_qs(urlparse(self.path).query)

        def _context(self, settings: Settings) -> modes.Context:
            # commit stays False: the kiosk must never advance the bird of the day.
            return modes.context(
                db, images_dir, picks, featured, settings,
                namer(settings.primary_language, settings.secondary_language, store.path.parent),
                settings.web_size(),
            )

        def _edited(self) -> Settings:
            """Saved settings under the admin's unsaved form state, so the
            preview and its listing show a change before Save."""
            return merged(store.get(), **admin.form_changes(self._query()))

        def _page_png(self):
            self._send_cached(modes.png_bytes(self._context(store.get())), "image/png")

        def _preview_png(self):
            self._send_cached(modes.png_bytes(self._context(self._edited())), "image/png")

        def _state(self):
            # Cheap enough to poll every second: one grouped query, no render.
            settings = store.get()
            self._send(200, json.dumps({
                "token": modes.token(modes.state_key(self._context(settings))),
                "refresh": settings.kiosk_refresh_seconds,
            }).encode(), JSON)

        def _species(self):
            ctx = self._context(self._edited())
            rows = admin.subjects(ctx)
            self._send(200, json.dumps(
                {"count": len(rows), "html": admin.species_html(rows, ctx.namer)}
            ).encode(), JSON)

        def _admin(self):
            settings = store.get()
            html = admin.page(
                self._context(settings), settings, status,
                panel.resolution if panel else None, store.path.parent,
            )
            self._send(200, html.encode(), HTML)

        def _update(self):
            self._send(200, json.dumps({
                "updating": bool(status.updating or status.update_requested),
                "version": __version__,
                "phase": status.update_phase,
                "percent": status.update_percent,
            }).encode(), JSON)

        def _health(self):
            self._send(200, b"ok", "text/plain")

        ROUTES: ClassVar[dict] = {
            "/collage.png": _page_png,
            "/preview.png": _preview_png,
            "/state": _state,
            "/species": _species,
            "/admin": _admin,
            "/update": _update,
            "/health": _health,
        }

        def do_GET(self):
            route = urlparse(self.path).path
            if route in FILES:
                name, content_type = FILES[route]
                self._send_cached((STATIC_DIR / name).read_bytes(), content_type)
            elif route in self.ROUTES:
                self.ROUTES[route](self)
            else:
                self._send(404, b"not found", "text/plain")

        def do_HEAD(self):
            # Full GET, body dropped: a wrong Content-Length is worse than no HEAD.
            self.head = True
            self.do_GET()

        def do_POST(self):
            if urlparse(self.path).path != "/admin":
                self._send(404, b"not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode())
            action = form.get("action", [""])[0]
            if action == "check":
                status.update_error = None
                status.update_available = updates.available(force=True)
            elif action == "update" and status.update_available:
                # The loop installs it: exiting mid-render or mid-push is not safe here.
                status.update_requested = status.update_available
            else:
                store.update(**admin.form_changes(form))
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
    picks: Picks,
    featured: Featured,
    panel: Panel | None = None,
    status: Status | None = None,
) -> None:
    """Blocking server loop. Opens its own DB connection."""
    db = Database(db_path)
    handler = make_handler(db, images_dir, store, picks, featured, panel, status or Status())
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.serve_forever()
