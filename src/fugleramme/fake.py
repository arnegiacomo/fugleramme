"""A fake BirdNET-Go for a hardware-free dev loop, or a fake BirdWeather station.

Serves the slice of `/api/v2` the frame reads - the species summary, the recent
detections, the locale list, the name dictionaries and the species list in the
station's own language - over generated in-memory detections.

The shapes are upstream's, warts and all: a detection carries its date and time
as two strings of station-local wall clock with no offset, beside a `timestamp`
that is RFC3339 with one, as are the summary's `first_heard`/`last_heard`.

With `--birdweather` it is BirdWeather instead, answering the GraphQL the frame
posts to `/graphql` about the stations in `STATIONS`.

Usage:
    fugleramme-fake-detector --count 40 --seed 1
    fugleramme-fake-detector --birdweather
"""

from __future__ import annotations

import argparse
import contextlib
import gzip
import json
import random
import re
import secrets
import threading
from collections import Counter
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, quote, urlparse
from zoneinfo import ZoneInfo

from babel import Locale

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

# Heard among the birds, so everything running against the fake exercises the
# filter: the bat is outside v2.4 and the other two are labels within it.
NON_BIRDS = {
    "Myotis daubentonii": "Daubenton's Bat",
    "Sciurus carolinensis": "Eastern Gray Squirrel",
    "Human vocal": "Human vocal",
}

HEARD = SPECIES + list(NON_BIRDS)

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

# The station's species language (birdnet.locale). Estonian: a label locale with
# no dictionary, the gap the frame's "station" language fills.
LOCALE = "et"

# Label locales in other scripts, in SPECIES order, verbatim from BirdNET v2.4's
# label files - English where a file has no name of its own.
_SCRIPTS = {
    "ja": "ニシクロウタドリ|ヨーロッパシジュウカラ|ズアオアトリ|ユーラシアカササギ|イエスズメ|アオガラ|ヨーロッパコマドリ|ズキンガラス",
    "zh": "欧乌鸫|欧亚大山雀|苍头燕雀|欧亚喜鹊|家麻雀|青山雀|欧亚鸲|冠小嘴乌鸦",
    "ko": "Eurasian Blackbird|노랑배박새|푸른머리되새|Eurasian Magpie|집참새|Eurasian Blue Tit|꼬까울새|Hooded Crow",
    "ar": "شحرور|قرقف كبير|شرشور ظالم-صلنج|العقعق الأوراسي|دوري منزلي|قرقف أزرق|أبو الحناء الأوروبي|غراب ابقع",
    "he": "שחרור|ירגזי מצוי|פרוש מצוי|עקעק זנבתן|דרור הבית|ירגזי כחול|אדום חזה|עורב אפור",
    "th": "Eurasian Blackbird|Great Tit|นกจาบปีกอ่อนหัวเทาอกชมพู|Eurasian Magpie|นกกระจอกใหญ่|Eurasian Blue Tit|European Robin|Hooded Crow",
    "ml": "Eurasian Blackbird|European Great Tit|Common Chaffinch|Eurasian Magpie|അങ്ങാടിക്കുരുവി|Eurasian Blue Tit|European Robin|Hooded Crow",
    "ru": "Чёрный дрозд|Большая синица|Зяблик|Сорока|Домовый воробей|Лазоревка|Зарянка|Серая ворона",
    "el": "(Κοινός) Κότσυφας|Καλόγερος|(Κοινός) Σπίνος|Καρακάξα|Σπιτοσπουργίτης|(Ευρωπαϊκή) Γαλαζοπαπαδίτσα|Κοκκινολαίμης|(Σταχτιά) Κουρούνα",
}
LABELS = {
    "et": {
        "Turdus merula": "musträstas",
        "Parus major": "rasvatihane",
        "Fringilla coelebs": "metsvint",
        "Pica pica": "harakas",
        "Passer domesticus": "koduvarblane",
        "Cyanistes caeruleus": "sinitihane",
        "Erithacus rubecula": "punarind",
        "Corvus cornix": "hallvares",
    },
} | {code: dict(zip(SPECIES, names.split("|"), strict=True)) for code, names in _SCRIPTS.items()}

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

# The fake BirdWeather's stations, (name, timezone, lat, lon) by ID; any other
# answers 404, as upstream does. A detection is heard at the first unless it
# says otherwise.
STATION_ID, OTHER_STATION_ID = "1", "2"
STATION_NAME, STATION_ZONE = "Fake station", "Europe/Oslo"
STATIONS = {
    STATION_ID: (STATION_NAME, STATION_ZONE, 59.91, 10.75),
    OTHER_STATION_ID: ("Other fake station", "Europe/London", 51.51, -0.13),
}


