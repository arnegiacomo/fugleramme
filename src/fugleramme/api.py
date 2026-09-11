"""BirdNET-Go's REST API as the frame's detection source.

The frame reads `/api/v2` rather than the SQLite behind it, so the detector can
be the container beside it or an install elsewhere on the network:

    GET /analytics/species/summary   -> per-species aggregate, false positives dropped
    GET /detections/recent           -> the newest rows, false positives included

Both are filtered to birds on the way in (`taxa.is_bird`), so a station that also
classifies bats or noise offers nothing above this module that it cannot draw.

`Security.PrivateMode` gates the whole API behind a session cookie, so with
credentials configured a 401 triggers one login and one retry.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, datetime, timedelta, tzinfo
from http.cookiejar import CookieJar
from itertools import count
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener

from .names import canonical, normalize
from .settings import SettingsStore
from .source import NEEDS_PASSWORD, Detection, Species, Unavailable
from .taxa import is_bird

log = logging.getLogger(__name__)

API = "/api/v2"

# BirdNET-Go's basic auth is a password, but its login endpoint rejects an empty
# username and compares the one it is given against `security.basicauth.clientid`.
# This is that setting's default, and what BirdNET-Go's own login page sends.
CLIENT_ID = "birdnet-client"

# One serial per ApiSource. `station` is which detector, as whom: `Configured`
# builds a new source for a changed address or changed credentials alike, so a
# cache keyed on it expires for either - and the password stays out of the key.
_stations = count(1)

_TIMEOUT = 5
_TTL = 3  # seconds: the loop and the server share one page's worth of answers
_DAY = "%Y-%m-%d"

# /detections/recent carries false positives, so the newest row is not always
# one the frame may show. Over-fetch and take the first that is.
_LATEST_SCAN = 10

# The summary only takes dates, so a sub-day window is counted by hand from the
# feed - which takes no date filter, leaving the row count as the only lever.
_WINDOW_SCAN = 1000


class _NoRedirect(HTTPRedirectHandler):
    """The login callback's 302 is the response we want: it carries the session
    cookie."""

    def redirect_request(self, *args, **kwargs):
        return None


def _loads(body: bytes, what: str) -> Any:
    try:
        return json.loads(body)
    except ValueError as error:
        raise Unavailable(f"{what} answered no JSON") from error


def _headers(response: Any) -> dict[str, str]:
    """Response headers, keyed lowercase. urllib's own mapping is case-insensitive
    and a plain dict of it is not, so a caller would be at the mercy of the case
    upstream sent - BirdNET-Go spells it "Etag"."""
    return {name.lower(): value for name, value in response.headers.items()}


def _local() -> tzinfo:
    return datetime.now().astimezone().tzinfo or UTC


def _time(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def _window(hours: int) -> tuple[str, str]:
    """The summary filters on whole dates, so a window of hours becomes the days
    it touches. It rounds outwards: a day-long window is never short."""
    if hours <= 0:
        return "", ""
    now = datetime.now().astimezone()
    return (now - timedelta(hours=hours)).strftime(_DAY), now.strftime(_DAY)


def _heard_since(row: dict, since: datetime | None) -> bool:
    """Whether a summary row falls in the window the dates only approximate.
    Upstream aggregates last_heard over the same rounded range, so a row whose
    newest call is before the cutoff was not heard in the window."""
    if since is None:
        return True
    heard = _time(row.get("last_heard") or "")
    return heard is None or heard >= since


def _ranked(counts: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    return sorted(counts, key=lambda pair: (-pair[1], pair[0]))


def _detection(row: dict, offset: tzinfo) -> Detection:
    at = datetime.fromisoformat(f"{row['date']}T{row['time']}").replace(tzinfo=offset)
    return Detection(
        id=int(row.get("id") or 0),
        detected_at=at,
        scientific_name=canonical(row["scientificName"]),
        confidence=float(row.get("confidence") or 0.0),
        clip_path=row.get("clipName") or None,
    )


def _at(value: Any) -> datetime:
    """A summary stamp for ordering. An unreadable one sorts oldest, so a parse
    failure can never win `last_heard` nor lose `first_heard`."""
    stamp = _time(value) if isinstance(value, str) else None
    return stamp or datetime.min.replace(tzinfo=UTC)


def _fold(into: dict, row: dict) -> None:
    """Add a legacy-named row's totals to the current-named row it belongs to."""
    into["count"] = into.get("count", 0) + row.get("count", 0)
    if (best := row.get("max_confidence")) is not None:
        held = into.get("max_confidence")
        into["max_confidence"] = best if held is None else max(held, best)
    for field, keep in (("first_heard", min), ("last_heard", max)):
        stamps = [value for value in (into.get(field), row.get(field)) if value]
        if stamps:
            into[field] = keep(stamps, key=_at)


