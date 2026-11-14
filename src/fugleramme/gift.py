"""Gift mode (#355): ready a working frame to be given, with a splash on it in the box.

The last step after an install that works. `fugleramme-gift` borrows the frame: it stops the
frame service, asks where the frame is going, which birds go on the splash, a note and a
title, and draws the splash on the panel itself. Wrapping writes the recipient's place
into BirdNET-Go's config, sets their timezone, can delete this place's history, forget its
Wi-Fi networks and clear the admin password, and powers the Pi off with the splash on the
glass.

The frame service knows nothing of any of it. It is still enabled, so the next boot, at the
recipient's, starts an ordinary frame: their birds, or the Wi-Fi setup if it has no network.

A frame that reads BirdWeather, or a BirdNET-Go elsewhere, has no place or history of its own:
it is wrapped without those two (`detector/.env` marks a BirdNET-Go on this Pi).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import zoneinfo
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlencode
from urllib.request import urlopen

from . import languages, taxa
from .config import DEFAULT_CONFIG_PATH, REPO_ROOT
from .names import canonical, normalize
from .source import Unavailable

if TYPE_CHECKING:
    from .api import ApiSource

UNIT = "fugleramme-frame"  # run.sh's systemd unit
BIRDS = 20  # on a splash, unless the giver asks for another number
MOST_BIRDS = 40  # the frame's own page ships limited to as many
NEAR_KM = 50  # how far from the place a record still counts as there
PLACES = "https://photon.komoot.io/api/?limit=5&q="  # the admin's station finder asks the same
ZONES = "https://api.open-meteo.com/v1/forecast?latitude={:.2f}&longitude={:.2f}&timezone=auto"
RECORDS = "https://api.gbif.org/v1/occurrence/search?"
SNAPSHOT = REPO_ROOT / "hooks" / "species_by_country.json"  # the species page's, by country
LAT_LON = re.compile(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*")
_BINOMIAL = re.compile(r"[A-Z][a-z]+ [a-z-]+")
_HYBRID = re.compile(r" x |×")


@dataclass(frozen=True)
class Paths:
    """Where an appliance keeps what wrapping changes. Fields, not constants, for the tests."""

    data: Path = DEFAULT_CONFIG_PATH.parent  # BirdNET-Go's /data, settings.json beside it
    detector: Path = REPO_ROOT / "detector"

    @property
    def settings(self) -> Path:
        return self.data / "settings.json"

    @property
    def birdnet_config(self) -> Path:
        return self.detector / "config" / "config.yaml"

    @property
    def env(self) -> Path:
        return self.detector / ".env"


@dataclass(frozen=True)
class Splash:
    """What the splash shows."""

    title: str
    notes: tuple[str, ...]
    birds: tuple[str, ...]  # scientific names


# -- the place, its timezone and the birds' names -----------------------------


@dataclass(frozen=True)
class Place:
    label: str
    latitude: float
    longitude: float
    country: str = ""  # ISO 3166, "" for a typed position


def _json(url: str) -> Any:
    with urlopen(url, timeout=10) as answer:
        return json.load(answer)


def find_place(text: str, fetch: Callable[[str], Any] = _json) -> Place | None:
    """A typed `lat, lon`, else the first place Photon has by that name. Raises OSError
    when Photon cannot be asked."""
    typed = LAT_LON.fullmatch(text)
    if typed:
        lat, lon = float(typed[1]), float(typed[2])
        return Place(text.strip(), lat, lon) if abs(lat) <= 90 and abs(lon) <= 180 else None
    features = fetch(PLACES + quote(text.strip())).get("features") or []
    if not features:
        return None
    props, (lon, lat) = features[0]["properties"], features[0]["geometry"]["coordinates"]
    parts = [props.get("name"), props.get("city"), props.get("state")]
    label = ", ".join(dict.fromkeys(p for p in [*parts, props.get("country")] if p))
    return Place(label, float(lat), float(lon), str(props.get("countrycode") or "").upper())


def zone_at(place: Place, fetch: Callable[[str], Any] = _json) -> str:
    """The timezone at a place by Open-Meteo, as Photon gives none. "" when it does not
    answer, or names a zone this machine has no rules for."""
    try:
        zone = str(fetch(ZONES.format(place.latitude, place.longitude)).get("timezone") or "")
    except (OSError, ValueError, AttributeError):
        return ""
    return zone if zone in zoneinfo.available_timezones() else ""


def zone_here() -> str:
    """The Pi's own timezone, "" when timedatectl will not say."""
    asked = ["timedatectl", "show", "-p", "Timezone", "--value"]
    done = subprocess.run(asked, capture_output=True, text=True, check=False)
    return done.stdout.strip() if done.returncode == 0 else ""