@dataclass(frozen=True)
class Detection:
    id: int
    at: datetime  # station-local, timezone-aware
    scientific_name: str
    confidence: float
    false_positive: bool
    station: str = STATION_ID  # BirdWeather's only

    @property
    def date(self) -> str:
        return self.at.strftime("%Y-%m-%d")

    @property
    def time(self) -> str:
        return self.at.strftime("%H:%M:%S")


def _common(scientific: str) -> str:
    return NAMES["en"][1].get(scientific) or NON_BIRDS.get(scientific, "")


def generate(count: int, seed: int | None = None, heard: list[str] = HEARD) -> list[Detection]:
    """Detections newest first, ages spread from _NEWEST back to _OLDEST."""
    rng = random.Random(seed)
    now = datetime.now().astimezone()
    span = _OLDEST / _NEWEST
    return [
        Detection(
            id=count - i,
            at=now - _NEWEST * span ** (i / max(count - 1, 1)),
            scientific_name=rng.choice(heard),
            confidence=round(rng.uniform(0.6, 0.98), 2),
            false_positive=rng.random() < _FALSE_POSITIVE_RATE,
        )
        for i in range(count)
    ]


def locales(every_language: bool = False) -> dict[str, str]:
    listed = {_LISTED_AS.get(code, code): display for code, (display, _) in NAMES.items()}
    every = {code: str(Locale.parse(code).english_name) for code in LABELS}
    return listed | _NO_DICTIONARY | (every if every_language else {})


def species_all(locale: str) -> dict[str, Any]:
    """`/species/all`: every species in `locale`, English where it has no name.
    "Human vocal" comes back as its own scientific name, as upstream's labels do."""
    listed = {listed: code for code, listed in _LISTED_AS.items()}
    names = LABELS.get(locale) or NAMES.get(listed.get(locale, locale), ("", {}))[1]
    common = {sci: names.get(sci) or _common(sci) or sci for sci in sorted(HEARD)}
    rows = [
        {"label": f"{sci}_{name}", "scientificName": sci, "commonName": name}
        for sci, name in common.items()
    ]
    return {"species": rows, "count": len(rows)}


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


