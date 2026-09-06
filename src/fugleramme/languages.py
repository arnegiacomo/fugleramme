"""Species names in the reader's language, from BirdNET-Go's API.

Nothing is vendored: BirdNET-Go is the only name source, so they come over HTTP
from the same instance the frame reads its detections from - through that
source's session, since PrivateMode gates these two endpoints as well:

    GET /api/v2/settings/locales           -> {code: English name}, all label locales
    GET /api/v2/species/dictionary/<code>   -> {scientific name: common name}, gzipped

Only some of those locales have a dictionary and the two endpoints disagree on
codes (the list's "no" answers as "nb"), so the offered languages are the probed
intersection - HEAD is enough to ask. Dictionaries cache under `<cache_dir>/names/`
and revalidate by ETag, which is BirdNET-Go's own speciesDictVersion. With it
unreachable and nothing cached, SCIENTIFIC is the only language left.

The two are not gated alike. `/settings/*` sits behind BirdNET-Go's
authentication whenever any provider is configured, where the detections are
only behind PrivateMode - so the locale list is the first thing to refuse a
frame that has no credentials, while the birds keep arriving. `catalog_failure`
exists so the admin can say that instead of silently offering one language.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from .source import NEEDS_PASSWORD, Unavailable

log = logging.getLogger(__name__)

# Pseudo-language: the scientific name, the only one needing no BirdNET-Go.
SCIENTIFIC = "sci"
NONE = ""  # secondary language unset

# Locale codes the dictionary spells differently; the rest just drop the region.
_ALIASES = {"no": "nb"}

# Offered first, ahead of the alphabetical rest.
_PREFERRED = (SCIENTIFIC, "en", "nb")

_CATALOG_TTL = 24 * 3600
_DICT_TTL = 3600
_RETRY_TTL = 120  # BirdNET-Go down or still starting: retry soon, not tomorrow

_UNCHANGED = object()  # 304: the cached copy is still current

_lock = threading.Lock()

# Both caches carry the station they came from: a dictionary and its ETag are
# one detector's answer, so pointing the frame at another expires them rather
# than serving the old station's names under the new one's.
_Catalog = tuple[float, str, dict[str, str], str]
_Dictionary = tuple[float, str, str, dict[str, str]]
_catalog: _Catalog | None = None
_dicts: dict[str, _Dictionary] = {}

_source: Any = None


def use(source: Any) -> None:
    """Read names through this detector. Set once at startup; unset, there is
    nothing to ask and SCIENTIFIC is the only language."""
    global _source
    _source = source


def _station() -> str:
    """Which source the caches belong to - the detector, and as whom. Read per
    lookup, not captured: the settings can point `use`'s source elsewhere while
    we run, and a password entered for the locale list must not sit out the
    retry TTL before it counts."""
    return str(getattr(_source, "station", ""))


def _request(path: str, method: str = "GET", headers: dict[str, str] | None = None):
    """The detector's answer, or None when it gives none. A missing name is a
    scientific one, not a blank page, so nothing here raises."""
    if _source is None:
        return None
    try:
        return _source.request(path, method, headers)
    except Unavailable:
        return None


def _fetch(path: str, etag: str = "") -> tuple[object, str]:
    """(payload, etag), where payload is _UNCHANGED on a 304 and None when
    BirdNET-Go is unreachable or answers anything but JSON."""
    answer = _request(path, headers={"If-None-Match": etag} if etag else None)
    if answer is None:
        return None, ""
    status, headers, body = answer
    if status == 304:
        return _UNCHANGED, etag
    try:
        return (json.loads(body), headers.get("etag", "")) if status == 200 else (None, "")
    except ValueError:
        return None, ""


def _has_dictionary(code: str) -> bool:
    answer = _request(f"/species/dictionary/{code}", "HEAD")
    return answer is not None and answer[0] == 200


def _display(locales: dict[str, str], code: str, fallback: str) -> str:
    """The language's English name, unqualified: the list's region-less entry, or
    a regional one stripped ("English (UK)" -> "English")."""
    return locales.get(code) or fallback.split(" (")[0]


def _probe() -> tuple[dict[str, str], str]:
    """The locales that have a dictionary, as {dictionary code: display name},
    and why there are none when there are none. The reason is a fragment, not a
    sentence - the admin and `fugleramme-check` each frame it their own way."""
    answer = _request("/settings/locales")
    if answer is None:
        return {}, "detector unreachable"
    status, _headers, body = answer
    if status == 401:
        # Gated whenever any auth provider is configured, PrivateMode or not -
        # hence a frame that shows birds and has no names for them.
        return {}, NEEDS_PASSWORD
    if status != 200:
        return {}, f"detector answered {status}"
    try:
        locales = json.loads(body)
    except ValueError:
        locales = None
    if not isinstance(locales, dict):
        return {}, "unreadable locale list"
    found: dict[str, str] = {}
    for code, display in sorted(locales.items()):  # region-less codes sort first
        resolved = _ALIASES.get(code, code.split("-")[0])
        if resolved in found or not _has_dictionary(resolved):
            continue
        found[resolved] = _display(locales, resolved, display)
    return found, "" if found else "detector serves none"


def _read(path: Path) -> dict:
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def _write(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload))
    except OSError:
        log.warning("Could not cache %s", path.name)


def cache_path(cache_dir: Path, name: str) -> Path:
    """Where a probed language list ("languages") or a locale's dictionary lands."""
    return Path(cache_dir) / "names" / f"{name}.json"


