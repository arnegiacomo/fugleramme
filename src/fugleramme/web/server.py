"""HTTP server for the kiosk and admin views.

The kiosk (`/`) serves one thing: a full-color page of what the frame is
showing, full-screen. It never reloads; instead it polls `/state` and swaps the
image only when the page actually changed, so a new bird appears within one poll
interval with no flash. Presentation settings live at `/admin` and are read per
request from the shared SettingsStore, so a change takes effect without a
restart. The kiosk is open to the LAN; so is the admin until the switch is on
with a password behind it (#52).

Routing and transport only - the admin page itself is built in admin.py, and the
files under static/ are served as they are.

Stdlib http.server only, but threaded with a socket timeout: a serial server is
one silent client away from a dead kiosk, since a connection that never sends a
request blocks the accept loop forever. It shares the render loop's detector
source, so the two halves of a page cost one round trip between them.

A request that cannot reach the detector answers 503 rather than an empty page,
and the kiosk keeps the picture it is holding.
"""

from __future__ import annotations

import base64
import functools
import hashlib
import hmac
import io
import json
import logging
import secrets
import threading
import time
from http.cookies import CookieError, SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

from .. import __version__, modes, updates
from ..languages import namer
from ..panel import Panel, resolution_of
from ..picks import Picks
from ..render.paper import paper_tile
from ..settings import Settings, SettingsStore, merged
from ..source import Source, Unavailable
from ..status import Status
from . import LOGIN, LOGOUT, STATIC_DIR, admin

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15

HTML = "text/html; charset=utf-8"
JSON = "application/json"

# What a password covers (#52). The kiosk stays open whatever is set: it is the
# product, and the demo page and the container's healthcheck read it as strangers.
GATED = frozenset({"/admin", "/preview.png", "/species", "/update", "/detector", LOGOUT})

COOKIE = "fugleramme_session"
SESSION_SECONDS = 7 * 24 * 60 * 60  # a week, the session BirdNET-Go hands out

# Five tries a quarter hour, as BirdNET-Go's login allows. In memory: a frame that
# restarts under someone guessing has bigger problems than a forgotten counter.
TRIES, WINDOW = 5, 15 * 60

# How many addresses the limiter remembers. Behind a proxy the key is a header a
# stranger writes, so the table needs a ceiling.
TRACKED = 1000

MAX_BODY = 1024 * 1024  # what BirdNET-Go's API takes; a settings form is bytes

# Served verbatim. The admin's link carries ?v=<version>, so an update busts the cache.
FILES = {
    "/": ("kiosk.html", HTML),
    "/index.html": ("kiosk.html", HTML),
    "/admin.css": ("admin.css", "text/css; charset=utf-8"),
    "/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
}


@functools.cache
def paper_png() -> bytes:
    buffer = io.BytesIO()
    paper_tile().save(buffer, format="PNG")
    return buffer.getvalue()


def _key(settings: Settings) -> bytes:
    """What the session cookie is signed with: the stored secret mixed with the
    password, so changing the password ends every session signed under the old one."""
    return hmac.new(
        settings.session_secret.encode(), settings.admin_password.encode(), hashlib.sha256
    ).digest()


def _sign(key: bytes, expires: int) -> str:
    signature = hmac.new(key, str(expires).encode(), hashlib.sha256).digest()
    return f"{expires}.{base64.urlsafe_b64encode(signature).decode().rstrip('=')}"


def _valid(key: bytes, cookie: str) -> bool:
    expires, _, _signature = cookie.partition(".")
    # A stranger's cookie reaches this. isdigit() is true of "²" and of Arabic-Indic
    # digits that int() then refuses, a long run of them trips int()'s own limit, and
    # compare_digest will not take a str carrying a high byte: all three raise.
    if not cookie.isascii() or not expires.isdigit() or len(expires) > 12:
        return False
    when = int(expires)
    return when > time.time() and hmac.compare_digest(cookie, _sign(key, when))


def _set_cookie(value: str, seconds: int) -> str:
    # No Secure: the frame is http://<pi>:8080 and the flag would drop the cookie
    # on every LAN install. Lax keeps it off another site's cross-site POST.
    return f"{COOKIE}={value}; Max-Age={seconds}; Path=/; HttpOnly; SameSite=Lax"