def make_handler(
    rows: list[Detection],
    password: str = "",
    down: bool = False,
    private: bool = True,
    locale: str = LOCALE,
    every_language: bool = False,
):
    dictionaries = {code: names for code, (_, names) in NAMES.items()} | (
        LABELS if every_language else {}
    )
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

        def _gated(self, route: str) -> bool:
            """Which routes want the session. PrivateMode gates the whole API,
            /health included; with it off, /settings/* is gated anyway whenever
            any auth provider is configured - so `private=False` serves every
            detection and still refuses the locale list."""
            return bool(password) and (private or route.startswith(f"{API}/settings/"))

        def _authorized(self) -> bool:
            cookie = SimpleCookie(self.headers.get("Cookie", ""))
            return _SESSION_COOKIE in cookie and cookie[_SESSION_COOKIE].value in sessions

        def _dictionary(self, code: str) -> None:
            names = dictionaries.get(code)
            if names is None:
                self._json(404, {"error": "Species dictionary not found for locale"})
                return
            if self.headers.get("If-None-Match") in (_DICT_ETAG, f"W/{_DICT_ETAG}"):
                self._send(304, b"", {"Etag": _DICT_ETAG})
                return
            body = gzip.compress(json.dumps(names, ensure_ascii=False).encode())
            self._send(
                200,
                body,
                {
                    "Content-Type": "application/json",
                    "Content-Encoding": "gzip",
                    "Etag": _DICT_ETAG,
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
            if self._gated(route) and not self._authorized():
                self._json(401, {"error": "Authentication required"})
                return
            if route == f"{API}/health":
                self._json(200, {"status": "healthy", "version": "fake"})
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
                self._json(200, locales(every_language))
            elif route == f"{API}/settings/birdnet":
                self._json(200, {"locale": locale})
            elif route == f"{API}/species/all":
                self._json(200, species_all(locale))
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


# -- BirdWeather ---------------------------------------------------------------

# A legacy and a current name, which BirdWeather keeps as two species.
GOSHAWK_WAS, GOSHAWK_IS = "Accipiter gentilis", "Astur gentilis"
BIRDWEATHER_HEARD = HEARD + [GOSHAWK_WAS, GOSHAWK_IS]

# BirdWeather's own species for everything the station hears, verbatim from its
# API: name -> (id, commonName, classification, translations in _TRANSLATED order).
# English is the commonName and never a translation. An empty name is a locale
# the species has none in; None is a species `allSpecies` leaves out altogether.
_TRANSLATED = ("no", "de", "zh-SM", "pt-BR", "pt-PT")
_BIRDWEATHER: dict[str, tuple[str, str, str, str | None]] = {
    "Turdus merula": ("35", "Eurasian Blackbird", "avian", "Svarttrost|Amsel|欧乌鸫|Melro|Melro"),
    "Parus major": (
        "11",
        "Great Tit",
        "avian",
        "Kjøttmeis|Kohlmeise|欧亚大山雀|Chapim-real|Chapim-real",
    ),
    "Fringilla coelebs": (
        "25",
        "Common Chaffinch",
        "avian",
        "Bokfink|Buchfink|苍头燕雀|Tentilhão|Tentilhão",
    ),
    "Pica pica": ("52", "Eurasian Magpie", "avian", "Skjære|Elster|欧亚喜鹊|Pega|Pega"),
    "Passer domesticus": (
        "1",
        "House Sparrow",
        "avian",
        "Gråspurv|Haussperling|家麻雀|Pardal|Pardal-do-telhado",
    ),
    "Cyanistes caeruleus": (
        "66",
        "Eurasian Blue Tit",
        "avian",
        "Blåmeis|Blaumeise|蓝山雀|Chapim-azul|Chapim-azul",
    ),
    "Erithacus rubecula": (
        "6",
        "European Robin",
        "avian",
        "Rødstrupe|Rotkehlchen|欧亚鸲|Pisco-de-peito-ruivo|Pisco-de-peito-ruivo",
    ),
    "Corvus cornix": (
        "34",
        "Hooded Crow",
        "avian",
        "Kråke|Nebelkrähe|冠小嘴乌鸦|Gralha-cinzenta|Gralha-cinzenta",
    ),
    GOSHAWK_WAS: ("235", "Northern Goshawk", "avian", "Hønsehauk|Habicht|蒼鷹|Açor|Açor"),
    GOSHAWK_IS: ("19431", "Eurasian Goshawk", "avian", "hønsehauk|Habicht|苍鹰|açor|Açor"),
    "Myotis daubentonii": (
        "17273",
        "Daubentons or Whiskered Bat",
        "bat",
        "Vannflaggermus|Wasserfledermaus||Morcego-de-água|",
    ),
    "Sciurus carolinensis": (
        "17102",
        "Eastern Gray Squirrel",
        "mammal",
        "Østlig Gråekorn|Grauhörnchen|东美松鼠|Esquilo-cinzento-oriental|",
    ),
    "Human vocal": ("17078", "Human vocal", "human", None),
}
# Locales BirdWeather has for only some species: a partial Traditional `zh`, and
# `en-UK` where the British name differs.
_PARTIAL = {
    "Passer domesticus": {"zh": "家麻雀"},
    GOSHAWK_WAS: {"zh": "蒼鷹"},
    "Pica pica": {"en-UK": "Common Magpie"},
}

# Upstream's 404 is its site's own HTML page.
_NOT_FOUND = (
    b"<!DOCTYPE html>\n<html><head><title>Page Not Found :: BirdWeather</title></head></html>\n"
)

# The fields the fake answers, each with its arguments. Only variables are read
# (`first: $first`), never literals: the frame passes everything as one.
_FIELD = re.compile(
    r"(?:(\w+)\s*:\s*)?\b(detections|topSpecies|dailyDetectionCounts|allSpecies|stations)\s*\(([^)]*)\)"
)
_ARG = re.compile(r"(\w+)\s*:\s*\$(\w+)")
_STATION_ARG = re.compile(r"\bstation\s*\(\s*id\s*:\s*\$(\w+)\s*\)")
_UNITS = {
    "minute": timedelta(minutes=1),
    "hour": timedelta(hours=1),
    "day": timedelta(days=1),
    "week": timedelta(weeks=1),
    "month": timedelta(days=30),
    "year": timedelta(days=365),
}
_DEFAULT_PAGE = 100
_MAX_PAGE = 500
_MOST_DETECTION_FIELDS = 3


def _species(name: str) -> dict[str, Any]:
    id_, common, classification, _names = _BIRDWEATHER[name]
    return {
        "id": id_,
        "scientificName": name,
        "commonName": common,
        "classification": classification,
    }


def _stamp(row: Detection) -> str:
    """In the station's own zone, as upstream stamps it."""
    return row.at.astimezone(ZoneInfo(STATIONS[row.station][1])).isoformat(timespec="seconds")


def _in_period(row: Detection, period: dict | None) -> bool:
    """`{count, unit}` back from now, or `{from, to}` as whole UTC days."""
    if not period:
        return True
    if "count" in period:
        return row.at >= datetime.now(UTC) - period["count"] * _UNITS[period["unit"]]
    day = row.at.astimezone(UTC).date().isoformat()
    return period["from"] <= day <= period["to"]


def _bw_detections(rows: list[Detection], args: dict[str, Any]) -> dict[str, Any]:
    """Newest first, a page at a time; the cursor is the next row's index. With no
    period, the last 24 hours only."""
    period = args.get("period") or {"count": 1, "unit": "day"}
    kept = [
        row
        for row in sorted(rows, key=lambda row: row.at, reverse=True)
        if _in_period(row, period)
        and args.get("speciesId") in (None, _BIRDWEATHER[row.scientific_name][0])
        and (
            not args.get("classifications")
            or _BIRDWEATHER[row.scientific_name][2] in args["classifications"]
        )
    ]
    start = int(args.get("after") or 0)
    end = start + min(args.get("first") or _DEFAULT_PAGE, _MAX_PAGE)
    return {
        "pageInfo": {"hasNextPage": end < len(kept), "endCursor": str(end)},
        "nodes": [
            {
                "id": str(row.id),
                "timestamp": _stamp(row),
                "confidence": row.confidence,
                "certainty": "almost_certain",
                "species": _species(row.scientific_name),
            }
            for row in kept[start:end]
        ],
    }


def _top_species(rows: list[Detection], args: dict[str, Any]) -> list[dict[str, Any]]:
    """Every classification: unlike `detections`, topSpecies takes no filter for it."""
    counts = Counter(row.scientific_name for row in rows if _in_period(row, args.get("period")))
    ranked = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))
    return [
        {"count": n, "species": _species(name)} for name, n in ranked[: args.get("limit") or 10]
    ]


