"""Route invariants: what the kiosk and the admin actually get over the wire."""

from __future__ import annotations

import hashlib
import hmac
import io
import json
import logging
import re
import socket
import threading
import time
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from types import SimpleNamespace

import pytest
from PIL import Image

from fugleramme import api
from fugleramme.api import ApiSource
from fugleramme.picks import Picks
from fugleramme.settings import Settings, SettingsStore
from fugleramme.status import Status
from fugleramme.web import LOGIN, LOGOUT, admin, server

SETTINGS = "s.json"
PASSWORD = "wren-house"


def _serve(tmp_path, source, store=None, panel=None):
    """A served frame with artwork for two of the fake's species."""
    style = tmp_path / "images" / "classic"
    (style / "birds").mkdir(parents=True)
    for key in ("turdus-merula", "parus-major"):
        Image.new("RGBA", (120, 90), (40, 40, 40, 255)).save(style / "birds" / f"{key}.png")

    handler = server.make_handler(
        source,
        tmp_path / "images",
        store or SettingsStore(tmp_path / SETTINGS),
        Picks(tmp_path / "artwork.json"),
        panel,
        Status(),
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()


@pytest.fixture
def frame(tmp_path, source):
    yield from _serve(tmp_path, source(count=40, seed=0))


@pytest.fixture
def stranded(tmp_path, source):
    """The same frame over a detector that will not answer."""
    yield from _serve(tmp_path, source(down=True))


@pytest.fixture
def locked(tmp_path, source):
    """The same frame with a password on the admin (#52)."""
    store = SettingsStore(
        tmp_path / SETTINGS, Settings(admin_password=PASSWORD, require_sign_in=True)
    )
    yield from _serve(tmp_path, source(count=40, seed=0), store=store)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The 303 is the answer we want: it carries the session cookie."""

    def redirect_request(self, *args, **kwargs):
        return None


def _fetch(
    url: str,
    method: str = "GET",
    headers: dict | None = None,
    data: bytes | None = None,
    follow: bool = True,
):
    request = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    open_it = urllib.request.urlopen if follow else urllib.request.build_opener(_NoRedirect).open
    try:
        with open_it(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.status, dict(error.headers), error.read()


def _post(url: str, fields: dict, headers: dict | None = None):
    body = urllib.parse.urlencode(fields).encode()
    return _fetch(url, "POST", headers, data=body, follow=False)


def _signed_in(base: str, password: str = PASSWORD) -> dict:
    """What a browser holds after the login form: the session cookie, as a header."""
    _status, headers, _body = _post(base + LOGIN, {"password": password})
    return {"Cookie": headers["Set-Cookie"].split(";")[0]}


def _attempts(handler) -> dict:
    """The limiter's table, through the closure make_handler keeps it in."""
    cells = handler._throttled.__code__.co_freevars
    return handler._throttled.__closure__[cells.index("attempts")].cell_contents


BROWSER = {"Accept": "text/html,application/xhtml+xml"}


@pytest.mark.parametrize(
    "route,content_type",
    [
        ("/", "text/html; charset=utf-8"),
        ("/index.html", "text/html; charset=utf-8"),
        ("/admin.css", "text/css; charset=utf-8"),
        ("/admin.js", "text/javascript; charset=utf-8"),
        ("/admin", "text/html; charset=utf-8"),
        ("/collage.png", "image/png"),
        ("/preview.png", "image/png"),
        ("/state", "application/json"),
        ("/species", "application/json"),
        ("/update", "application/json"),
        ("/health", "text/plain"),
    ],
)
def test_every_route_answers_with_what_it_promises(frame, route, content_type):
    status, headers, body = _fetch(frame + route)
    assert status == 200
    assert headers["Content-Type"] == content_type
    assert len(body) == int(headers["Content-Length"]) > 0


def test_an_unknown_route_is_a_404(frame):
    assert _fetch(frame + "/nope")[0] == 404


def test_a_page_that_cannot_reach_the_detector_says_so(stranded):
    """A 503 the kiosk retries past, not a blank page it would swap onto the glass."""
    for route in ("/collage.png", "/preview.png", "/state", "/species"):
        status, _headers, body = _fetch(stranded + route)
        assert status == 503
        assert b"detector unavailable" in body


def test_the_admin_still_renders_with_the_detector_gone(stranded):
    status, _headers, body = _fetch(stranded + "/admin")
    assert status == 200
    assert b"detector unreachable" in body


def _raw(url: str, request: str | bytes) -> tuple[str, bytes]:
    """One request down a socket of our own: an HTTP client discards a HEAD body
    for us, so nothing above this level can prove the server withheld it. Bytes
    for a request no str would survive."""
    host, port = url.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        sock.sendall(request if isinstance(request, bytes) else request.encode())
        chunks = iter(lambda: sock.recv(4096), b"")  # HTTP/1.0: read to close
        head, _, body = b"".join(chunks).partition(b"\r\n\r\n")
    return head.decode(), body


def test_head_answers_with_the_headers_and_no_body(frame):
    for route in ("/admin.css", "/admin", "/collage.png"):
        head, body = _raw(frame, f"HEAD {route} HTTP/1.0\r\n\r\n")
        assert "200 OK" in head
        assert body == b""
        declared = int(re.search(r"Content-Length: (\d+)", head).group(1))
        assert declared == len(_fetch(frame + route)[2]) > 0


def test_an_unchanged_page_revalidates_to_304(frame):
    """The kiosk re-requests the collage on every swap; only the ETag keeps it
    from re-downloading a megabyte it already holds."""
    for route in ("/collage.png", "/admin.css"):
        etag = _fetch(frame + route)[1]["ETag"]
        status, _, body = _fetch(frame + route, headers={"If-None-Match": etag})
        assert status == 304 and body == b""


def test_the_preview_reads_an_unsaved_form_without_saving_it(frame, tmp_path):
    saved = json.loads(_fetch(frame + "/species")[2])
    edited = json.loads(_fetch(frame + "/species?mode=latest")[2])

    assert saved["count"] > 1  # the collage: every species in the window
    assert edited["count"] == 1  # the latest bird alone

    _fetch(frame + "/preview.png?mode=latest&rotation=90")
    assert not (tmp_path / SETTINGS).exists()  # only a POST may write


def _size(body: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(body)).size


def test_the_preview_shows_the_panel_s_page_and_the_kiosk_its_own(tmp_path, source):
    """Unlocked, the two pages differ (#147); the admin previews what is on the
    glass, in the panel's shape at the web height."""
    store = SettingsStore(
        tmp_path / SETTINGS, Settings(web_lock=False, web_aspect="16:9", web_resolution="720p")
    )
    panel = SimpleNamespace(resolution=(800, 480))
    for base in _serve(tmp_path, source(count=40, seed=0), store=store, panel=panel):
        assert _size(_fetch(base + "/collage.png")[2]) == (1280, 720)
        assert _size(_fetch(base + "/preview.png")[2]) == (1200, 720)
        assert _size(_fetch(base + "/preview.png?rotation=90")[2]) == (720, 1200)


def test_with_no_panel_the_preview_is_the_kiosk_s_page(frame):
    assert _size(_fetch(frame + "/preview.png")[2]) == _size(_fetch(frame + "/collage.png")[2])
    assert _size(_fetch(frame + "/preview.png?web_aspect=16:9")[2]) == (1920, 1080)


def test_the_species_listing_marks_what_the_collage_cannot_draw(frame):
    body = json.loads(_fetch(frame + "/species")[2])
    assert 'class="noart"' in body["html"]
    assert body["html"].count("<li") == body["count"]


def test_the_connection_test_answers_over_the_wire(frame):
    body = urllib.parse.urlencode({"detector_url": "http://127.0.0.1:1"}).encode()
    request = urllib.request.Request(frame + "/detector", data=body, method="POST")
    with urllib.request.urlopen(request, timeout=10) as response:
        answer = json.loads(response.read())
    assert answer["state"] == "unreachable"


def test_the_kiosk_holds_its_last_page_when_the_detector_goes_away(tmp_path, detector, monkeypatch):
    """The kiosk mirrors the glass, so a blip must not blank every viewer with a
    broken image."""
    monkeypatch.setattr(api, "_TTL", 0)  # or the cached answer, not the hold, is what passes
    url, fake = detector(count=40, seed=0)
    for base in _serve(tmp_path, ApiSource(url)):
        status, _headers, page = _fetch(base + "/collage.png")
        assert status == 200

        fake.shutdown()
        fake.server_close()
        assert _fetch(base + "/species")[0] == 503  # the detector really is gone

        status, _headers, held = _fetch(base + "/collage.png")
        assert (status, held) == (200, page)


def test_an_emptied_field_clears_the_setting(frame, tmp_path):
    """ "None" for the second language and a cleared credential both post blank,
    and a dropped blank reads as "field absent, keep what is saved"."""
    store = SettingsStore(tmp_path / SETTINGS)

    def post(**fields):
        body = urllib.parse.urlencode(fields).encode()
        request = urllib.request.Request(frame + "/admin", data=body, method="POST")
        with urllib.request.urlopen(request, timeout=10):
            pass
        return store.get()

    assert post(mode="collage", secondary_language="nb").secondary_language == "nb"
    assert post(mode="collage", secondary_language="").secondary_language == ""

    saved = post(detector_url="http://127.0.0.1:1", detector_username="bird")
    assert saved.detector_username == "bird"
    assert post(detector_url="http://127.0.0.1:1", detector_username="").detector_username == ""


def test_a_detector_that_stays_away_is_reported_once(stranded, caplog):
    """The kiosk polls every few seconds, so one warning per failed request would
    fill the journal for as long as the detector is gone."""
    with caplog.at_level(logging.WARNING, logger="fugleramme.web.server"):
        for _ in range(8):
            assert _fetch(stranded + "/state")[0] == 503

    assert len(caplog.records) == 1


def test_pointing_at_another_detector_drops_the_held_page(tmp_path, detector, monkeypatch):
    """Holding a page through a blip is the point of it, but after a deliberate
    switch that page is another station's birds, not a stale copy of ours."""
    monkeypatch.setattr(api, "_TTL", 0)
    url, fake = detector(count=40, seed=0)
    store = SettingsStore(tmp_path / SETTINGS, Settings(detector_url=url))

    for base in _serve(tmp_path, api.Configured(store), store=store):
        assert _fetch(base + "/collage.png")[0] == 200

        store.update(detector_url="http://127.0.0.1:1")
        assert _fetch(base + "/collage.png")[0] == 503

        store.update(detector_url=url)
        assert _fetch(base + "/collage.png")[0] == 200

        fake.shutdown()  # the same detector going quiet still holds
        fake.server_close()
        assert _fetch(base + "/collage.png")[0] == 200


def test_every_route_is_either_the_kiosk_or_behind_the_password(tmp_path, source):
    """The gate is only as good as its list: a route added to the admin and
    forgotten here would serve strangers with the whole suite still green."""
    handler = server.make_handler(
        source(),
        tmp_path,
        SettingsStore(tmp_path / SETTINGS),
        Picks(tmp_path / "artwork.json"),
        None,
        Status(),
    )
    known = set(server.FILES) | set(handler.ROUTES) | {"/detector"}  # /detector is POST-only
    assert known - server.GATED == {
        "/",
        "/index.html",
        "/admin.css",
        "/admin.js",
        "/collage.png",
        "/state",
        "/paper.png",
        "/health",
    }


def test_a_password_sends_a_browser_to_the_login_page(locked):
    """The frame's own page, never the browser's credential prompt: the door has
    to look like the product it opens."""
    for route in sorted(server.GATED):
        status, headers, _body = _fetch(locked + route, headers=BROWSER, follow=False)
        assert (status, headers["Location"]) == (303, LOGIN)
        assert "WWW-Authenticate" not in headers

    # The admin's own fetches are not browsing: they get an answer, not a page.
    assert _fetch(locked + "/species")[0] == 401
    assert _fetch(locked + LOGIN, headers=BROWSER)[0] == 200


def test_a_password_leaves_the_kiosk_open(locked):
    """The kiosk is the product: a password must not shut strangers out of the birds."""
    for route in ("/", "/collage.png", "/state", "/paper.png", "/admin.css", "/health"):
        assert _fetch(locked + route)[0] == 200


def test_signing_in_opens_the_admin_and_signing_out_shuts_it(locked):
    session = _signed_in(locked)
    assert _fetch(locked + "/admin", headers=session)[0] == 200
    assert _fetch(locked + "/preview.png", headers=session)[0] == 200

    # Signing out revokes the session, not just the browser's copy of the cookie.
    assert _post(locked + LOGOUT, {}, session)[0] == 303
    assert _fetch(locked + "/admin", headers=session | BROWSER, follow=False)[0] == 303


def test_the_switch_opens_the_admin_without_losing_the_password(locked, tmp_path):
    """Off is how you open the frame up again for a while; the password is still
    there, and the door shuts again when the switch goes back on."""
    session = _signed_in(locked)
    # What the form posts with the box unticked: the declaration, and no box.
    unticked = {"checkboxes": "require_sign_in", "admin_password": admin.PASSWORD_SET}
    assert _post(locked + "/admin", unticked, session)[0] == 303

    saved = SettingsStore(tmp_path / SETTINGS).get()
    assert saved.require_sign_in is False
    assert saved.admin_password == PASSWORD
    assert _fetch(locked + "/admin")[0] == 200  # no session, and none wanted

    _post(locked + "/admin", {"require_sign_in": "on", "checkboxes": "require_sign_in"})
    assert _fetch(locked + "/species")[0] == 401


def test_a_switch_with_no_password_behind_it_locks_nobody_out(frame, tmp_path):
    """Half a door is no door: it must read as open rather than shut with no key."""
    _post(frame + "/admin", {"require_sign_in": "on", "checkboxes": "require_sign_in"})
    assert SettingsStore(tmp_path / SETTINGS).get().require_sign_in is True
    assert _fetch(frame + "/admin")[0] == 200


def test_only_the_saved_password_signs_anyone_in(locked):
    assert _post(locked + LOGIN, {"password": PASSWORD})[0] == 303
    assert _post(locked + LOGIN, {"password": "sparrow"})[0] == 401
    assert _post(locked + LOGIN, {"password": ""})[0] == 401


def test_an_open_frame_hands_out_no_session(frame, tmp_path):
    """The empty password an open frame has saved matches the empty box on the
    login page, which would otherwise mint a session and a secret to sign it."""
    status, headers, _body = _post(frame + LOGIN, {"password": ""})
    assert (status, "Set-Cookie" in headers) == (303, False)
    assert SettingsStore(tmp_path / SETTINGS).get().session_secret == ""


def test_a_password_the_owner_can_type_signs_in(tmp_path, source):
    """Norwegian keyboards exist. compare_digest refuses a str it cannot encode,
    and the login page is the only door: a crash here locks the owner out for good."""
    store = SettingsStore(
        tmp_path / SETTINGS, Settings(admin_password="fuglerø", require_sign_in=True)
    )
    for base in _serve(tmp_path, source(count=40, seed=0), store=store):
        assert _fetch(base + "/admin", headers=_signed_in(base, "fuglerø"))[0] == 200
        assert _post(base + LOGIN, {"password": "fuglera"})[0] == 401


def test_a_cookie_forged_before_the_first_sign_in_is_refused(locked):
    """With no secret minted yet, an empty signing key would leave the cookie
    derivable from the password - every gated route an oracle, with no login
    page in the way to rate limit it."""
    key = hmac.new(b"", PASSWORD.encode(), hashlib.sha256).digest()
    forged = server._sign(key, int(time.time()) + 600)
    assert _fetch(locked + "/species", headers={"Cookie": f"{server.COOKIE}={forged}"})[0] == 401


def test_a_stranger_cannot_sign_the_owner_out(locked, tmp_path):
    """Signing out rotates the secret, so an unauthenticated one would throw the
    owner out and write to the SD card as often as anyone cared to ask."""
    session = _signed_in(locked)
    secret = SettingsStore(tmp_path / SETTINGS).get().session_secret

    assert _post(locked + LOGOUT, {})[0] == 401
    assert SettingsStore(tmp_path / SETTINGS).get().session_secret == secret
    assert _fetch(locked + "/admin", headers=session)[0] == 200


@pytest.mark.parametrize("served", ["frame", "locked"])
def test_a_hostile_content_length_is_answered_not_crashed(request, served):
    """Read before any gate, so a stranger reaches it on a frame with a password."""
    base = request.getfixturevalue(served)
    head, _body = _raw(base, "POST /admin HTTP/1.0\r\nContent-Length: abc\r\n\r\n")
    assert "400" in head

    head, _body = _raw(base, f"POST /admin HTTP/1.0\r\nContent-Length: {2**30}\r\n\r\n")
    assert "413" in head

    # read(-1) would read to EOF instead, down a socket the sender holds open.
    head, _body = _raw(base, "POST /admin HTTP/1.0\r\nContent-Length: -1\r\n\r\n")
    assert "400" in head


def test_a_body_that_is_not_utf_8_is_answered_not_crashed(locked):
    """Decoded before any gate, so the bytes are a stranger's to choose."""
    head, _body = _raw(locked, b"POST /admin HTTP/1.0\r\nContent-Length: 2\r\n\r\n\xff\xfe")
    assert "400" in head


def test_an_expired_session_is_refused(locked, monkeypatch):
    """A week is the whole point of the cookie, so it has to actually run out."""
    monkeypatch.setattr(server, "SESSION_SECONDS", 0)
    assert _fetch(locked + "/species", headers=_signed_in(locked))[0] == 401


def test_a_forged_or_stale_cookie_is_refused(locked):
    for cookie in (
        f"{server.COOKIE}=99999999999.notasignature",
        f"{server.COOKIE}={server._sign(b'whatever', 99999999999)}",  # wrong key
        f"{server.COOKIE}={'9' * 5000}.sig",  # past the length cap, and past int()'s own
        "nonsense",
        server.COOKIE,
    ):
        assert _fetch(locked + "/species", headers={"Cookie": cookie})[0] == 401


def test_changing_the_password_ends_the_sessions_it_let_in(locked):
    """The reason to change it is usually that someone knew the old one."""
    session = _signed_in(locked)
    assert _post(locked + "/admin", {"admin_password": "new-one"}, session)[0] == 303

    assert _fetch(locked + "/species", headers=session)[0] == 401
    assert _fetch(locked + "/admin", headers=_signed_in(locked, "new-one"))[0] == 200


def test_setting_the_old_password_back_does_not_revive_its_sessions(locked):
    """The key is the secret and the password together, so a pure change of
    password is undone by changing it back."""
    session = _signed_in(locked)
    assert _post(locked + "/admin", {"admin_password": "new-one"}, session)[0] == 303

    back = _signed_in(locked, "new-one")
    assert _post(locked + "/admin", {"admin_password": PASSWORD}, back)[0] == 303
    assert _fetch(locked + "/species", headers=session)[0] == 401


def test_signing_out_of_an_open_frame_writes_nothing(frame, tmp_path):
    """Nothing is signed in and nothing is gated, so a stranger reaches this one:
    rotating a secret nobody uses would be an SD-card write for the asking."""
    status, headers, _body = _post(frame + LOGOUT, {})
    assert (status, headers["Location"]) == (303, LOGIN)
    assert not (tmp_path / SETTINGS).exists()


def test_signing_out_sends_the_browser_back_to_the_door(locked):
    session = _signed_in(locked)
    status, headers, _body = _post(locked + LOGOUT, {}, session)
    assert (status, headers["Location"]) == (303, LOGIN)
    assert headers["Set-Cookie"].startswith(f"{server.COOKIE}=;")


def test_the_login_page_sends_a_signed_in_browser_on(locked):
    """Nothing to do at the door once it is open."""
    status, headers, _body = _fetch(locked + LOGIN, headers=_signed_in(locked), follow=False)
    assert (status, headers["Location"]) == (303, "/admin")


def test_a_signed_out_browser_posting_the_form_lands_on_the_login_page(locked):
    """A Save with an expired session is a browser, not a fetch: it gets the door,
    not a 401 it would render as a broken page."""
    status, headers, _body = _post(locked + "/admin", {"mode": "latest"}, BROWSER)
    assert (status, headers["Location"]) == (303, LOGIN)


def test_the_session_cookie_is_kept_from_script_and_from_other_sites(locked):
    """The frame is plain HTTP on a LAN, so these two flags are the whole defence."""
    _status, headers, _body = _post(locked + LOGIN, {"password": PASSWORD})
    assert "HttpOnly" in headers["Set-Cookie"]
    assert "SameSite=Lax" in headers["Set-Cookie"]


def test_the_login_page_says_what_went_wrong(locked):
    """The door is the only way back in: an unexplained refusal reads as a broken
    frame, and a lockout has to say it is one."""
    status, _headers, body = _post(locked + LOGIN, {"password": "sparrow"})
    assert (status, b"Wrong password." in body) == (401, True)

    for _ in range(server.TRIES):
        _post(locked + LOGIN, {"password": "sparrow"})
    status, headers, body = _post(locked + LOGIN, {"password": "sparrow"})
    assert (status, b"Too many attempts" in body) == (429, True)
    assert headers["Retry-After"] == str(server.WINDOW)


def test_guessing_is_rate_limited(locked):
    """Five tries a quarter hour, as BirdNET-Go allows."""
    for _ in range(server.TRIES):
        assert _post(locked + LOGIN, {"password": "sparrow"})[0] == 401

    assert _post(locked + LOGIN, {"password": "sparrow"})[0] == 429
    assert _post(locked + LOGIN, {"password": PASSWORD})[0] == 429  # the real one waits too


def test_a_cross_site_post_is_refused(frame, tmp_path):
    """An open frame takes a POST from anyone on the network, so the only thing
    standing between it and a drive-by is what the browser says about the sender."""
    elsewhere = {"Sec-Fetch-Site": "cross-site"}

    assert _post(frame + "/admin", {"mode": "latest"}, elsewhere)[0] == 403
    assert _post(frame + "/detector", {"mode": "latest"}, elsewhere)[0] == 403
    assert not (tmp_path / SETTINGS).exists()

    # The admin's own Save, and anything that sends no opinion at all.
    _post(frame + "/admin", {"mode": "latest"}, {"Sec-Fetch-Site": "same-origin"})
    assert SettingsStore(tmp_path / SETTINGS).get().mode == "latest"


def test_an_anonymous_503_keeps_the_detector_address_to_itself(stranded):
    """/state answers strangers, and which detector this frame reads is not theirs."""
    status, _headers, body = _fetch(stranded + "/state")
    assert (status, body) == (503, b"detector unavailable")


def test_behind_a_proxy_one_guesser_does_not_lock_out_the_owner(tmp_path, source):
    """Every request arrives from the proxy, so keying on the socket would hand a
    stranger a fifteen-minute lockout of the frame's owner, over and over."""
    store = SettingsStore(
        tmp_path / SETTINGS,
        Settings(admin_password=PASSWORD, require_sign_in=True, behind_proxy=True),
    )
    for base in _serve(tmp_path, source(count=40, seed=0), store=store):
        guesser = {"X-Forwarded-For": "198.51.100.7"}
        for _ in range(server.TRIES + 1):
            _post(base + LOGIN, {"password": "sparrow"}, guesser)
        assert _post(base + LOGIN, {"password": PASSWORD}, guesser)[0] == 429

        owner = {"X-Forwarded-For": "192.0.2.4"}
        assert _post(base + LOGIN, {"password": PASSWORD}, owner)[0] == 303


def test_a_guesser_cannot_dodge_the_limit_with_a_header_the_proxy_did_not_set(tmp_path, source):
    """Most proxies pass X-Real-IP through untouched, so only the hop they append
    to X-Forwarded-For is their word."""
    store = SettingsStore(
        tmp_path / SETTINGS,
        Settings(admin_password=PASSWORD, require_sign_in=True, behind_proxy=True),
    )
    for base in _serve(tmp_path, source(count=40, seed=0), store=store):
        for n in range(server.TRIES):
            spoofed = {"X-Forwarded-For": "198.51.100.7", "X-Real-IP": f"10.0.0.{n}"}
            _post(base + LOGIN, {"password": "sparrow"}, spoofed)
        guesser = {"X-Forwarded-For": "198.51.100.7"}
        assert _post(base + LOGIN, {"password": PASSWORD}, guesser)[0] == 429


def test_a_forwarded_header_is_ignored_unless_the_frame_is_behind_a_proxy(locked):
    """Any stranger on the LAN can write that header, so honouring it unasked
    would hand a guesser a fresh identity every try."""
    for n in range(server.TRIES):
        forged = {"X-Forwarded-For": f"198.51.100.{n}"}
        assert _post(locked + LOGIN, {"password": "sparrow"}, forged)[0] == 401

    assert _post(locked + LOGIN, {"password": PASSWORD})[0] == 429


def test_x_real_ip_alone_keys_the_limiter(tmp_path, source):
    """A proxy that sets only that one still has to throttle who it reports, and
    only them."""
    store = SettingsStore(
        tmp_path / SETTINGS,
        Settings(admin_password=PASSWORD, require_sign_in=True, behind_proxy=True),
    )
    for base in _serve(tmp_path, source(count=40, seed=0), store=store):
        guesser = {"X-Real-IP": "198.51.100.7"}
        for _ in range(server.TRIES):
            assert _post(base + LOGIN, {"password": "sparrow"}, guesser)[0] == 401

        assert _post(base + LOGIN, {"password": PASSWORD}, guesser)[0] == 429
        assert _post(base + LOGIN, {"password": PASSWORD}, {"X-Real-IP": "192.0.2.4"})[0] == 303


def test_a_forged_address_cannot_grow_the_limiter_without_end(tmp_path, source, monkeypatch):
    """Behind a proxy the key is a header a stranger writes, so an uncapped table
    is a way to fill the Pi's memory one request at a time."""
    monkeypatch.setattr(server, "TRACKED", 4)
    store = SettingsStore(
        tmp_path / SETTINGS,
        Settings(admin_password=PASSWORD, require_sign_in=True, behind_proxy=True),
    )
    handler = server.make_handler(
        source(), tmp_path, store, Picks(tmp_path / "artwork.json"), None, Status()
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True).start()
    try:
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        for n in range(server.TRACKED * 5):
            _post(base + LOGIN, {"password": "sparrow"}, {"X-Forwarded-For": f"198.51.100.{n}"})
        assert len(_attempts(handler)) == server.TRACKED
    finally:
        httpd.shutdown()


def test_the_window_runs_out_and_the_owner_gets_back_in(locked, monkeypatch):
    """A quarter of an hour, not a lockout that has to be ended from the Pi."""
    for _ in range(server.TRIES):
        _post(locked + LOGIN, {"password": "sparrow"})
    assert _post(locked + LOGIN, {"password": PASSWORD})[0] == 429

    monkeypatch.setattr(server, "WINDOW", 0)  # the quarter hour, elapsed
    assert _post(locked + LOGIN, {"password": PASSWORD})[0] == 303


def test_getting_in_clears_what_was_counted(locked):
    """Four fumbles and then the right password must not leave the owner one
    mistake from a lockout for the rest of the quarter hour."""
    for _ in range(2):
        for _ in range(server.TRIES - 1):
            assert _post(locked + LOGIN, {"password": "sparrow"})[0] == 401
        assert _post(locked + LOGIN, {"password": PASSWORD})[0] == 303


def test_a_cookie_carrying_a_high_byte_is_refused(locked):
    """compare_digest raises on a str it cannot encode, and this one arrives from
    a stranger: a 500 here is a crash for the asking. Quoted, because that is the
    one shape the cookie parser hands such a value on rather than dropping it."""
    cookie = f'{server.COOKIE}="9999999999.sig\xff"'.encode("latin-1")
    head, _body = _raw(locked, b"GET /species HTTP/1.0\r\nCookie: " + cookie + b"\r\n\r\n")
    assert "401" in head


def test_a_signed_out_post_saves_nothing(locked, tmp_path):
    """A refusal that wrote anyway would be the whole feature undone."""
    assert _post(locked + "/admin", {"mode": "latest"})[0] == 401
    assert not (tmp_path / SETTINGS).exists()

    _post(locked + "/admin", {"mode": "latest"}, _signed_in(locked))
    assert SettingsStore(tmp_path / SETTINGS).get().mode == "latest"
