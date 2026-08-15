"""Route invariants: what the kiosk and the admin actually get over the wire."""

from __future__ import annotations

import json
import random
import re
import socket
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest
from PIL import Image

from fugleramme.db import Database
from fugleramme.featured import Featured
from fugleramme.picks import Picks
from fugleramme.seed import seed
from fugleramme.settings import SettingsStore
from fugleramme.status import Status
from fugleramme.web import server

SETTINGS = "s.json"


@pytest.fixture
def frame(tmp_path):
    """A served frame over a seeded record, with artwork for two of its species."""
    random.seed(0)
    seed(tmp_path / "birdnet.db", 40)
    style = tmp_path / "images" / "classic"
    style.mkdir(parents=True)
    for key in ("turdus-merula", "parus-major"):
        Image.new("RGBA", (120, 90), (40, 40, 40, 255)).save(style / f"{key}.png")

    handler = server.make_handler(
        Database(tmp_path / "birdnet.db"), tmp_path / "images",
        SettingsStore(tmp_path / SETTINGS), Picks(tmp_path / "artwork.json"),
        Featured(tmp_path / "featured.json"), None, Status(),
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()


def _fetch(url: str, method: str = "GET", headers: dict | None = None):
    request = urllib.request.Request(url, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as error:
        return error.status, dict(error.headers), error.read()


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


def _raw(url: str, request: str) -> tuple[str, bytes]:
    """One request down a socket of our own: an HTTP client discards a HEAD body
    for us, so nothing above this level can prove the server withheld it."""
    host, port = url.removeprefix("http://").split(":")
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        sock.sendall(request.encode())
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


def test_the_species_listing_marks_what_the_collage_cannot_draw(frame):
    body = json.loads(_fetch(frame + "/species")[2])
    assert 'class="noart"' in body["html"]
    assert body["html"].count("<li") == body["count"]
