"""Species names in the reader's language, from BirdNET-Go's API.

Nothing is vendored: BirdNET-Go is the only name source, and its SQLite has none
of them (`labels` carries the scientific name alone), so they come over HTTP from
the same container the frame reads the DB from:

    GET /api/v2/settings/locales           -> {code: English name}, all label locales
    GET /api/v2/species/dictionary/<code>   -> {scientific name: common name}, gzipped

Only some of those locales have a dictionary and the two endpoints disagree on
codes (the list's "no" answers as "nb"), so the offered languages are the probed
intersection - HEAD is enough to ask. Dictionaries cache under `<cache_dir>/names/`
and revalidate by ETag, which is BirdNET-Go's own speciesDictVersion. With it
unreachable and nothing cached, SCIENTIFIC is the only language left.
"""

from __future__ import annotations

import gzip
import json
import logging
import threading
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .config import BIRDNET_PORT

log = logging.getLogger(__name__)

# Pseudo-language: the scientific name, the only one needing no BirdNET-Go.
SCIENTIFIC = "sci"
NONE = ""  # secondary language unset

_API = f"http://127.0.0.1:{BIRDNET_PORT}/api/v2"
_TIMEOUT = 3

# Locale codes the dictionary spells differently; the rest just drop the region.
_ALIASES = {"no": "nb"}

# Offered first, ahead of the alphabetical rest.
_PREFERRED = (SCIENTIFIC, "en", "nb")

_CATALOG_TTL = 24 * 3600
_DICT_TTL = 3600
_RETRY_TTL = 120  # BirdNET-Go down or still starting: retry soon, not tomorrow

_UNCHANGED = object()  # 304: the cached copy is still current

_lock = threading.Lock()
_catalog: tuple[float, dict[str, str]] | None = None  # (deadline, {code: display})
_dicts: dict[str, tuple[float, str, dict[str, str]]] = {}  # code -> (deadline, etag, names)


def _fetch(url: str, etag: str = "") -> tuple[object, str]:
    """(payload, etag), where payload is _UNCHANGED on a 304 and None when
    BirdNET-Go is unreachable or answers anything but JSON."""
    headers = {"Accept-Encoding": "gzip"}
    if etag:
        headers["If-None-Match"] = etag
    try:
        with urlopen(Request(url, headers=headers), timeout=_TIMEOUT) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return json.loads(raw), response.headers.get("ETag", "")
    except HTTPError as exc:
        return (_UNCHANGED if exc.code == 304 else None), etag
    except (URLError, OSError, ValueError, gzip.BadGzipFile):
        return None, ""


def _has_dictionary(code: str) -> bool:
    request = Request(f"{_API}/species/dictionary/{code}", method="HEAD")
    try:
        with urlopen(request, timeout=_TIMEOUT) as response:
            return response.status == 200
    except (HTTPError, URLError, OSError):
        return False


def _display(locales: dict[str, str], code: str, fallback: str) -> str:
    """The language's English name, unqualified: the list's region-less entry, or
    a regional one stripped ("English (UK)" -> "English")."""
    return locales.get(code) or fallback.split(" (")[0]


def _probe() -> dict[str, str] | None:
    """The locales that have a dictionary, as {dictionary code: display name}."""
    locales, _etag = _fetch(f"{_API}/settings/locales")
    if not isinstance(locales, dict):
        return None
    found: dict[str, str] = {}
    for code, display in sorted(locales.items()):  # region-less codes sort first
        resolved = _ALIASES.get(code, code.split("-")[0])
        if resolved in found or not _has_dictionary(resolved):
            continue
        found[resolved] = _display(locales, resolved, display)
    return found


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
    """Where a probed language list ("languages") or a locale's dictionary lands.
    Public for `seed.py`, which writes the same files for a container-less loop."""
    return Path(cache_dir) / "names" / f"{name}.json"


def catalog(cache_dir: Path) -> dict[str, str]:
    """Selectable languages as {code: display name}, SCIENTIFIC always first.

    Cached in the process and on disk, so the admin page normally costs nothing
    and a restart with BirdNET-Go down still offers what it last found.
    """
    global _catalog
    with _lock:
        path = cache_path(cache_dir, "languages")
        if _catalog is None:
            _catalog = (0.0, _read(path).get("languages") or {})
        deadline, found = _catalog
        if time.monotonic() >= deadline:
            probed = _probe()
            if probed is not None:
                found = probed
                _write(path, {"languages": found})
            ttl = _CATALOG_TTL if probed is not None else _RETRY_TTL
            _catalog = (time.monotonic() + ttl, found)
        return {SCIENTIFIC: "Scientific", **found}


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
        path = cache_path(cache_dir, code)
        if code not in _dicts:
            cached = _read(path)
            _dicts[code] = (0.0, cached.get("etag", ""), cached.get("names") or {})
        deadline, etag, names = _dicts[code]
        if time.monotonic() >= deadline:
            payload, fresh = _fetch(f"{_API}/species/dictionary/{code}", etag)
            if isinstance(payload, dict):
                etag, names = fresh, payload
                _write(path, {"etag": etag, "names": names})
            ttl = _DICT_TTL if payload is not None else _RETRY_TTL
            _dicts[code] = (time.monotonic() + ttl, etag, names)
        return names, etag


def _capitalized(name: str) -> str:
    """Norwegian names come lowercase, English titled; a standalone label reads
    better capitalized, and a mixed dictionary evenly."""
    return name[:1].upper() + name[1:]


class Namer:
    """Renders a scientific name into the configured language(s). Built by `namer`."""

    def __init__(self, primary: str, secondary: str, names: dict[str, dict[str, str]], version: tuple):
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


def namer(primary: str, secondary: str, cache_dir: Path) -> Namer:
    """A Namer for the admin's language settings, loading only the dictionaries
    it needs. Cheap to call per render or per request: the loads are cached."""
    names, versions = {}, []
    for code in (primary, secondary):
        if code not in (SCIENTIFIC, NONE) and code not in names:
            names[code], version = dictionary(code, cache_dir)
            versions.append((code, version))
    return Namer(primary, secondary, names, tuple(versions))
