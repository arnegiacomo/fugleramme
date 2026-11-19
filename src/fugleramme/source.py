"""Where detections come from, as the rest of the frame sees them.

One protocol over the detector, so nothing above it knows whether it is the
BirdNET-Go container beside it, an install across the house, a BirdWeather
station or made-up birds. `api.ApiSource`, `birdweather.BirdWeatherSource` and
`demo.DemoSource` are the implementations.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from urllib.parse import urlsplit

# What a detector refusing the frame wants, in the one wording every surface
# uses: the admin's Detector row, its language menu, and `fugleramme-check`.
NEEDS_PASSWORD = "needs a password"

# Which kind of detector the frame reads (`Settings.detector_kind`): `api.ApiSource`
# reads a BirdNET-Go, `birdweather.BirdWeatherSource` a public BirdWeather station,
# `demo.DemoSource` makes birds up. Demo is chosen at install only, so the admin
# offers the first two (`admin.KINDS`).
BIRDNET_GO = "birdnet-go"
BIRDWEATHER = "birdweather"
DEMO = "demo"
DETECTOR_KINDS = (BIRDNET_GO, BIRDWEATHER, DEMO)

# Where a bare station ID is looked up.
BIRDWEATHER_SITE = "https://app.birdweather.com"
# The most BirdWeather stations one frame reads as one (`Settings.detector_station`).
MOST_STATIONS = 5
_STATION_PAGE = re.compile(r"/stations/(\d+)")


def station_id(url: str) -> str:
    """The BirdWeather station a page names, or "" for an address that names
    none. Any host: the fake serves its station on loopback."""
    found = _STATION_PAGE.fullmatch(urlsplit(url).path.rstrip("/"))
    return found.group(1) if found else ""


def with_scheme(typed: str) -> str:
    """An address as typed, read as plain HTTP when it names no scheme: a
    BirdNET-Go on a LAN serves no HTTPS. Not `urlsplit`, which reads the host
    of "pi.local:8090" as a scheme."""
    typed = typed.strip()
    return typed if not typed or "://" in typed else f"http://{typed}"


def station_url(typed: str) -> str:
    """A station as the frame saves it: a bare ID as its page on BirdWeather, a
    station's page with nothing after the ID. Anything else is left as typed."""
    typed = typed.strip()
    if typed.isascii() and typed.isdigit():
        return f"{BIRDWEATHER_SITE}/stations/{typed}"
    found = station_id(typed)
    if not found:
        return typed
    parts = urlsplit(typed)
    return f"{parts.scheme}://{parts.netloc}/stations/{found}"


def station_pages(typed: str) -> list[str]:
    """Every station a list separated by commas names, each as `station_url`
    saves it: in the order given, once each."""
    pages = (station_url(part) for part in typed.split(","))
    return list(dict.fromkeys(page for page in pages if page))


def station_fault(pages: list[str]) -> str:
    """Why `pages` cannot be read as one, or "": each must be a station, at most
    `MOST_STATIONS`, all on one site, since they are asked in one query."""
    if not all(station_id(page) for page in pages):
        return "not a station"
    if len(pages) > MOST_STATIONS:
        return "too many stations"
    if len({urlsplit(page).netloc for page in pages}) > 1:
        return "stations on two sites"
    return ""


class Unavailable(Exception):
    """The detector could not be reached, or answered with something else.

    Never confuse this with an empty result: empty means the detector answered
    and there were genuinely no birds. A source that returned [] on a timeout
    would collapse the collage to a bare perch and push that to the glass.
    """


class NoSuchStation(Unavailable):
    """The detector answered, and the station the frame names is not on it.
    Not "unreachable": that would send the reader to check a network that is fine."""


@dataclass(frozen=True)
class Detection:
    id: int
    detected_at: datetime
    scientific_name: str
    confidence: float
    clip_path: str | None


@dataclass(frozen=True)
class Species:
    scientific_name: str
    first_seen: datetime


class Source(Protocol):
    @property
    def base_url(self) -> str:
        """Which detector this is. Anything held from one station is not the
        answer for another, so callers key their caches on it."""

    def latest(self) -> Detection | None: ...

    def recent(self, limit: int = 20) -> list[Detection]: ...

    def species_since(self, hours: float = 24) -> list[tuple[str, int]]:
        """Species heard in the last `hours` with their detection count, most
        frequent first then by name. `hours` of 0 or less is not a window:
        every species ever heard."""
        ...

    def last_heard(self, hours: float = 24) -> list[str]:
        """Species heard in the last `hours`, most recently heard first then by name."""
        ...

    def life_list(self) -> list[Species]:
        """Every species ever recorded with the date it was first heard, earliest first."""
        ...

    def stats(self) -> dict: ...

    def close(self) -> None: ...