def recorded(place: Place, today: date, fetch: Callable[[str], Any] = _json) -> list[str]:
    """The birds GBIF has records of within NEAR_KM of a place, in this month of the last
    ten years, most recorded first. Asked as `tools/species_map.py` asks of a country.
    Raises OSError when GBIF cannot be asked."""
    asked = {
        "taxonKey": 212,  # Aves
        "facet": "scientificName",
        "facetLimit": 300,
        "limit": 0,
        "occurrenceStatus": "PRESENT",
        "basisOfRecord": "HUMAN_OBSERVATION",
        "year": f"{today.year - 9},{today.year}",
        "month": today.month,
        "geoDistance": f"{place.latitude:.2f},{place.longitude:.2f},{NEAR_KM}km",
    }
    facets = fetch(RECORDS + urlencode(asked)).get("facets") or [{}]
    counts: dict[str, int] = {}
    for value in facets[0].get("counts") or []:
        binomial = _BINOMIAL.match(value["name"])  # the name carries its author
        if binomial and not _HYBRID.search(value["name"]):
            counts[binomial[0]] = counts.get(binomial[0], 0) + int(value["count"])
    return sorted(counts, key=lambda name: -counts[name])


def recorded_in(country: str) -> list[str]:
    """A country's birds from the species page's GBIF snapshot, most recorded first: all
    year and country wide, for when GBIF does not answer. [] for a country it lacks."""
    try:
        records = json.loads(SNAPSHOT.read_text())["countries"][country]["records"]
    except (OSError, ValueError, KeyError):
        return []
    return sorted(records, key=lambda name: -records[name])


def likely(place: Place, today: date, fetch: Callable[[str], Any] = _json) -> list[str]:
    """The birds most recorded where the frame is going: near the place this month, else
    its country's."""
    try:
        return recorded(place, today, fetch) or recorded_in(place.country)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return recorded_in(place.country)


def top_birds(names: Iterable[str], drawable: set[str], count: int = BIRDS) -> tuple[str, ...]:
    """The first `count` of `names` the style has a plate for."""
    chosen: dict[str, str] = {}
    for name in names:
        key = normalize(name)
        if key in drawable and key not in chosen:
            chosen[key] = canonical(name)
    return tuple(chosen.values())[:count]


@dataclass(frozen=True)
class Names:
    """Every name a bird with a plate can be picked by."""

    by_name: dict[str, str] = field(default_factory=dict)  # folded, against the scientific
    shown: tuple[str, ...] = ()  # what the search offers: each bird's common and scientific

    @classmethod
    def of(cls, cache_dir: Path, language: str, drawable: set[str]) -> Names:
        """The labels' English and scientific names, and the frame's own language's from
        the dictionary cached beside the settings."""
        english = {common: _scientific(key) for key, common in taxa.labels().items() if common}
        local, _version = languages.dictionary(language, cache_dir)
        common = {
            name: canonical(sci)
            for name, sci in {**{n: s for s, n in local.items()}, **english}.items()
            if normalize(sci) in drawable
        }
        named = {**common, **{sci: sci for sci in common.values()}}
        return cls({folded(name): sci for name, sci in named.items()}, tuple(sorted(named)))

    def match(self, text: str) -> str | None:
        return self.by_name.get(folded(text))


def _scientific(key: str) -> str:
    """ "cyanocitta-stelleri" -> "Cyanocitta stelleri"."""
    return key.replace("-", " ").capitalize()


def folded(name: str) -> str:
    """Case, apostrophes and hyphens are not worth a ✗: "stellers jay" is Steller's Jay."""
    return re.sub(r"[\s\-]+", " ", re.sub(r"['’]", "", name.lower())).strip()


# -- wrapping ----------------------------------------------------------------


def bundled(paths: Paths) -> bool:
    """Whether this Pi runs the BirdNET-Go that install.sh sets up, by run.sh's marker."""
    return paths.env.exists()


def root(*command: str) -> bool:
    """Run a command as root. Without a password where sudo allows it, else asking for one
    where there is a terminal to ask on."""
    if subprocess.run(["sudo", "-n", *command], capture_output=True, check=False).returncode == 0:
        return True
    if not sys.stdin.isatty():
        return False
    return subprocess.run(["sudo", *command], check=False).returncode == 0


def docker(*args: str) -> str:
    """A docker command's output, through sudo where the docker group has not taken yet,
    as run.sh does."""
    command = ["docker"]
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:
        command = ["sudo", "-n", "docker"]
    done = subprocess.run([*command, *args], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args[:2])}: {done.stderr.strip()}")
    return done.stdout.strip()


