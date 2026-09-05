"""A fake BirdNET-Go for a hardware-free dev loop.

Serves the slice of `/api/v2` the frame reads - the species summary, the recent
detections, the locale list and the name dictionaries - over generated
in-memory detections.

The shapes are upstream's, warts and all: a detection carries its date and time
as two strings of station-local wall clock with no offset, while the summary's
`first_heard`/`last_heard` are RFC3339 with one.

Usage:
    fugleramme-fake-detector --count 40 --seed 1
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import random
import secrets
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlparse

from .config import BIRDNET_PORT

# Common Norwegian species; some without artwork (Cyanistes, Erithacus), which the collage omits.
SPECIES = [
    "Turdus merula",
    "Parus major",
    "Fringilla coelebs",
    "Pica pica",
    "Passer domesticus",
    "Cyanistes caeruleus",
    "Erithacus rubecula",
    "Corvus cornix",
]

# Two languages for those species, as BirdNET-Go's own dictionaries give them:
# lowercase in Norwegian, titled in English. code -> (display name, {species: name})
NAMES: dict[str, tuple[str, dict[str, str]]] = {
    "nb": (
        "Norwegian",
        {
            "Turdus merula": "svarttrost",
            "Parus major": "kjøttmeis",
            "Fringilla coelebs": "bokfink",
            "Pica pica": "skjære",
            "Passer domesticus": "gråspurv",
            "Cyanistes caeruleus": "blåmeis",
            "Erithacus rubecula": "rødstrupe",
            "Corvus cornix": "kråke",
        },
    ),
    "en": (
        "English",
        {
            "Turdus merula": "Eurasian Blackbird",
            "Parus major": "Great Tit",
            "Fringilla coelebs": "Common Chaffinch",
            "Pica pica": "Eurasian Magpie",
            "Passer domesticus": "House Sparrow",
            "Cyanistes caeruleus": "Eurasian Blue Tit",
            "Erithacus rubecula": "European Robin",
            "Corvus cornix": "Hooded Crow",
        },
    ),
}

# BirdNET-Go lists locales it has no dictionary for, so the frame's probe has to
# intersect the two. The list spells Norwegian "no" where the dictionary
# answers "nb" - upstream's own disagreement, which languages._ALIASES handles.
_LISTED_AS = {"nb": "no"}
_NO_DICTIONARY = {"el": "Greek", "pt-br": "Brazilian Portuguese"}

API = "/api/v2"

# gothic's default session cookie, set by the OAuth callback that completes a login.
_SESSION_COOKIE = "_gothic_session"

_DICT_ETAG = '"fake"'

# The generated detections span this, geometrically, so every lookback the admin
# offers (6h through 30 days, and all time) has content whatever --count is.
_NEWEST = timedelta(minutes=2)
_OLDEST = timedelta(days=90)

_CLIP_SECONDS = 3
_FALSE_POSITIVE_RATE = 0.15


@dataclass(frozen=True)
class Detection:
    id: int
    at: datetime  # station-local, timezone-aware
    scientific_name: str
    confidence: float
    false_positive: bool

    @property
    def date(self) -> str:
        return self.at.strftime("%Y-%m-%d")

    @property
    def time(self) -> str:
        return self.at.strftime("%H:%M:%S")


def _common(scientific: str) -> str:
    return NAMES["en"][1].get(scientific, "")


def generate(count: int, seed: int | None = None) -> list[Detection]:
    """Detections newest first, ages spread from _NEWEST back to _OLDEST."""
    rng = random.Random(seed)
    now = datetime.now().astimezone()
    span = _OLDEST / _NEWEST
    return [
        Detection(
            id=count - i,
            at=now - _NEWEST * span ** (i / max(count - 1, 1)),
            scientific_name=rng.choice(SPECIES),
            confidence=round(rng.uniform(0.6, 0.98), 2),
            false_positive=rng.random() < _FALSE_POSITIVE_RATE,
        )
        for i in range(count)
    ]


def locales() -> dict[str, str]:
    return {_LISTED_AS.get(code, code): display for code, (display, _) in NAMES.items()} | (
        _NO_DICTIONARY
    )


def summary(
    rows: list[Detection], start: str = "", end: str = "", limit: int = 0
) -> list[dict[str, Any]]:
    """`/analytics/species/summary`: per-species aggregate, most detections first.
    Upstream's analytics drop false positives and filter on the local date."""
    groups: dict[str, list[Detection]] = {}
    for row in rows:
        if row.false_positive or (start and row.date < start) or (end and row.date > end):
            continue
        groups.setdefault(row.scientific_name, []).append(row)
    out = [
        {
            "scientific_name": name,
            "common_name": _common(name),
            # species_code is omitempty upstream and this fixture has no eBird codes.
            "count": len(group),
            "first_heard": min(r.at for r in group).isoformat(timespec="seconds"),
            "last_heard": max(r.at for r in group).isoformat(timespec="seconds"),
            "avg_confidence": round(sum(r.confidence for r in group) / len(group), 4),
            "max_confidence": max(r.confidence for r in group),
            "thumbnail_url": f"{API}/media/image/{quote(name)}",
        }
        for name, group in sorted(groups.items(), key=lambda item: -len(item[1]))
    ]
    return out[:limit] if limit > 0 else out


def detections(rows: list[Detection], limit: int = 10) -> list[dict[str, Any]]:
    """`/detections/recent`: newest first, false positives included - only
    analytics excludes them, here they are flagged by `verified`."""
    return [
        {
            "id": row.id,
            "date": row.date,
            "time": row.time,
            "timestamp": row.at.isoformat(timespec="seconds"),
            "beginTime": row.at.isoformat(timespec="seconds"),
            "endTime": (row.at + timedelta(seconds=_CLIP_SECONDS)).isoformat(timespec="seconds"),
            "speciesCode": "",
            "scientificName": row.scientific_name,
            "commonName": _common(row.scientific_name),
            "confidence": row.confidence,
            "verified": "false_positive" if row.false_positive else "unverified",
            "locked": False,
        }
        for row in rows[:limit]
    ]


def _int(query: dict[str, list[str]], name: str, default: int = 0) -> int:
    try:
        return int(query.get(name, [""])[0])
    except ValueError:
        return default


def _one(query: dict[str, list[str]], name: str) -> str:
    return query.get(name, [""])[0]


def make_handler(rows: list[Detection], password: str = "", down: bool = False):
    dictionaries = {code: names for code, (_, names) in NAMES.items()}
    codes: set[str] = set()
    sessions: set[str] = set()

    class Handler(BaseHTTPRequestHandler):
        head = False

        def _send(self, status: int, body: bytes, headers: dict[str, str]) -> None:
            self.send_response(status)
            for name, value in headers.items():
                self.send_header(name, value)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if not self.head:
                self.wfile.write(body)

        def _json(self, status: int, payload: Any) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode()
            self._send(status, body, {"Content-Type": "application/json"})

        def _authorized(self) -> bool:
            if not password:
                return True
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return _SESSION_COOKIE in cookie and cookie[_SESSION_COOKIE].value in sessions

        def _dictionary(self, code: str) -> None:
            names = dictionaries.get(code)
            if names is None:
                self._json(404, {"error": "Species dictionary not found for locale"})
                return
            if self.headers.get("If-None-Match") in (_DICT_ETAG, f"W/{_DICT_ETAG}"):
                self._send(304, b"", {"ETag": _DICT_ETAG})
                return
            body = gzip.compress(json.dumps(names, ensure_ascii=False).encode())
            self._send(
                200,
                body,
                {
                    "Content-Type": "application/json",
                    "Content-Encoding": "gzip",
                    "ETag": _DICT_ETAG,
                },
            )

        def _callback(self, query: dict[str, list[str]]) -> None:
            code = _one(query, "code")
            if code not in codes:
                self._json(401, {"error": "Unable to complete login at this time"})
                return
            codes.discard(code)
            token = secrets.token_hex(16)
            sessions.add(token)
            self._send(
                302,
                b"",
                {
                    "Set-Cookie": f"{_SESSION_COOKIE}={token}; Path=/; HttpOnly",
                    "Location": _one(query, "redirect") or "/",
                },
            )

        def _login(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            try:
                request = json.loads(self.rfile.read(length) or b"{}")
            except ValueError:
                self._json(400, {"success": False, "message": "Invalid login request"})
                return
            # Upstream checks the credentials against its own basic-auth user; the
            # fake takes any non-empty username and matches --auth on the password.
            username, given = request.get("username", ""), request.get("password", "")
            now = datetime.now().astimezone().isoformat(timespec="seconds")
            if not username or not given:
                self._json(
                    400,
                    {
                        "success": False,
                        "message": "Username and password are required",
                        "timestamp": now,
                    },
                )
                return
            if given != password:
                self._json(
                    401, {"success": False, "message": "Invalid credentials", "timestamp": now}
                )
                return
            code = secrets.token_hex(16)
            codes.add(code)
            redirect = request.get("redirectUrl") or "/"
            self._json(
                200,
                {
                    "success": True,
                    "message": "Login successful - complete OAuth flow",
                    "username": username,
                    "timestamp": now,
                    "redirectUrl": f"{API}/auth/callback"
                    f"?code={quote(code)}&redirect={quote(redirect)}",
                },
            )

        def do_GET(self) -> None:
            if down:
                self._json(503, {"error": "Service unavailable"})
                return
            url = urlparse(self.path)
            route, query = url.path, parse_qs(url.query)
            if route == f"{API}/auth/callback":
                self._callback(query)
                return
            if route == f"{API}/health":
                # Outside upstream's auth group, so PrivateMode answers here too.
                self._json(200, {"status": "healthy", "version": "fake"})
                return
            if not self._authorized():
                self._json(401, {"error": "Authentication required"})
                return
            if route == f"{API}/ping":
                self._json(200, {"status": "ok"})
            elif route == f"{API}/analytics/species/summary":
                self._json(
                    200,
                    summary(
                        rows,
                        _one(query, "start_date"),
                        _one(query, "end_date"),
                        _int(query, "limit"),
                    ),
                )
            elif route == f"{API}/detections/recent":
                self._json(200, detections(rows, _int(query, "limit", 10) or 10))
            elif route == f"{API}/settings/locales":
                self._json(200, locales())
            elif route.startswith(f"{API}/species/dictionary/"):
                self._dictionary(route.rsplit("/", 1)[1])
            else:
                self._json(404, {"error": "Not found"})

        def do_HEAD(self) -> None:
            # Full GET, body dropped: languages.py probes the dictionaries this way.
            self.head = True
            self.do_GET()

        def do_POST(self) -> None:
            if down:
                self._json(503, {"error": "Service unavailable"})
                return
            if urlparse(self.path).path != f"{API}/auth/login":
                self._json(404, {"error": "Not found"})
                return
            self._login()

    return Handler


def serve(
    rows: list[Detection],
    host: str = "127.0.0.1",
    port: int = BIRDNET_PORT,
    password: str = "",
    down: bool = False,
) -> ThreadingHTTPServer:
    """Start the fake on a daemon thread. Port 0 asks the OS for one - read it
    back from `server_address[1]`."""
    httpd = ThreadingHTTPServer((host, port), make_handler(rows, password, down))
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=BIRDNET_PORT)
    parser.add_argument("--count", type=int, default=40, help="detections to generate")
    parser.add_argument("--seed", type=int, help="fix the generated detections")
    parser.add_argument(
        "--auth", metavar="PASSWORD", default="", help="simulate PrivateMode: 401 until login"
    )
    parser.add_argument("--down", action="store_true", help="answer every request 503")
    args = parser.parse_args()

    httpd = serve(generate(args.count, args.seed), args.host, args.port, args.auth, args.down)
    print(f"fake BirdNET-Go on http://{args.host}:{httpd.server_address[1]}{API}")
    with contextlib.suppress(KeyboardInterrupt):
        threading.Event().wait()
    httpd.shutdown()


if __name__ == "__main__":
    main()