def make_handler(
    source: Source,
    images_dir: Path,
    store: SettingsStore,
    picks: Picks,
    panel: Panel | None,
    status: Status,
):
    # Held across requests: an outage must not blank every viewer at once. Tied
    # to the detector that drew it, since another station's birds are not ours.
    last_page: bytes | None = None
    last_from = ""
    # The kiosk polls every few seconds, so one warning per failed request would
    # never stop. Say it once, and again on recovery.
    unreachable = False
    # Failed sign-ins per client address, newest last, under `guessing`.
    attempts: dict[str, list[float]] = {}
    guessing = threading.Lock()

    def note(message: str, gone: bool) -> None:
        nonlocal unreachable
        if gone and not unreachable:
            log.warning("%s", message)
        elif not gone and unreachable:
            log.info("Detector reachable again")
        else:
            log.debug("%s", message)
        unreachable = gone

    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT
        head = False
        # Set when a route answered from a held copy rather than the detector, so
        # a served page is not mistaken for the detector having come back.
        degraded = False

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def log_error(self, fmt, *args):
            log.warning("%s %s", self.address_string(), fmt % args)

        def _send(
            self, status: int, body: bytes, content_type: str, extra: dict[str, str] | None = None
        ):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            for name, value in (extra or {}).items():
                self.send_header(name, value)
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

        def _allowed(self) -> bool:
            """Whether this request may reach the admin. No password saved leaves it open."""
            settings = store.get()
            if not settings.admin_locked:
                return True
            # Nothing has been signed until the first sign-in mints a secret, and an
            # empty key would leave the signature derivable from the password alone -
            # every gated route an oracle for it, with no login page to rate limit.
            if not settings.session_secret:
                return False
            return _valid(_key(settings), self._session())

        def _session(self) -> str:
            try:
                jar = SimpleCookie(self.headers.get("Cookie", ""))
            except CookieError:
                return ""  # a stranger's malformed header is not a session
            morsel = jar.get(COOKIE)
            return morsel.value if morsel else ""

        def _ask_to_sign_in(self):
            """A browser is sent to the login page; anything else is told plainly.
            The admin's own fetches land here when a session runs out mid-page."""
            if "text/html" not in self.headers.get("Accept", ""):
                self._send(401, b"sign in at /admin/login", "text/plain")
                return
            self._redirect(LOGIN)

        def _redirect(self, location: str, cookie: str = ""):
            self.send_response(303)
            self.send_header("Location", location)
            if cookie:
                self.send_header("Set-Cookie", cookie)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def _login_page(self, error: str = "", status: int = 200):
            # A refusal says when to come back: the window is what the limiter forgives after.
            extra = {"Retry-After": str(WINDOW)} if status == 429 else None
            self._send(status, admin.login_page(error).encode(), HTML, extra)

        def _sign_in(self, form: dict[str, list[str]]):
            """The password is checked here and nowhere else."""
            settings = store.get()
            if not settings.admin_locked:
                self._redirect("/admin")  # nothing to sign in to, and no secret to mint
                return
            client = self._client()
            # Bytes: compare_digest refuses a str with an "ø" in it, and the form
            # body is UTF-8, so the owner's own password would take the door off.
            typed = form.get("password", [""])[0].encode()
            refused, code = self._attempt(client, typed, settings.admin_password)
            if refused:
                # Written with `guessing` released: a slow reader would hold every
                # other sign-in behind it.
                log.warning("Refused admin sign-in from %s: %s", client, refused)
                self._login_page(refused, code)
                return
            # Minted on the first sign-in rather than at startup, so a frame nobody
            # locked never writes a secret it has no use for.
            if not settings.session_secret:
                settings = store.update(session_secret=secrets.token_urlsafe(32))
            expires = int(time.time()) + SESSION_SECONDS
            cookie = _set_cookie(_sign(_key(settings), expires), SESSION_SECONDS)
            self._redirect("/admin", cookie)

        def _attempt(self, client: str, typed: bytes, password: str) -> tuple[str, int]:
            """Whether this guess is refused, and with what. The check and the record
            are one step: apart, guesses arriving together all read the same count
            and walk straight past the limit."""
            with guessing:
                if self._throttled(client):
                    return "Too many attempts. Try again in fifteen minutes.", 429
                if not hmac.compare_digest(typed, password.encode()):
                    attempts.setdefault(client, []).append(time.time())
                    return "Wrong password.", 401
                attempts.pop(client, None)
                return "", 200

        def _client(self) -> str:
            """Who a failed sign-in is held against. Behind a proxy every request
            arrives from the proxy, so keying on the socket would let one attacker
            lock the owner out along with themselves."""
            if not store.get().behind_proxy:
                return self.client_address[0]
            # X-Forwarded-For first: a proxy appends to it, so its last hop is always
            # the proxy's word. X-Real-IP passes through untouched from one that
            # does not set it, and a guesser would send a fresh one each try.
            seen_by_proxy = (
                self.headers.get("X-Forwarded-For") or self.headers.get("X-Real-IP") or ""
            )
            # The rightmost hop is the one the nearest proxy saw. Bounded: it is a
            # header a stranger writes, and it ends up as a dict key.
            return seen_by_proxy.rsplit(",", 1)[-1].strip()[:64] or self.client_address[0]

        def _throttled(self, client: str) -> bool:
            now = time.time()
            for address in list(attempts):  # all of them, or a scanner's leavings pile up
                fresh = [at for at in attempts[address] if now - at < WINDOW]
                if fresh:
                    attempts[address] = fresh
                else:
                    del attempts[address]
            # Room for the attempt about to be recorded, so the table stops at TRACKED.
            while len(attempts) >= TRACKED:
                del attempts[next(iter(attempts))]  # insertion order: the oldest first
            return len(attempts.get(client, [])) >= TRIES

        def _query(self) -> dict[str, list[str]]:
            return parse_qs(urlparse(self.path).query, keep_blank_values=True)

        def _context(self, settings: Settings) -> modes.Context:
            return modes.context(
                source,
                images_dir,
                picks,
                settings,
                namer(settings.primary_language, settings.secondary_language, store.path.parent),
                settings.web_size(resolution_of(panel)),
            )

        def _edited(self) -> Settings:
            """Saved settings under the admin's unsaved form state, so the
            preview and its listing show a change before Save."""
            return merged(store.get(), **admin.form_changes(self._query()))

        def _page_png(self):
            nonlocal last_page, last_from
            if source.base_url != last_from:
                last_page, last_from = None, source.base_url
            try:
                last_page = modes.png_bytes(self._context(store.get()))
            except Unavailable as exc:
                if last_page is None:
                    raise
                self.degraded = True
                note(f"Detector unavailable, serving the last kiosk page ({exc})", True)
            self._send_cached(last_page, "image/png")

        def _preview_png(self):
            self._send_cached(modes.png_bytes(self._context(self._edited())), "image/png")

        def _state(self):
            # Cheap enough to poll: one grouped query, no render.
            token = modes.token(modes.state_key(self._context(store.get())))
            self._send(200, json.dumps({"token": token}).encode(), JSON)

        def _species(self):
            ctx = self._context(self._edited())
            rows = admin.subjects(ctx)
            self._send(
                200,
                json.dumps(
                    {"count": len(rows), "html": admin.species_html(rows, ctx.namer)}
                ).encode(),
                JSON,
            )

        def _admin(self):
            settings = store.get()
            html = admin.page(
                self._context(settings),
                settings,
                status,
                resolution_of(panel),
                panel is not None,
                store.path.parent,
            )
            self._send(200, html.encode(), HTML)

        def _update(self):
            self._send(
                200,
                json.dumps(
                    {
                        "updating": bool(status.updating or status.update_requested),
                        "version": __version__,
                        "phase": status.update_phase,
                        "percent": status.update_percent,
                    }
                ).encode(),
                JSON,
            )

        def _paper(self):
            self._send_cached(paper_png(), "image/png")

        def _health(self):
            self._send(200, b"ok", "text/plain")

        ROUTES: ClassVar[dict] = {
            "/collage.png": _page_png,
            "/preview.png": _preview_png,
            "/state": _state,
            "/paper.png": _paper,
            "/species": _species,
            "/admin": _admin,
            "/update": _update,
            "/health": _health,
        }

        def do_GET(self):
            route = urlparse(self.path).path
            if route == LOGIN:
                if self._allowed():
                    self._redirect("/admin")  # signed in, or nothing to sign in to
                else:
                    self._login_page()
                return
            if route in GATED and not self._allowed():
                self._ask_to_sign_in()
                return
            if route in FILES:
                name, content_type = FILES[route]
                self._send_cached((STATIC_DIR / name).read_bytes(), content_type)
            elif route in self.ROUTES:
                try:
                    self.ROUTES[route](self)
                    note("", self.degraded)
                except Unavailable as exc:
                    # The address stays in the log: /state and /collage.png answer
                    # strangers, and which detector this frame reads is not theirs.
                    note(f"{route}: {exc}", True)
                    self._send(503, b"detector unavailable", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_HEAD(self):
            # Full GET, body dropped: a wrong Content-Length is worse than no HEAD.
            self.head = True
            self.do_GET()

        def do_POST(self):
            route = urlparse(self.path).path
            # A browser attaches Basic credentials to a cross-site POST as readily as a
            # cookie, so any page could re-point a frame whose admin is signed in.
            # Anything sending no Sec-Fetch-Site (curl, an old browser) is let through.
            if self.headers.get("Sec-Fetch-Site") == "cross-site":
                self._send(403, b"cross-site post refused", "text/plain")
                return
            try:
                length = int(self.headers.get("Content-Length", 0))
            except ValueError:
                length = -1
            if length < 0:  # read(-1) reads to EOF, on a socket the sender holds open
                self._send(400, b"bad content-length", "text/plain")
                return
            if length > MAX_BODY:  # this is a form, and it is read before any gate
                self._send(413, b"too large", "text/plain")
                return
            try:
                body = self.rfile.read(length).decode()
            except UnicodeDecodeError:
                self._send(400, b"bad body", "text/plain")
                return
            # keep_blank_values: an emptied field is a change, not an absent one.
            # "None" for the second language and a cleared credential both post blank.
            form = parse_qs(body, keep_blank_values=True)
            if route == LOGIN:
                self._sign_in(form)
                return
            if route in GATED and not self._allowed():
                self._ask_to_sign_in()
                return
            if route == LOGOUT:
                # A new secret, so the cookie just cleared cannot be handed back: one
                # user, one session. An open frame answers strangers here, and has
                # nothing to revoke.
                if store.get().admin_locked:
                    store.update(session_secret=secrets.token_urlsafe(32))
                self._redirect(LOGIN, _set_cookie("", 0))
                return
            # POST, not a query: the connection test carries a password.
            if route == "/detector":
                answer = admin.connection(form, store.get())
                self._send(200, json.dumps(answer).encode(), JSON)
                return
            if route != "/admin":
                self._send(404, b"not found", "text/plain")
                return
            action = form.get("action", [""])[0]
            if action == "check":
                status.update_error = None
                status.update_available = updates.available(force=True)
            elif action == "update" and status.update_available and not updates.in_container():
                # The loop installs it: exiting mid-render or mid-push is not safe here.
                status.update_requested = status.update_available
            else:
                changes = admin.form_changes(form)
                password = changes.get("admin_password")
                # Without this the old password, set back, would revive the cookies it signed.
                if password is not None and password != store.get().admin_password:
                    changes["session_secret"] = secrets.token_urlsafe(32)
                store.update(**changes)
            self._redirect("/admin")

    return Handler


def serve(
    source: Source,
    images_dir: Path,
    host: str,
    port: int,
    store: SettingsStore,
    picks: Picks,
    panel: Panel | None = None,
    status: Status | None = None,
) -> ThreadingHTTPServer:
    """Start the kiosk on a daemon thread. Port 0 asks the OS for one - read it
    back from `server_address[1]`."""
    handler = make_handler(source, images_dir, store, picks, panel, status or Status())
    httpd = ThreadingHTTPServer((host, port), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
