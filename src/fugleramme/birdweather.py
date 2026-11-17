"""Public BirdWeather stations as the frame's detection source.

BirdWeather serves every station through one GraphQL endpoint, so the frame names
a station by its page, `https://app.birdweather.com/stations/<id>`, and posts its
questions to `/graphql` on the same host. Several stations are asked as one, by
`stationIds`, so a species heard at more than one is one bird:

    station                -> one station's name and its first and last detection
    detections             -> the newest detections, newest first
    topSpecies             -> per-species counts over a rolling window
    dailyDetectionCounts   -> per-species counts per UTC day, the whole record
    allSpecies             -> a species' names in every language BirdWeather has
    stations               -> the stations in a box, for the admin's search

It is someone else's service, shared by every frame reading the same station and
asked every few seconds, and a POST gets no working ETag. So an answer is held
about a minute, and the whole record is fetched a few times a day with only its
last two days asked again each minute.
"""

from __future__ import annotations

import json
import logging
import math
import sys
import threading
import time
from collections import Counter
from collections.abc import Callable, Iterable
from datetime import UTC, date, datetime, time as clock, timedelta
from itertools import count
from typing import Any, NamedTuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .names import canonical
from .source import (
    BIRDWEATHER,
    BIRDWEATHER_SITE,
    MOST_STATIONS,
    Detection,
    NoSuchStation,
    Species,
    Unavailable,
    station_id,
    station_pages,
)
from .taxa import is_bird

log = logging.getLogger(__name__)

# `Configured` passes the frame's own; this is for a source built by hand.
_TIMEOUT = 30.0
_TTL = 60  # seconds an answer is held: the newest detections, a window's counts
_RECORD_TTL = 6 * 3600  # seconds the whole record is held; its last two days are not
_RETRY = 10  # seconds a failure is held, so a dead network is not asked on every call
_PAGE = 500  # `first` is capped here without a word, so anything longer pages
# topSpecies answers 10 rows unless asked for more; no station hears this many.
_TOP = 5000
_USER_AGENT = "fugleramme"
# How far the station search looks, widening until it has a page of stations. Each
# is a box of its own: one wide box can hit `_PAGE` and leave out the nearest.
RADII_KM = (25, 100, 400)
_EARTH_KM = 6371.0

_stations = count(1)

_STATION = """
query ($id: ID!) { station(id: $id) { name timezone earliestDetectionAt latestDetectionAt } }
"""

# One `detections` field a query: BirdWeather refuses a query asking more than three.
# Without a `period` it answers the last 24 hours only.
_DETECTIONS = """
query ($ids: [ID!], $first: Int, $after: String, $period: InputDuration, $species: ID,
       $classes: [String!]) {
  detections(stationIds: $ids, first: $first, after: $after, period: $period,
             speciesId: $species, classifications: $classes) {
    pageInfo { hasNextPage endCursor }
    nodes { id timestamp confidence species { id scientificName commonName classification } }
  }
}
"""

_TOP_SPECIES = """
query ($ids: [ID!], $period: InputDuration, $limit: Int) {
  topSpecies(stationIds: $ids, period: $period, limit: $limit) {
    count species { id scientificName commonName classification }
  }
}
"""

# Takes no `classifications`, unlike the two above, so the birds are picked out here.
_DAYS = """
query ($ids: [ID!], $period: InputDuration) {
  dailyDetectionCounts(stationIds: $ids, period: $period) {
    date counts { count species { id scientificName commonName classification } }
  }
}
"""


# Only stations heard from within `period`; without it, every one ever set up.
_STATIONS = """
query ($ne: InputLocation!, $sw: InputLocation!, $period: InputDuration, $first: Int) {
  stations(ne: $ne, sw: $sw, period: $period, first: $first) {
    nodes { id name coords { lat lon } }
  }
}
"""

_ALL_SPECIES = """
query ($ids: [ID!]!, $first: Int, $after: String) {
  allSpecies(ids: $ids, first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { id scientificName commonName translations { locale commonName } }
  }
}
"""