def catalog(cache_dir: Path) -> dict[str, str]:
    """Selectable languages as {code: display name}, SCIENTIFIC always first.

    Cached in the process and on disk, so the admin page normally costs nothing
    and a restart with BirdNET-Go down still offers what it last found.
    """
    global _catalog
    with _lock:
        station = _station()
        path = cache_path(cache_dir, "languages")
        if _catalog is None or _catalog[1] != station:
            _catalog = (0.0, station, _read(path).get("languages") or {}, "")
        deadline, _held, found, _why = _catalog
        if time.monotonic() >= deadline:
            # An empty probe is a failure, not an answer: caching it for a day
            # and writing it over a good list on disk would turn one bad moment
            # into a frame with no languages until someone restarted it.
            probed, why = _probe()
            if probed:
                found = probed
                _write(path, {"languages": found})
            ttl = _CATALOG_TTL if probed else _RETRY_TTL
            _catalog = (time.monotonic() + ttl, station, found, why if not found else "")
        return {SCIENTIFIC: "Scientific", **found}


def catalog_failure() -> str:
    """Why the last `catalog` found nothing to offer, or "" when it did. Held
    with the catalog rather than returned beside it: a list served off the disk
    cache is a working menu whatever the probe behind it just did."""
    with _lock:
        return _catalog[3] if _catalog else ""


def ordered(languages: dict[str, str]) -> list[tuple[str, str]]:
    """The catalog as select options: _PREFERRED first, then by display name."""
    rest = sorted(
        ((c, n) for c, n in languages.items() if c not in _PREFERRED), key=lambda cn: cn[1]
    )
    return [(c, languages[c]) for c in _PREFERRED if c in languages] + rest


def dictionary(code: str, cache_dir: Path) -> tuple[dict[str, str], str]:
    """A locale's {scientific name: common name} and its version, or ({}, "")
    when BirdNET-Go has never been reachable for it."""
    if code in (SCIENTIFIC, NONE):
        return {}, ""
    with _lock:
        station = _station()
        path = cache_path(cache_dir, code)
        if code not in _dicts or _dicts[code][1] != station:
            cached = _read(path)
            _dicts[code] = (0.0, station, cached.get("etag", ""), cached.get("names") or {})
        deadline, _held, etag, names = _dicts[code]
        if time.monotonic() >= deadline:
            payload, fresh = _fetch(f"/species/dictionary/{code}", etag)
            if isinstance(payload, dict):
                etag, names = fresh, payload
                _write(path, {"etag": etag, "names": names})
            ttl = _DICT_TTL if payload is not None else _RETRY_TTL
            _dicts[code] = (time.monotonic() + ttl, station, etag, names)
        return names, etag