def _daily(rows: list[Detection], args: dict[str, Any]) -> list[dict[str, Any]]:
    """UTC days newest first, each species by id. No classification filter here either."""
    days: dict[str, Counter[str]] = {}
    for row in rows:
        if _in_period(row, args.get("period")):
            days.setdefault(row.at.astimezone(UTC).date().isoformat(), Counter())[
                row.scientific_name
            ] += 1
    return [
        {
            "date": day,
            "total": sum(counts.values()),
            "counts": [
                {"count": n, "species": _species(name)}
                for name, n in sorted(
                    counts.items(), key=lambda pair: int(_BIRDWEATHER[pair[0]][0])
                )
            ],
        }
        for day, counts in sorted(days.items(), reverse=True)
    ]


def _all_species(_rows: list[Detection], args: dict[str, Any]) -> dict[str, Any]:
    wanted = set(args.get("ids") or [])
    nodes = []
    for name, (id_, _common, _classification, names) in _BIRDWEATHER.items():
        if id_ not in wanted or names is None:
            continue
        translated = dict(zip(_TRANSLATED, names.split("|"), strict=True)) | _PARTIAL.get(name, {})
        nodes.append(
            {
                **_species(name),
                "translations": [
                    {"locale": locale, "commonName": common}
                    for locale, common in translated.items()
                    if common
                ],
            }
        )
    return {"pageInfo": {"hasNextPage": False}, "nodes": nodes}


def _stations(_rows: list[Detection], _args: dict[str, Any]) -> dict[str, Any]:
    """Every station whatever the box, as loose as upstream's gets: the frame
    cuts the circle itself."""
    return {
        "nodes": [
            {"id": id_, "name": name, "coords": {"lat": lat, "lon": lon}}
            for id_, (name, _zone, lat, lon) in STATIONS.items()
        ]
    }


_ANSWERS = {
    "detections": _bw_detections,
    "topSpecies": _top_species,
    "dailyDetectionCounts": _daily,
    "allSpecies": _all_species,
    "stations": _stations,
}


