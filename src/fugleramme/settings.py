"""Runtime presentation settings (#2).

Persisted to a small JSON file (no frame DB, per #7), shared by the render loop
and the HTTP server in one process. The file is the source of truth: it is
reloaded when its mtime changes, so hand edits and admin-form writes are both
picked up live without a restart. Writes are atomic (temp + os.replace).

Presentation, plus where the detector is - how it listens stays BirdNET-Go's own UI.
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass, fields
from pathlib import Path

from .config import (
    DEFAULT_DETECTOR_URL,
    DEFAULT_WEB_ASPECT,
    DEFAULT_WEB_RESOLUTION,
    WEB_ASPECTS,
    WEB_HEIGHTS,
)
from .languages import NONE, SCIENTIFIC
from .modes import DEFAULT_MODE, MODES
from .render.collage import DEFAULT_MARGIN, DEFAULT_RANKING, NO_LIMIT, RANKINGS
from .render.fonts import DEFAULT_FONT, DEFAULT_LABEL_SIZE, FONTS, LABEL_SIZES
from .render.packing import DEFAULT_LAYOUT, LAYOUTS

log = logging.getLogger(__name__)

# How the frame hangs, counter-clockwise. 0/180 render landscape, 90/270 portrait.
ROTATIONS = (0, 90, 180, 270)

# Not a window at all: every species the detector has ever heard, so the collage
# keeps growing. Sorts last despite being the smallest number - see `lookback_order`.
ALL_TIME = 0

# Lookback windows offered in the admin UI, as (hours, label), shortest-first.
LOOKBACK_OPTIONS = (
    (0.25, "Last 15 minutes"),
    (0.5, "Last 30 minutes"),
    (1, "Last hour"),
    (3, "Last 3 hours"),
    (6, "Last 6 hours"),
    (12, "Last 12 hours"),
    (24, "Today (24 hours)"),
    (72, "Last 3 days"),
    (168, "Last week"),
    (720, "Last 30 days"),
    (ALL_TIME, "All time"),
)


# What the frame ships limited to, and the number the admin warns past (#53).
DEFAULT_LIMIT = 40
# Not a render budget - only so a hand-edited file cannot hand the packer a
# number no Pi finishes.
LIMIT_CEILING = 500


# How long the panel holds a page before the birds may change it, as (minutes,
# label). A floor, not a timer: nothing repaints until the page differs (#64).
REFRESH_OPTIONS = (
    (0, "As soon as it changes"),
    (5, "At most every 5 minutes"),
    (10, "At most every 10 minutes"),
    (15, "At most every 15 minutes"),
    (30, "At most every 30 minutes"),
    (60, "At most every hour"),
)


# A quarter off each edge already leaves half the page, so margin stops here.
MARGIN_CEILING = 25


def lookback_order(hours: float) -> float:
    """Sort key: ALL_TIME is the longest window, not the shortest."""
    return float("inf") if hours == ALL_TIME else hours


@dataclass(frozen=True)
class Settings:
    # Which page the frame shows; only the collage reads lookback_hours.
    mode: str = DEFAULT_MODE
    web_resolution: str = DEFAULT_WEB_RESOLUTION
    # Locked, the kiosk follows the panel; unlocked, the aspect and portrait below.
    web_lock: bool = True
    web_aspect: str = DEFAULT_WEB_ASPECT
    web_portrait: bool = False
    # Shapes the panel, and the kiosk while it is locked; only the panel turns the pixels.
    rotation: int = 0
    lookback_hours: float = 24
    refresh_minutes: int = 0
    # The collage's own default, as a percent.
    margin: int = round(DEFAULT_MARGIN * 100)
    # Which birds make the page (#53); NO_LIMIT is every species the window holds.
    species_limit: int = DEFAULT_LIMIT
    ranking: str = DEFAULT_RANKING
    # Active artwork style folder; empty means "whichever is present" (resolved
    # against the filesystem at render time, so it survives a renamed style).
    style: str = ""
    # How the collage packs its birds; a plate has one bird and ignores it.
    layout: str = DEFAULT_LAYOUT
    auto_update: bool = False
    show_names: bool = True
    # Species-name languages: BirdNET-Go dictionary locales, resolved
    # against its API at render time like `sources`.
    primary_language: str = SCIENTIFIC
    secondary_language: str = NONE
    label_font: str = DEFAULT_FONT
    label_size: str = DEFAULT_LABEL_SIZE
    # Only needed for a BirdNET-Go that authenticates. The username is not in the
    # admin: BirdNET-Go asks for a password and matches the name against a fixed
    # client id, so it is here only for an install that changed that id.
    detector_url: str = DEFAULT_DETECTOR_URL
    detector_username: str = ""
    detector_password: str = ""
    # The door (#52): shut only with this on and a password saved. Off is also how
    # the admin is opened up again for a while without throwing the password away.
    require_sign_in: bool = False
    # What the admin page asks for; empty is the default and leaves it open.
    admin_password: str = ""
    # Behind a reverse proxy every request arrives from the proxy, so the sign-in
    # limiter has to key on the address the proxy reports instead (#52).
    behind_proxy: bool = False
    # Signs the admin's session cookie. Minted at the first sign-in and kept, so a
    # restart does not sign everyone out; not a setting anyone edits.
    session_secret: str = ""

    @property
    def admin_locked(self) -> bool:
        """Whether the admin actually asks for anything. Either half alone leaves
        it open: a password nobody is asked for, or a switch with nothing behind it."""
        return self.require_sign_in and bool(self.admin_password)

    def oriented(self, resolution: tuple[int, int]) -> tuple[int, int]:
        """Apply the rotation's aspect to a landscape-native (w, h)."""
        long, short = max(resolution), min(resolution)
        return (short, long) if self.rotation % 180 else (long, short)

    def web_size(self, panel: tuple[int, int] | None) -> tuple[int, int]:
        """Kiosk render size at the selected height. Locked, the panel scaled and
        turned; unlocked, or with no panel (None) to follow, its own aspect."""
        height = WEB_HEIGHTS[self.web_resolution]
        if self.web_lock and panel:
            scale = height / min(panel)
            return self.oriented((round(panel[0] * scale), round(panel[1] * scale)))
        w, h = WEB_ASPECTS[self.web_aspect]
        width = round(height * w / h)
        return (height, width) if self.web_portrait else (width, height)