def compose(paths: Paths, *args: str) -> str:
    """`docker compose` on the bundled detector."""
    files = ["--env-file", str(paths.env), "-f", str(paths.detector / "docker-compose.yml")]
    return docker("compose", *files, *args)


_SECTION = re.compile(r"(?m)^birdnet:[ \t]*$")
_NEXT_SECTION = re.compile(r"(?m)^\S")
_COORD = r"(?m)^([ \t]+{}:[ \t]*)(\S+)"
_TZ = re.compile(r"(?m)^TZ=.*$")


def located(text: str, latitude: str, longitude: str) -> str:
    """BirdNET-Go's config with `birdnet.latitude`/`longitude` replaced. By line, not by
    YAML, to leave the rest of the file as BirdNET-Go wrote it."""
    section = _SECTION.search(text)
    if section is None:
        raise ValueError("no birdnet section in config.yaml")
    start = section.end()
    after = _NEXT_SECTION.search(text, start + 1)
    end = after.start() if after else len(text)
    block = text[start:end]
    for key, value in (("latitude", latitude), ("longitude", longitude)):
        match = re.search(_COORD.format(key), block)
        if match is None:
            raise ValueError(f"no birdnet.{key} in config.yaml")
        block = block[: match.start(2)] + value + block[match.end(2) :]
    return text[:start] + block + text[end:]


def zoned(env: str, zone: str) -> str:
    """`detector/.env` with the container's `TZ` replaced, the line run.sh writes."""
    line = f"TZ={zone}"
    return _TZ.sub(line, env) if _TZ.search(env) else f"{env}{line}\n"


def forget_history(paths: Paths) -> None:
    """Delete this place's detections and clips, with the detector stopped. BirdNET-Go
    starts an empty database. The glob takes the update's `birdnet.db.bak` and SQLite's
    -wal and -shm with the database."""
    for path in paths.data.glob("birdnet.db*"):
        path.unlink(missing_ok=True)
    shutil.rmtree(paths.data / "clips", ignore_errors=True)


def heard(source: ApiSource) -> int | None:
    """How many detections wrapping can delete, to say so before it does. None when
    BirdNET-Go will not say."""
    try:
        return int(source.stats()["total"])
    except Unavailable:
        return None


def _write(path: Path, text: str) -> None:
    """Whole or not at all: a half-written config.yaml would keep BirdNET-Go from starting."""
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)


@dataclass(frozen=True)
class Wrapping:
    """What the questions hand `wrap`, every answer already checked."""

    place: Place | None  # None: no BirdNET-Go of its own, so no place or history to change
    zone: str = ""  # "": the Pi's own already
    delete: bool = False
    clear_admin: bool = False


Step = Callable[[str], None]


def wrap(
    paths: Paths,
    wrapping: Wrapping,
    clear_admin: Callable[[], object],
    done: Step = lambda line: None,
) -> None:
    """Ready the frame for its new home, with the frame service already stopped and the
    splash on the glass. BirdNET-Go is stopped for it and brought back whatever fails in
    between: stopped by hand it would stay stopped at every boot from here."""
    place = wrapping.place
    if place is None:
        _settle(paths, wrapping, clear_admin, done)
        os.sync()
        return
    new = located(
        paths.birdnet_config.read_text(), f"{place.latitude:.4f}", f"{place.longitude:.4f}"
    )  # before anything changes: a config it cannot read stops the wrap here
    compose(paths, "stop")
    done("BirdNET-Go stopped")
    try:
        _write(paths.birdnet_config, new)
        done(f"Location set to {place.label}")
        _settle(paths, wrapping, clear_admin, done)
        if wrapping.delete:
            forget_history(paths)
            done("Detections and clips deleted")
    finally:
        compose(paths, "up", "-d")  # recreates the container when its TZ changed
    done("BirdNET-Go started")
    os.sync()  # the card has everything, so pulling the plug is as good as the power-off


def _settle(
    paths: Paths, wrapping: Wrapping, clear_admin: Callable[[], object], done: Step
) -> None:
    """What any frame takes to a new home: the Pi's clock and the admin password."""
    if wrapping.zone:
        if not root("timedatectl", "set-timezone", wrapping.zone):
            raise RuntimeError(f"could not set the timezone to {wrapping.zone}")
        if bundled(paths):
            _write(paths.env, zoned(paths.env.read_text(), wrapping.zone))
        done(f"Timezone set to {wrapping.zone}")
    if wrapping.clear_admin:
        clear_admin()
        done("Admin password removed")