def graphql(rows: list[Detection], query: str, variables: dict[str, Any]) -> dict | None:
    """The answer to one POST /graphql, or None for a station not in `STATIONS`.
    Not GraphQL at large: the fields above, each over the `stationIds` it is
    given, plus `station`'s own (name, timezone and the earliest and latest
    detection), whatever is selected."""
    fields = _FIELD.findall(query)
    asked = sum(field == "detections" for _alias, field, _args in fields)
    if asked > _MOST_DETECTION_FIELDS:
        message = (
            f"Query requests {asked} detection fields (limit {_MOST_DETECTION_FIELDS}). "
            "Split them across requests, or use the detections export for bulk access."
        )
        return {"errors": [{"message": message}]}
    data: dict[str, Any] = {}
    for alias, field, args in fields:
        given = {name: variables.get(var) for name, var in _ARG.findall(args)}
        ids = given.get("stationIds")
        heard = [row for row in rows if ids is None or row.station in ids]
        data[alias or field] = _ANSWERS[field](heard, given)
    named = _STATION_ARG.search(query)
    if named is None:
        return {"data": data}
    id_ = variables.get(named.group(1))
    if id_ not in STATIONS:
        return None
    stamps = [_stamp(row) for row in sorted(rows, key=lambda row: row.at) if row.station == id_]
    about = {
        "id": id_,
        "name": STATIONS[id_][0],
        "timezone": STATIONS[id_][1],
        "earliestDetectionAt": stamps[0] if stamps else None,
        "latestDetectionAt": stamps[-1] if stamps else None,
    }
    return {"data": data | {"station": about}}


def make_birdweather_handler(rows: list[Detection], down: bool = False):
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: bytes, kind: str) -> None:
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if down:
                self._send(503, b"Service unavailable", "text/plain")
                return
            if urlparse(self.path).path != "/graphql":
                self._send(404, _NOT_FOUND, "text/html; charset=utf-8")
                return
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))))
            answer = graphql(rows, request["query"], request.get("variables") or {})
            if answer is None:
                self._send(404, _NOT_FOUND, "text/html; charset=utf-8")
                return
            body = json.dumps(answer, ensure_ascii=False).encode()
            self._send(200, body, "application/json; charset=utf-8")

    return Handler


def serve(
    rows: list[Detection],
    host: str = "127.0.0.1",
    port: int = BIRDNET_PORT,
    password: str = "",
    down: bool = False,
    private: bool = True,
    locale: str = LOCALE,
    every_language: bool = False,
    birdweather: bool = False,
) -> ThreadingHTTPServer:
    """Start the fake on a daemon thread. Port 0 asks the OS for one - read it
    back from `server_address[1]`. `birdweather` serves a BirdWeather station
    instead of BirdNET-Go, which only `down` applies to."""
    handler = (
        make_birdweather_handler(rows, down)
        if birdweather
        else make_handler(rows, password, down, private, locale, every_language)
    )
    httpd = ThreadingHTTPServer((host, port), handler)
    # `shutdown()` blocks until the loop next comes round, so the default half second
    # is half a second per fake the tests start and stop.
    threading.Thread(target=lambda: httpd.serve_forever(poll_interval=0.01), daemon=True).start()
    return httpd


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=BIRDNET_PORT)
    parser.add_argument("--count", type=int, default=40, help="detections to generate")
    parser.add_argument("--seed", type=int, help="fix the generated detections")
    parser.add_argument(
        "--auth", metavar="PASSWORD", default="", help="simulate PrivateMode: 401 until login"
    )
    parser.add_argument(
        "--auth-names-only",
        action="store_true",
        help="with --auth: leave the detections open and gate only /settings/*",
    )
    parser.add_argument("--down", action="store_true", help="answer every request 503")
    parser.add_argument(
        "--locale", default=LOCALE, help="the station's species language (birdnet.locale)"
    )
    parser.add_argument(
        "--every-language",
        action="store_true",
        help="also serve a dictionary for every label locale the fake has, in any script, "
        "so each is its own Language entry; BirdNET-Go serves only its 16 UI locales",
    )
    parser.add_argument(
        "--birdweather",
        action="store_true",
        help="be BirdWeather's GraphQL instead, serving two stations",
    )
    args = parser.parse_args()

    rows = generate(args.count, args.seed, BIRDWEATHER_HEARD if args.birdweather else HEARD)
    if args.birdweather:  # a third heard at the other station, so the two make one page
        rows = [replace(row, station=OTHER_STATION_ID) if row.id % 3 == 0 else row for row in rows]
    httpd = serve(
        rows,
        args.host,
        args.port,
        args.auth,
        args.down,
        private=not args.auth_names_only,
        locale=args.locale,
        every_language=args.every_language,
        birdweather=args.birdweather,
    )
    address = f"http://{args.host}:{httpd.server_address[1]}"
    if args.birdweather:
        pages = ", ".join(f"{address}/stations/{id_}" for id_ in STATIONS)
        print(f"fake BirdWeather stations: {pages}")
    else:
        print(f"fake BirdNET-Go on {address}{API}")
    with contextlib.suppress(KeyboardInterrupt):
        threading.Event().wait()
    httpd.shutdown()


if __name__ == "__main__":
    main()