try:
    from babel import Locale
    from babel.core import UnknownLocaleError
    from babel.dates import format_date, format_skeleton, format_time
except ImportError:  # a half-finished self-update: numeric dates still read fine
    Locale = format_date = format_skeleton = format_time = None  # type: ignore[assignment,misc]
    UnknownLocaleError = ValueError  # type: ignore[assignment,misc]


# English puts a narrow no-break space before AM/PM. Five of the seven label
# faces have no glyph for one and draw a box instead.
_PLAIN_SPACES = str.maketrans({"\u202f": " ", "\u00a0": " "})


def _spelled(code: str, local: datetime, clock: bool) -> str | None:
    """The date in the language's own words, or None when babel cannot."""
    if code in (SCIENTIFIC, NONE) or format_date is None:
        return None
    try:
        if not clock:
            # "long" keeps the month spelled out; asking for day-month-year
            # shortens it to "16. aug. 2026".
            return format_date(local, "long", locale=code)
        day = str(format_skeleton("MMMMd", local, locale=code))
        # Some languages put a comma between the day and the time, some a space.
        join = str(Locale.parse(code).datetime_formats["short"])
        return join.format(format_time(local, "short", locale=code), day)
    except (UnknownLocaleError, ValueError, KeyError):
        log.warning("No date format for %s; using numeric", code)
        return None


def _written(code: str, when: datetime, clock: bool) -> str:
    """A date the way the language writes it - more than the month's name, since
    Hungarian and Latvian put the year first and Spanish joins with "de"."""
    local = when.astimezone()
    written = _spelled(code, local, clock) or local.strftime(
        "%-d.%m %H:%M" if clock else "%-d.%m.%Y"
    )
    return written.translate(_PLAIN_SPACES)


def _capitalized(name: str) -> str:
    """Norwegian names come lowercase, English titled; a standalone label reads
    better capitalized, and a mixed dictionary evenly."""
    return name[:1].upper() + name[1:]


class Namer:
    """Renders a scientific name into the configured language(s). Built by `namer`."""

    def __init__(
        self, primary: str, secondary: str, names: dict[str, dict[str, str]], version: tuple
    ):
        self.primary = primary
        self.secondary = secondary
        self._names = names
        # Cache key: the names change with the dictionaries, not just the setting.
        self.key = (primary, secondary, version)

    def _one(self, code: str, scientific: str) -> str:
        if code in (SCIENTIFIC, NONE):
            return scientific
        common = self._names.get(code, {}).get(scientific)
        return _capitalized(common) if common else scientific

    def parts(self, scientific: str) -> tuple[str, ...]:
        """The primary name, plus the second language's when it differs."""
        primary = self._one(self.primary, scientific)
        if self.secondary == NONE:
            return (primary,)
        secondary = self._one(self.secondary, scientific)
        return (primary,) if secondary == primary else (primary, secondary)

    def label(self, scientific: str) -> str:
        """Collage label: the second language on its own line, in parentheses."""
        parts = self.parts(scientific)
        return parts[0] if len(parts) == 1 else f"{parts[0]}\n({parts[1]})"

    def inline(self, scientific: str) -> str:
        """One line, for the admin listings."""
        return self.label(scientific).replace("\n", " ")

    def date(self, when: datetime) -> str:
        """A day, with its year: the newest arrival's can be months back."""
        return _written(self.primary, when, clock=False)

    def moment(self, when: datetime) -> str:
        """A day and a clock time, for the bird holding the page now."""
        return _written(self.primary, when, clock=True)


def namer(primary: str, secondary: str, cache_dir: Path) -> Namer:
    """A Namer for the admin's language settings, loading only the dictionaries
    it needs. Cheap to call per render or per request: the loads are cached."""
    names, versions = {}, []
    for code in (primary, secondary):
        if code not in (SCIENTIFIC, NONE) and code not in names:
            names[code], version = dictionary(code, cache_dir)
            versions.append((code, version))
    return Namer(primary, secondary, names, tuple(versions))