def _merged(rows: Any) -> Any:
    """One row per bird, still most detections first.

    BirdNET-Go canonicalizes a scientific name as it stores a detection but
    leaves what it already stored alone, so a station upgraded across a
    reclassification serves one bird as two species forever.

    A row the merge cannot read passes through untouched rather than dropped:
    the callers' own guards are what turn a malformed summary into Unavailable.
    """
    if not isinstance(rows, list):
        return rows
    merged: dict[str, dict] = {}
    passed: list[Any] = []
    for row in rows:
        name = row.get("scientific_name") if isinstance(row, dict) else None
        if not isinstance(name, str):
            passed.append(row)
            continue
        key = normalize(name)
        held = merged.get(key)
        if held is None:
            merged[key] = {**row, "scientific_name": canonical(name)}
            continue
        _fold(held, row)
    ordered = sorted(merged.values(), key=lambda row: -(row.get("count") or 0))
    return ordered + passed


class ApiSource:
    """A `source.Source` over one BirdNET-Go instance."""

    def __init__(
        self,
        base_url: str,
        username: str = "",
        password: str = "",
        timeout: int = _TIMEOUT,
    ):
        self.base_url = base_url.rstrip("/")
        self.station = f"{self.base_url}#{next(_stations)}"
        self._api = self.base_url + API
        self._username, self._password = username, password
        self._timeout = timeout
        self._opener = build_opener(_NoRedirect, HTTPCookieProcessor(CookieJar()))
        self._lock = threading.RLock()
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._not_birds: set[str] = set()

    def _is_bird(self, name: str, common: str = "") -> bool:
        """`taxa.is_bird`, naming what it drops the first time it sees it. Once
        per species rather than per poll, and a bird that vanishes because the
        alias map is behind the detector says so here or nowhere. The common name
        is the row's own: another model's label has none here to look up."""
        if is_bird(name):
            return True
        if name not in self._not_birds:
            self._not_birds.add(name)
            named = f"{common} ({name})" if common else name
            log.info("Not a bird, ignoring detections of %s", named)
        return False

    # -- transport ---------------------------------------------------------

    def _url(self, path: str, params: dict[str, Any] | None = None) -> str:
        query = urlencode({k: v for k, v in (params or {}).items() if v not in ("", None)})
        return f"{self._api}{path}" + (f"?{query}" if query else "")

    def _open(
        self,
        url: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        data: bytes | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        request = Request(url, data=data, method=method, headers=headers or {})
        request.add_header("Accept-Encoding", "gzip")
        if data is not None:
            request.add_header("Content-Type", "application/json")
        try:
            with self._opener.open(request, timeout=self._timeout) as response:
                body = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    body = gzip.decompress(body)
                return response.status, _headers(response), body
        except HTTPError as error:
            return error.code, _headers(error), error.read()
        except (URLError, OSError) as error:
            raise Unavailable(f"{self.base_url} unreachable: {error}") from error

    def _login(self) -> bool:
        """Whether a session was established. Two steps: the login hands out a
        code, and following the callback it names is what sets the cookie.

        A refusal is reported, not raised, so the caller's own 401 stands and
        says what it always meant. The detail goes to the log: a reader wants
        "credentials rejected", not a client id and a status line.
        """
        user = self._username or CLIENT_ID
        credentials = json.dumps({"username": user, "password": self._password})
        status, _head, body = self._open(
            self._url("/auth/login"), "POST", data=credentials.encode()
        )
        redirect = _loads(body, "login").get("redirectUrl") if status == 200 else ""
        if not redirect:
            log.warning("Login to %s as %r answered %s", self.base_url, user, status)
            return False
        status, _head, _body = self._open(urljoin(self.base_url, redirect))
        if status in (200, 302):
            return True
        log.warning("Login callback answered %s", status)
        return False

    def request(
        self,
        path: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        """One API call. Raises Unavailable when the detector cannot be reached;
        any status it does answer with is returned as it came. A lapsed session
        is worth exactly one re-login."""
        url = self._url(path, params)
        status, response_headers, body = self._open(url, method, headers)
        if status == 401 and self._password and self._login():
            return self._open(url, method, headers)
        return status, response_headers, body

    def _get(self, path: str, **params: Any) -> Any:
        status, _headers, body = self.request(path, params=params)
        if status != 200:
            raise Unavailable(f"GET {path} answered {status}")
        return _loads(body, f"GET {path}")

    def _cached(self, key: tuple, fetch: Callable[[], Any]) -> Any:
        """A few seconds of memory: one page render costs one round trip per
        endpoint rather than one per caller. Failures are cached too - a name
        that will not resolve costs a DNS timeout per call, and one admin page
        makes five."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and time.monotonic() < entry[0]:
                if isinstance(entry[1], Unavailable):
                    raise entry[1]
                return entry[1]
            try:
                value: Any = fetch()
            except Unavailable as error:
                self._cache[key] = (time.monotonic() + _TTL, error)
                raise
            self._cache[key] = (time.monotonic() + _TTL, value)
            return value

    def _summary(self, start: str = "", end: str = "") -> list[dict]:
        return self._cached(
            ("summary", start, end),
            lambda: [
                row
                for row in _merged(
                    self._get("/analytics/species/summary", start_date=start, end_date=end)
                )
                if self._is_bird(row["scientific_name"], row.get("common_name") or "")
            ],
        )

    def _feed(self, limit: int) -> list[dict]:
        return self._cached(("recent", limit), lambda: self._get("/detections/recent", limit=limit))

    def _offset(self) -> tzinfo:
        """The station's own UTC offset. The feed gives a bare wall clock and
        the summary's timestamps carry an offset, so it is read off there rather
        than assuming the detector shares the frame's timezone."""
        for row in self._summary():
            stamp = _time(row.get("last_heard") or row.get("first_heard") or "")
            if stamp and stamp.tzinfo:
                return stamp.tzinfo
        return _local()

    # -- source ------------------------------------------------------------

    def latest(self) -> Detection | None:
        rows = self.recent(_LATEST_SCAN)
        return rows[0] if rows else None

    def recent(self, limit: int = 20) -> list[Detection]:
        offset = self._offset()
        try:
            # Not in `_feed`: `_counted` reads the raw row count to spot a feed
            # that ran out before reaching its cutoff.
            return [
                _detection(row, offset)
                for row in self._feed(limit)
                if row.get("verified") != "false_positive"
                and self._is_bird(row["scientificName"], row.get("commonName") or "")
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise Unavailable(f"unreadable detections: {error}") from error

    def _counted(self, hours: int) -> list[tuple[str, int]] | None:
        """A sub-day window counted off the feed, or None when the feed ran out
        before reaching the cutoff and the count would be short."""
        since = datetime.now(UTC) - timedelta(hours=hours)
        heard = self.recent(_WINDOW_SCAN)
        oldest = min((d.detected_at for d in heard), default=since)
        if oldest > since and len(self._feed(_WINDOW_SCAN)) >= _WINDOW_SCAN:
            log.warning("The %d newest detections do not reach %dh back", _WINDOW_SCAN, hours)
            return None
        return _ranked(Counter(d.scientific_name for d in heard if d.detected_at >= since).items())

    def species_since(self, hours: int = 24) -> list[tuple[str, int]]:
        if 0 < hours < 24 and (counted := self._counted(hours)) is not None:
            return counted
        since = datetime.now(UTC) - timedelta(hours=hours) if hours > 0 else None
        # The dates round outwards, so last_heard settles which species are
        # really in the window. Their counts still cover the rounded range: that
        # shifts the ranking, never which birds reach the page.
        return _ranked(
            (row["scientific_name"], row["count"])
            for row in self._summary(*_window(hours))
            if _heard_since(row, since)
        )

    def life_list(self) -> list[Species]:
        try:
            species = [
                Species(row["scientific_name"], datetime.fromisoformat(row["first_heard"]))
                for row in self._summary()
                if row.get("first_heard")
            ]
        except (KeyError, TypeError, ValueError) as error:
            raise Unavailable(f"unreadable species summary: {error}") from error
        return sorted(species, key=lambda s: (s.first_seen, s.scientific_name))

    def stats(self) -> dict:
        rows = self._summary()  # most detections first, as _merged leaves them
        return {
            "total": sum(row["count"] for row in rows),
            "species": len(rows),
            "last_24h": sum(count for _name, count in self.species_since(24)),
            "top": [
                {
                    "scientific_name": row["scientific_name"],
                    "n": row["count"],
                    "best": row.get("max_confidence"),
                }
                for row in rows[:10]
            ],
        }

    def close(self) -> None:
        """No connection to release: every call is its own request."""


class Configured:
    """The detector the settings name, rebuilt when they name another one.

    `ApiSource` binds its address and credentials at construction, so the render
    loop, the HTTP server and `languages` hold this wrapper instead and a swap
    reaches all three at once. Nothing may be called out to while the lock is
    held: `languages` expires its own caches by station rather than being told.
    """

    def __init__(self, store: SettingsStore, timeout: int = _TIMEOUT):
        self._store = store
        self._timeout = timeout
        self._lock = threading.Lock()
        self._key: tuple[str, str, str] | None = None
        self._source: ApiSource | None = None

    @property
    def source(self) -> ApiSource:
        settings = self._store.get()
        key = (settings.detector_url, settings.detector_username, settings.detector_password)
        with self._lock:
            if key == self._key and self._source is not None:
                return self._source
            if self._key is not None:
                log.info("Detector is now %s", key[0])
            self._key, self._source = key, ApiSource(*key, timeout=self._timeout)
            return self._source

    def latest(self) -> Detection | None:
        return self.source.latest()

    def recent(self, limit: int = 20) -> list[Detection]:
        return self.source.recent(limit)

    def species_since(self, hours: int = 24) -> list[tuple[str, int]]:
        return self.source.species_since(hours)

    def life_list(self) -> list[Species]:
        return self.source.life_list()

    def stats(self) -> dict:
        return self.source.stats()

    def request(
        self,
        path: str,
        method: str = "GET",
        headers: dict[str, str] | None = None,
        params: dict[str, Any] | None = None,
    ) -> tuple[int, dict[str, str], bytes]:
        return self.source.request(path, method, headers, params)

    @property
    def base_url(self) -> str:
        return self.source.base_url

    @property
    def station(self) -> str:
        return self.source.station

    def close(self) -> None:
        self.source.close()


_DETECTIONS = "/analytics/species/summary"
_NAMES = "/settings/locales"


def _reach(source: ApiSource, path: str) -> tuple[int, str]:
    """(status, failure) for a gated endpoint; status 0 when it was not reached."""
    try:
        return source.request(path)[0], ""
    except Unavailable as error:
        return 0, str(error)


def probe(url: str, username: str = "", password: str = "") -> tuple[str, str]:
    """The admin's connection test: (state, detail), state one of "ok", "auth",
    "names" or "unreachable".

    Two endpoints, because BirdNET-Go gates them differently. PrivateMode covers
    the whole API, but `/settings/*` sits behind authentication whenever any
    provider is enabled at all - so a detector can serve every detection
    anonymously and still refuse the locale list the language menu is built
    from. Testing only the detections would call that frame connected and leave
    the reader wondering why the birds have nothing but scientific names.

    One source for both, so the session the first call logs in serves the second.
    """
    refused = "credentials rejected" if password else NEEDS_PASSWORD
    source = ApiSource(url, username, password)
    status, failure = _reach(source, _DETECTIONS)
    if status == 0:
        return "unreachable", failure
    if status == 401:
        return "auth", refused
    if status != 200:
        return "unreachable", f"answered {status}"
    status, failure = _reach(source, _NAMES)
    if status == 200:
        return "ok", ""
    if status == 0:  # gone between the two calls, not holding its locale list back
        return "unreachable", failure
    return "names", refused if status == 401 else f"the locale list answered {status}"
