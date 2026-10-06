"""Species names in the reader's language, from BirdNET-Go's API.

Nothing is vendored: BirdNET-Go is the only name source, so they come over HTTP
from the same instance the frame reads its detections from - through that
source's session, since PrivateMode gates these two endpoints as well:

    GET /api/v2/settings/locales           -> {code: English name}, all label locales
    GET /api/v2/species/dictionary/<code>   -> {scientific name: common name}, gzipped
    GET /api/v2/species/all                 -> every species, named in birdnet.locale
    GET /api/v2/settings/birdnet            -> {"locale": ...}, which language that is

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

STATION, BirdNET-Go's own species language (birdnet.locale), is the one outside
the dictionaries. `/species/all` names it with no password; only which language
it is, for the label and the dates, needs one.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .source import NEEDS_PASSWORD, Unavailable

log = logging.getLogger(__name__)

# Pseudo-language: the scientific name, the only one needing no BirdNET-Go.
SCIENTIFIC = "sci"
NONE = ""  # secondary language unset
# Pseudo-language: BirdNET-Go's own species language (birdnet.locale).
STATION = "station"
# As in "Estonian (BirdNET-Go locale)", or alone while the language is unknown.
STATION_NAME = "BirdNET-Go locale"
_STATION_PATH = "/species/all"

# Locale codes the dictionary spells differently; the rest just drop the region.
_ALIASES = {"no": "nb"}

# Offered first, ahead of the alphabetical rest.
_PREFERRED = (SCIENTIFIC, STATION, "en", "nb")

_CATALOG_TTL = 24 * 3600
_DICT_TTL = 3600
# No ETag to revalidate by, and a changed birdnet.locale should show within minutes.
_STATION_TTL = 300
_RETRY_TTL = 120  # BirdNET-Go down or still starting: retry soon, not tomorrow

_UNCHANGED = object()  # 304: the cached copy is still current

_lock = threading.Lock()

# Both caches carry the station they came from: a dictionary and its ETag are
# one detector's answer, so pointing the frame at another expires them rather
# than serving the old station's names under the new one's.
# (deadline, station, languages, offers STATION, why there are none)
_Catalog = tuple[float, str, dict[str, str], bool, str]
_Dictionary = tuple[float, str, str, dict[str, str]]
_catalog: _Catalog | None = None
_dicts: dict[str, _Dictionary] = {}
# (station, birdnet.locale) of the STATION names; "" when the locale is unknown.
_station_locale: tuple[str, str] | None = None

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
            cached = _read(path)
            _catalog = (
                0.0,
                station,
                cached.get("languages") or {},
                cached.get("station") is True,
                "",
            )
        deadline, _held, found, offers_station, _why = _catalog
        if time.monotonic() >= deadline:
            # An empty probe is a failure, not an answer: caching it for a day
            # and writing it over a good list on disk would turn one bad moment
            # into a frame with no languages until someone restarted it. So is
            # STATION's: an answer adds it, nothing removes it.
            probed, why = _probe()
            answered = _station_answers()
            if probed:
                found = probed
            offers_station = offers_station or answered
            if probed or answered:
                _write(path, {"languages": found, "station": offers_station})
            ttl = _CATALOG_TTL if probed else _RETRY_TTL
            _catalog = (
                time.monotonic() + ttl,
                station,
                found,
                offers_station,
                why if not found else "",
            )
        offered = {SCIENTIFIC: "Scientific", **found}
        if offers_station:
            offered[STATION] = _station_label(_held_locale(cache_dir, station))
        return offered


def _station_answers() -> bool:
    # No cheaper than a GET: BirdNET-Go answers HEAD with its full GET handler.
    answer = _request(_STATION_PATH, "HEAD")
    return answer is not None and answer[0] == 200


def _held_locale(cache_dir: Path, station: str) -> str:
    """birdnet.locale as the STATION names last found it. Called under _lock."""
    if _station_locale is not None and _station_locale[0] == station:
        return _station_locale[1]
    return str(_read(cache_path(cache_dir, STATION)).get("locale") or "")


def _station_label(locale: str) -> str:
    name = english_name(locale)
    return f"{name} ({STATION_NAME})" if name else STATION_NAME


def _birdnet_locale() -> str:
    """birdnet.locale, or "" when /settings/birdnet refuses a frame with no password."""
    answer = _request("/settings/birdnet")
    if answer is None or answer[0] != 200:
        return ""
    try:
        locale = json.loads(answer[2]).get("locale")
    except (ValueError, AttributeError):
        return ""
    return locale.strip().lower() if isinstance(locale, str) else ""


def _station_names() -> tuple[dict[str, str], str, str] | None:
    """(names, locale, version) of BirdNET-Go's species language, or None when
    the station does not answer.

    Names are keyed under both BirdNET-Go's scientific name and its `canonical`
    one. A common name equal to the scientific one is left out, so the label
    falls back as usual. The version hashes the locale too, so changing it
    re-renders the page.
    """
    answer = _request(_STATION_PATH)
    if answer is None or answer[0] != 200:
        return None
    try:
        payload = json.loads(answer[2])
    except ValueError:
        return None
    rows = payload.get("species") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return None
    from .names import canonical  # late: names sits above this module

    names: dict[str, str] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        sci, common = row.get("scientificName"), row.get("commonName")
        if not (isinstance(sci, str) and isinstance(common, str)):
            continue
        sci, common = sci.strip(), common.strip()
        if not sci or not common or common.lower() == sci.lower():
            continue
        names.setdefault(sci, common)
        names.setdefault(canonical(sci), common)
    locale = _birdnet_locale()
    version = hashlib.sha256(answer[2] + locale.encode()).hexdigest()[:12]
    return names, locale, version


def catalog_failure() -> str:
    """Why the last `catalog` found nothing to offer, or "" when it did. Held
    with the catalog rather than returned beside it: a list served off the disk
    cache is a working menu whatever the probe behind it just did."""
    with _lock:
        return _catalog[4] if _catalog else ""


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
    global _station_locale
    with _lock:
        station = _station()
        path = cache_path(cache_dir, code)
        if code not in _dicts or _dicts[code][1] != station:
            cached = _read(path)
            _dicts[code] = (0.0, station, cached.get("etag", ""), cached.get("names") or {})
            if code == STATION:
                _station_locale = (station, str(cached.get("locale") or ""))
        deadline, _held, etag, names = _dicts[code]
        if time.monotonic() >= deadline:
            if code == STATION:
                answer = _station_names()
                ttl = _STATION_TTL if answer is not None else _RETRY_TTL
                if answer is not None:
                    names, locale, fresh = answer
                    _station_locale = (station, locale)
                    # A few hundred KB that rarely changes: spare the Pi's SD card.
                    if fresh != etag:
                        _write(path, {"etag": fresh, "names": names, "locale": locale})
                    etag = fresh
            else:
                payload, fresh = _fetch(f"/species/dictionary/{code}", etag)
                if isinstance(payload, dict):
                    etag, names = fresh, payload
                    _write(path, {"etag": etag, "names": names})
                ttl = _DICT_TTL if payload is not None else _RETRY_TTL
            _dicts[code] = (time.monotonic() + ttl, station, etag, names)
        return names, etag


def station_locale() -> str:
    """birdnet.locale behind the STATION names `dictionary` last loaded, or ""."""
    with _lock:
        held = _station_locale
        return held[1] if held is not None and held[0] == _station() else ""


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


def english_name(locale: str) -> str:
    """English name: "Arabic" for "ar", "Portuguese" for "pt-br", "" if babel lacks it."""
    if not locale or Locale is None:
        return ""
    try:
        return str(Locale.parse(locale.split("-")[0]).english_name or "")
    except (UnknownLocaleError, ValueError):
        return ""


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
    written = _spelled(code, when.astimezone(), clock) or numeric(when, clock)
    return written.translate(_PLAIN_SPACES)


def numeric(when: datetime, clock: bool) -> str:
    """A date in figures alone, which any face can set."""
    return when.astimezone().strftime("%-d.%m %H:%M" if clock else "%-d.%m.%Y")


def _capitalized(name: str) -> str:
    """Norwegian names come lowercase, English titled; a standalone label reads
    better capitalized, and a mixed dictionary evenly."""
    return name[:1].upper() + name[1:]


# (language code, text) -> whether the page can draw it; a name it cannot falls
# back to the scientific one, a date to `numeric`.
Drawable = Callable[[str, str], bool]


def _anything(_code: str, _text: str) -> bool:
    return True


class Namer:
    """Renders a scientific name into the configured language(s). Built by `namer`."""

    def __init__(
        self,
        primary: str,
        secondary: str,
        names: dict[str, dict[str, str]],
        version: tuple,
        station_locale: str = "",
    ):
        self.primary = primary
        self.secondary = secondary
        self._names = names
        # STATION's dates follow birdnet.locale ("pt-br" as babel's "pt"), and are
        # numeric while it is unknown.
        self._dates = station_locale.split("-")[0] if primary == STATION else primary
        # Cache key: the names change with the dictionaries, not just the setting.
        self.key = (primary, secondary, version)

    def _one(self, code: str, scientific: str, drawable: Drawable) -> str:
        if code in (SCIENTIFIC, NONE):
            return scientific
        common = self._names.get(code, {}).get(scientific)
        name = _capitalized(common) if common else scientific
        return name if drawable(code, name) else scientific

    def parts(self, scientific: str, drawable: Drawable = _anything) -> tuple[str, ...]:
        """The primary name, plus the second language's when it differs."""
        primary = self._one(self.primary, scientific, drawable)
        if self.secondary == NONE:
            return (primary,)
        secondary = self._one(self.secondary, scientific, drawable)
        return (primary,) if secondary == primary else (primary, secondary)

    def label(self, scientific: str, drawable: Drawable = _anything) -> str:
        """Collage label: the second language on its own line, in parentheses."""
        parts = self.parts(scientific, drawable)
        return parts[0] if len(parts) == 1 else f"{parts[0]}\n({parts[1]})"

    def inline(self, scientific: str) -> str:
        """One line, for the admin listings."""
        return self.label(scientific).replace("\n", " ")

    def date(self, when: datetime, drawable: Drawable = _anything) -> str:
        """A day, with its year: the newest arrival's can be months back."""
        return self._dated(when, False, drawable)

    def moment(self, when: datetime, drawable: Drawable = _anything) -> str:
        """A day and a clock time, for the bird holding the page now."""
        return self._dated(when, True, drawable)

    def _dated(self, when: datetime, clock: bool, drawable: Drawable) -> str:
        written = _written(self._dates, when, clock)
        return written if drawable(self._dates, written) else numeric(when, clock)


def namer(primary: str, secondary: str, cache_dir: Path) -> Namer:
    """A Namer for the admin's language settings, loading only the dictionaries
    it needs. Cheap to call per render or per request: the loads are cached."""
    names, versions = {}, []
    for code in (primary, secondary):
        if code not in (SCIENTIFIC, NONE) and code not in names:
            names[code], version = dictionary(code, cache_dir)
            versions.append((code, version))
    locale = station_locale() if primary == STATION else ""
    return Namer(primary, secondary, names, tuple(versions), locale)