# BirdWeather's locales the frame spells otherwise, or None for one it does not
# offer: a Traditional `zh` only some species have, and `en-UK`, since English
# is each species' own commonName. The rest are lowercased as they come.
_LOCALES: dict[str, str | None] = {
    "no": "nb",
    "in": "id",
    "zh-SM": "zh",
    "zh": None,
    "en-UK": None,
}


def translations(node: dict) -> dict[str, str]:
    """One species' names by the frame's language code. BirdWeather has no `en`
    translation: English is the species' commonName."""
    codes = (
        (_LOCALES.get(row["locale"], row["locale"].lower()), row["commonName"])
        for row in node["translations"]
    )
    named = {code: name for code, name in codes if code and name}
    return named | ({"en": node["commonName"]} if node.get("commonName") else {})


def _post(endpoint: str, query: str, timeout: float, **variables: Any) -> dict:
    """The answer's `data`. A station BirdWeather does not have answers 404,
    an error in the query 200 with `errors`; both raise."""
    body = json.dumps({"query": query, "variables": variables}).encode()
    request = Request(
        endpoint,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            answer = response.read()
    except HTTPError as error:
        if error.code == 404:
            raise NoSuchStation("BirdWeather has no such station") from error
        raise Unavailable(f"BirdWeather answered {error.code}") from error
    except (URLError, OSError) as error:
        # Slow is not unreachable: that would send the reader to check a fine network.
        if isinstance(error.reason if isinstance(error, URLError) else error, TimeoutError):
            raise Unavailable(f"BirdWeather did not answer within {timeout:g}s") from error
        raise Unavailable(f"BirdWeather unreachable: {error}") from error
    try:
        data = json.loads(answer)
    except ValueError as error:
        raise Unavailable("BirdWeather answered no JSON") from error
    if not isinstance(data, dict) or data.get("errors") or not isinstance(data.get("data"), dict):
        errors = data.get("errors") if isinstance(data, dict) else data
        raise Unavailable(f"BirdWeather answered an error: {errors}")
    return data["data"]


class Station(NamedTuple):
    """A public station, as the admin's search lists it."""

    id: str
    name: str
    km: float  # from the place searched for


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance (haversine)."""
    a = (
        math.sin(math.radians(lat2 - lat1) / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * _EARTH_KM * math.asin(math.sqrt(a))


def _within(lat: float, lon: float, km: float) -> list[Station]:
    """The stations heard from this week within `km`, nearest first. BirdWeather
    filters by a box, and loosely since its coords are blurred, so the box is
    asked around the circle and the circle cut here. A box over the antimeridian
    stops at it."""
    rise = math.degrees(km / _EARTH_KM)
    run = min(180.0, rise / max(math.cos(math.radians(lat)), 1e-6))
    data = _post(
        f"{BIRDWEATHER_SITE}/graphql",
        _STATIONS,
        _TIMEOUT,
        ne={"lat": min(90.0, lat + rise), "lon": min(180.0, lon + run)},
        sw={"lat": max(-90.0, lat - rise), "lon": max(-180.0, lon - run)},
        period={"count": 7, "unit": "day"},
        first=_PAGE,
    )
    found = (
        Station(
            str(node["id"]),
            node["name"],
            _km(lat, lon, node["coords"]["lat"], node["coords"]["lon"]),
        )
        for node in data["stations"]["nodes"]
    )
    return sorted((station for station in found if station.km <= km), key=lambda s: s.km)


def nearest(lat: float, lon: float) -> list[Station]:
    """The stations heard from this week nearest a place, as many as the frame
    reads, within the widest of `RADII_KM`."""
    for km in RADII_KM:
        found = _within(lat, lon, km)
        if len(found) >= MOST_STATIONS:
            break
    return found[:MOST_STATIONS]


class _Day(NamedTuple):
    """One species' detections on one UTC day."""

    day: date
    species: str  # BirdWeather's id: a legacy and a current name are two
    name: str  # canonical, so the two are one bird here
    heard: int  # detections


def _ranked(counts: Iterable[tuple[str, int]]) -> list[tuple[str, int]]:
    return sorted(counts, key=lambda pair: (-pair[1], pair[0]))


def _noon(day: date) -> datetime:
    """A UTC day as a moment. The frame writes a date in its own zone, and noon
    reads as the same date from UTC-11 to UTC+12 where midnight would be the day
    before anywhere west of Greenwich."""
    return datetime.combine(day, clock(12), UTC)


class BirdWeatherSource:
    """A `source.Source` over public BirdWeather stations, read as one."""

    kind = BIRDWEATHER

    def __init__(self, base_url: str, timeout: float = _TIMEOUT):
        # The stations' pages separated by commas, as `Settings.detector_station` holds them.
        self.base_url = base_url.rstrip("/")
        self.station = f"{self.base_url}#{next(_stations)}"
        pages = station_pages(self.base_url)
        self._ids = tuple(station_id(page) for page in pages)
        parts = urlsplit(pages[0] if pages else "")
        self._endpoint = f"{parts.scheme}://{parts.netloc}/graphql"
        self._timeout = timeout
        self._lock = threading.RLock()
        self._cache: dict[tuple, tuple[float, Any]] = {}
        self._not_birds: set[str] = set()
        # BirdWeather id -> (scientific name, {language: common name}), asked once each.
        self._named: dict[str, tuple[str, dict[str, str]]] = {}

    def _is_bird(self, species: dict) -> bool:
        """BirdWeather's own classification, then `taxa.is_bird` as for any
        detector. What it drops is named once per species, not once per poll."""
        name = species["scientificName"]
        if species.get("classification") == "avian" and is_bird(name):
            return True
        if name not in self._not_birds:
            self._not_birds.add(name)
            common = species.get("commonName")
            log.info(
                "Not a bird, ignoring detections of %s", f"{common} ({name})" if common else name
            )
        return False

    # -- transport ---------------------------------------------------------

    def _query(self, query: str, **variables: Any) -> dict:
        return _post(self._endpoint, query, self._timeout, **variables)

    def _cached(self, key: tuple, ttl: float, fetch: Callable[[], Any]) -> Any:
        """Held for `ttl`, a failure for `_RETRY`. An answer in a shape the fetch
        cannot read is a failure too, never an empty one."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is not None and time.monotonic() < entry[0]:
                if isinstance(entry[1], Unavailable):
                    raise entry[1]
                return entry[1]
            now = time.monotonic()
            # A day's keys roll over, so its old ones are never asked again.
            self._cache = {k: v for k, v in self._cache.items() if v[0] > now}
            try:
                value = fetch()
            except (AttributeError, KeyError, TypeError, ValueError) as error:
                failure = Unavailable(f"unreadable answer from BirdWeather: {error!r}")
                self._cache[key] = (time.monotonic() + _RETRY, failure)
                raise failure from error
            except Unavailable as error:
                self._cache[key] = (time.monotonic() + _RETRY, error)
                raise
            self._cache[key] = (time.monotonic() + ttl, value)
            return value

    def _detections(self, ids: list[str], most: float, **filters: Any) -> list[dict]:
        """At least `most` detections where the stations have them, newest first."""
        nodes: list[dict] = []
        after = None
        while len(nodes) < most:
            data = self._query(_DETECTIONS, ids=ids, first=_PAGE, after=after, **filters)
            page = data["detections"]
            nodes += page["nodes"]
            if not page["pageInfo"]["hasNextPage"]:
                break
            after = page["pageInfo"]["endCursor"]
        return nodes

    def _about(self, id_: str) -> dict[str, Any] | None:
        def fetch() -> dict[str, Any] | None:
            try:
                return dict(self._query(_STATION, id=id_)["station"])
            except NoSuchStation:
                return None  # BirdWeather's answer, held as long as any other

        return self._cached(("station", id_), _TTL, fetch)

    def about(self) -> dict[str, dict[str, Any] | None]:
        """Each station by ID as BirdWeather describes it - `name`, `timezone`
        (IANA), `earliestDetectionAt` and `latestDetectionAt` - or None for one
        it does not have. One query each, since a query naming a station
        BirdWeather does not have fails whole."""
        if not self._ids or not all(self._ids):
            raise NoSuchStation(f"{self.base_url} names no BirdWeather station")
        return {id_: self._about(id_) for id_ in self._ids}

    def _heard(self) -> tuple[list[str], date | None]:
        """The stations BirdWeather has, and the first UTC day any of them heard
        anything (None while none has). One it does not have is left out, so the
        rest still make a page. With none left there is nothing to read, which
        is not the same as no birds."""
        about = {id_: row for id_, row in self.about().items() if row is not None}
        if not about:
            raise NoSuchStation(f"BirdWeather has no station {', '.join(self._ids)}")
        earliest = [
            datetime.fromisoformat(row["earliestDetectionAt"]).astimezone(UTC).date()
            for row in about.values()
            if row.get("earliestDetectionAt")
        ]
        return list(about), min(earliest, default=None)

    def _feed(self, pages: int) -> list[Detection]:
        ids, start = self._heard()
        if start is None:
            return []
        # The whole record, back from now so today is in it whatever the stations' zones.
        period = {"count": (datetime.now(UTC).date() - start).days + 1, "unit": "day"}

        def fetch() -> list[Detection]:
            return [
                Detection(
                    id=int(node["id"]),
                    detected_at=datetime.fromisoformat(node["timestamp"]),
                    scientific_name=canonical(node["species"]["scientificName"]),
                    confidence=float(node.get("confidence") or 0.0),
                    clip_path=None,
                )
                for node in self._detections(ids, pages * _PAGE, classes=["avian"], period=period)
                if self._is_bird(node["species"])
            ]

        return self._cached(("feed", pages, *ids), _TTL, fetch)

    def _top(self, minutes: int) -> list[tuple[str, int]]:
        ids = self._heard()[0]

        def fetch() -> list[tuple[str, int]]:
            period = {"count": minutes, "unit": "minute"}
            rows = self._query(_TOP_SPECIES, ids=ids, period=period, limit=_TOP)
            counts: Counter[str] = Counter()
            for row in rows["topSpecies"]:
                if self._is_bird(row["species"]):
                    counts[canonical(row["species"]["scientificName"])] += int(row["count"])
            return _ranked(counts.items())

        return self._cached(("top", minutes, *ids), _TTL, fetch)

    def _days(self, ids: list[str], start: date, end: date) -> list[_Day]:
        period = {"from": start.isoformat(), "to": end.isoformat()}
        data = self._query(_DAYS, ids=ids, period=period)
        return [
            _Day(
                date.fromisoformat(day["date"]),
                # interned: a long record repeats the same few ids and names on every day
                sys.intern(str(row["species"]["id"])),
                sys.intern(canonical(row["species"]["scientificName"])),
                int(row["count"]),
            )
            for day in data["dailyDetectionCounts"]
            for row in day["counts"]
            if self._is_bird(row["species"])
        ]

    def _record(self) -> list[_Day]:
        """Every day the stations heard birds. A finished day does not change, so
        the whole record is asked for a few times a day and its last two days
        each minute: an upload can land on yesterday after UTC midnight.

        The days are UTC's whatever timezone is asked for, so the first day is
        the earliest detection's UTC date, not its local one."""
        ids, start = self._heard()
        if start is None:
            return []  # stations that have heard nothing yet
        today = datetime.now(UTC).date()
        recent = max(start, today - timedelta(days=1))
        whole = self._cached(
            ("record", today, *ids), _RECORD_TTL, lambda: self._days(ids, start, today)
        )
        fresh = self._cached(("days", today, *ids), _TTL, lambda: self._days(ids, recent, today))
        return [row for row in whole if row.day < recent] + fresh

    def _first_heard(self, ids: list[str], species: str, day: date) -> datetime:
        """The exact first detection of a species BirdWeather first heard on `day`,
        which never changes once found. Detections only come newest first and
        `last` is ignored, so this reads that whole day."""

        def fetch() -> datetime:
            period = {"from": day.isoformat(), "to": day.isoformat()}
            nodes = self._detections(ids, float("inf"), species=species, period=period)
            stamps = [datetime.fromisoformat(node["timestamp"]) for node in nodes]
            return min(stamps, default=_noon(day))

        return self._cached(("first", species, day, *ids), float("inf"), fetch)

    def _species_names(self, ids: list[str]) -> dict[str, tuple[str, dict[str, str]]]:
        """(scientific name, names) by BirdWeather id. An id it leaves out is
        named in no language, so it is not asked for again."""
        named: dict[str, tuple[str, dict[str, str]]] = dict.fromkeys(ids, ("", {}))
        after = None
        while True:
            page = self._query(_ALL_SPECIES, ids=ids, first=_PAGE, after=after)["allSpecies"]
            named |= {str(n["id"]): (n["scientificName"], translations(n)) for n in page["nodes"]}
            if not page["pageInfo"]["hasNextPage"]:
                return named
            after = page["pageInfo"]["endCursor"]

    def common_names(self) -> dict[str, dict[str, str]]:
        """Every name BirdWeather has for the birds the stations have heard, as
        {language: {scientific name: common name}}. A species is asked for once,
        when the record first holds it, so a newly heard bird costs one small
        query and a quiet minute none."""
        ids = sorted({row.species for row in self._record()})
        with self._lock:
            missing = [species for species in ids if species not in self._named]
            if missing:
                fetched = self._cached(
                    ("names", *missing), _TTL, lambda: self._species_names(missing)
                )
                self._named = {**self._named, **fetched}
            rows = [self._named[species] for species in ids]
        # The current name's own row first, so a legacy one only fills in what it lacks.
        table: dict[str, dict[str, str]] = {}
        for name, names in sorted(rows, key=lambda row: canonical(row[0]) != row[0]):
            for code, common in names.items():
                table.setdefault(code, {}).setdefault(canonical(name), common)
        return table

    # -- source ------------------------------------------------------------

    def latest(self) -> Detection | None:
        rows = self.recent(1)
        return rows[0] if rows else None

    def recent(self, limit: int = 20) -> list[Detection]:
        return self._feed(max(1, -(-limit // _PAGE)))[:limit]

    def species_since(self, hours: float = 24) -> list[tuple[str, int]]:
        if hours > 0:
            return self._top(max(1, round(hours * 60)))
        counts: Counter[str] = Counter()
        for row in self._record():
            counts[row.name] += row.heard
        return _ranked(counts.items())

    def last_heard(self, hours: float = 24) -> list[str]:
        """In the order the newest detections heard them, then by the last UTC
        day each was heard for any the newest page does not reach."""
        heard = [name for name, _n in self.species_since(hours)]
        order: dict[str, int] = {}
        for detection in self.recent(_PAGE):
            order.setdefault(detection.scientific_name, len(order))
        last: dict[str, int] = {}
        for row in self._record():
            last[row.name] = max(last.get(row.name, 0), row.day.toordinal())
        return sorted(
            heard, key=lambda name: (order.get(name, len(order)), -last.get(name, 0), name)
        )

    def life_list(self) -> list[Species]:
        """First heard to the UTC day, which is all the record holds. A species
        whose day is today or yesterday may still be new, which is counted in
        hours, so its exact first detection is looked up."""
        record = self._record()
        ids = self._heard()[0]
        first: dict[str, date] = {}
        for row in record:
            first[row.name] = min(first.get(row.name, row.day), row.day)
        recent = datetime.now(UTC).date() - timedelta(days=1)

        def seen(name: str, day: date) -> datetime:
            if day < recent:
                return _noon(day)
            named = {row.species for row in record if row.name == name and row.day == day}
            return min(self._first_heard(ids, species, day) for species in named)

        species = [Species(name, seen(name, day)) for name, day in first.items()]
        return sorted(species, key=lambda s: (s.first_seen, s.scientific_name))

    def stats(self) -> dict:
        ever = self.species_since(0)
        return {
            "total": sum(n for _name, n in ever),
            "species": len(ever),
            "last_24h": sum(n for _name, n in self.species_since(24)),
            "top": [{"scientific_name": name, "n": n, "best": None} for name, n in ever[:10]],
        }

    def close(self) -> None:
        """No connection to release: every call is its own request."""