def _as_int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _as_hours(value, default: float) -> float:
    """Fractional so the admin can offer minutes; a whole number stays an int, so
    the settings file reads as plain hours."""
    try:
        hours = max(ALL_TIME, min(24 * 30, float(value)))
    except (TypeError, ValueError):
        return default
    return int(hours) if hours == int(hours) else hours


def _as_bool(value, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in ("1", "true", "on", "yes")
    return default


def _one_of(value, options, default):
    """The value if it is one of the offered options, else the default."""
    return value if value in options else default


def _style(raw: dict, default: str) -> str:
    """The active style name. Falls back to the first entry of the older
    multi-source `sources` list, so an existing settings.json migrates in place;
    a name that no longer exists is settled by names.resolve, not here."""
    value = raw.get("style")
    if not isinstance(value, str):
        legacy = raw.get("sources")
        value = legacy[0] if isinstance(legacy, (list, tuple)) and legacy else None
    return value.strip() if isinstance(value, str) else default


_LOCALE_RE = re.compile(r"[a-z]{2,3}(-[a-z]{2})?")
_URL_RE = re.compile(r"https?://[^\s/]+(/[^\s]*)?")


def _language(value, default: str) -> str:
    """A locale-code shape, SCIENTIFIC, or NONE; availability is settled at
    render time, not here."""
    if not isinstance(value, str):
        return default
    value = value.strip().lower()
    return value if value in (NONE, SCIENTIFIC) or _LOCALE_RE.fullmatch(value) else default


def _url(value, default: str) -> str:
    """An http(s) base address; the trailing slash goes so paths join cleanly.
    Whether anything answers there is settled at request time, not here."""
    if not isinstance(value, str):
        return default
    value = value.strip().rstrip("/")
    return value if _URL_RE.fullmatch(value) else default


def _text(value, default: str) -> str:
    return value.strip() if isinstance(value, str) else default


def _secret(value, default: str) -> str:
    """Kept byte for byte: the login page compares what was typed, so a stripped
    trailing space would save a password that no longer signs anyone in."""
    return value if isinstance(value, str) else default


_DEFAULTS = Settings()


def _coerce(raw: dict, base: Settings | None = None) -> Settings:
    """Build validated Settings from an untrusted dict, filling defaults and
    clamping out-of-range values. Unknown keys are ignored. `base` supplies the
    defaults, so a launch flag can stand in for a key the file does not carry."""
    d = base or _DEFAULTS
    try:
        rotation = int(raw.get("rotation", d.rotation))
    except (TypeError, ValueError):
        rotation = d.rotation
    rotation = _one_of(rotation, ROTATIONS, d.rotation)
    return Settings(
        mode=_one_of(str(raw.get("mode", d.mode)), MODES, d.mode),
        web_resolution=_one_of(
            str(raw.get("web_resolution", d.web_resolution)), WEB_HEIGHTS, d.web_resolution
        ),
        web_lock=_as_bool(raw.get("web_lock"), d.web_lock),
        web_aspect=_one_of(str(raw.get("web_aspect", d.web_aspect)), WEB_ASPECTS, d.web_aspect),
        # Absent, a file's own rotation says which way its page was turned.
        web_portrait=_as_bool(
            raw.get("web_portrait"), rotation % 180 != 0 if "rotation" in raw else d.web_portrait
        ),
        rotation=rotation,
        lookback_hours=_as_hours(raw.get("lookback_hours"), d.lookback_hours),
        refresh_minutes=_as_int(raw.get("refresh_minutes"), d.refresh_minutes, 0, 24 * 60),
        margin=_as_int(raw.get("margin"), d.margin, 0, MARGIN_CEILING),
        species_limit=_as_int(raw.get("species_limit"), d.species_limit, NO_LIMIT, LIMIT_CEILING),
        ranking=_one_of(str(raw.get("ranking", d.ranking)), RANKINGS, d.ranking),
        style=_style(raw, d.style),
        layout=_one_of(str(raw.get("layout", d.layout)), LAYOUTS, d.layout),
        auto_update=_as_bool(raw.get("auto_update"), d.auto_update),
        show_names=_as_bool(raw.get("show_names"), d.show_names),
        # A primary language is required: an empty pick means the scientific name.
        primary_language=_language(raw.get("primary_language"), d.primary_language) or SCIENTIFIC,
        secondary_language=_language(raw.get("secondary_language"), d.secondary_language),
        label_font=_one_of(str(raw.get("label_font", d.label_font)), FONTS, d.label_font),
        label_size=_one_of(str(raw.get("label_size", d.label_size)), LABEL_SIZES, d.label_size),
        detector_url=_url(raw.get("detector_url"), d.detector_url),
        detector_username=_text(raw.get("detector_username"), d.detector_username),
        detector_password=_text(raw.get("detector_password"), d.detector_password),
        require_sign_in=_as_bool(raw.get("require_sign_in"), d.require_sign_in),
        behind_proxy=_as_bool(raw.get("behind_proxy"), d.behind_proxy),
        admin_password=_secret(raw.get("admin_password"), d.admin_password),
        session_secret=_text(raw.get("session_secret"), d.session_secret),
    )


def merged(base: Settings, **changes) -> Settings:
    """Validated Settings from a base plus overrides, without persisting."""
    return _coerce({**asdict(base), **changes})


ENV_PREFIX = "FUGLERAMME_"

# Minted by the frame, never typed by anyone, so it is no one's to seed.
_NOT_SEEDED = frozenset({"session_secret"})


def from_env(base: Settings | None = None) -> Settings:
    """Settings seeded from the environment: `FUGLERAMME_<FIELD>` for any field
    of `Settings` but the session secret, read off the dataclass so a new setting
    needs nothing here.

    **A seed, not an override.** These are the store's defaults, so a key the file
    already carries wins and the variable is inert from the first Save on. The
    container image is the only reason for it: one that reset the style on every
    recreate would make the admin page, which offers to change it, a liar.
    """
    raw = {
        field.name: os.environ[key]
        for field in fields(Settings)
        if field.name not in _NOT_SEEDED and (key := ENV_PREFIX + field.name.upper()) in os.environ
    }
    return _coerce(raw, base)


class SettingsStore:
    """Thread-safe view of the settings file for the render loop + HTTP server."""

    def __init__(self, path: Path, defaults: Settings | None = None):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._defaults = defaults or _DEFAULTS
        self._settings = self._defaults
        self._mtime: float | None = None
        self._load()

    def get(self) -> Settings:
        with self._lock:
            self._reload_if_changed()
            return self._settings

    def update(self, **changes) -> Settings:
        with self._lock:
            self._reload_if_changed()
            new = merged(self._settings, **changes)
            self._write(new)
            self._settings = new
            return new

    def _reload_if_changed(self) -> None:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return  # missing: keep current in-memory settings
        if mtime != self._mtime:
            self._load()

    def _load(self) -> None:
        try:
            text = self.path.read_text()
            self._mtime = self.path.stat().st_mtime  # recorded first, so a bad file warns once
        except OSError:
            return  # missing: a fresh frame, or one whose file went away
        try:
            raw = json.loads(text)
        except json.JSONDecodeError as error:
            # Unsaid, a hand edit that broke the file takes every setting with it on
            # the next restart, the admin's own password included.
            log.warning("Ignoring %s, it is not valid JSON: %s", self.path, error)
            return
        if not isinstance(raw, dict):
            log.warning("Ignoring %s, it is not a JSON object of settings", self.path)
            return
        self._settings = _coerce(raw, self._defaults)

    def _write(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        # 0600 at creation: the password must never exist under the umask's mode.
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as handle:
            os.fchmod(fd, 0o600)  # O_CREAT leaves a leftover temp file its old mode
            handle.write(json.dumps(asdict(settings), indent=2) + "\n")
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime
