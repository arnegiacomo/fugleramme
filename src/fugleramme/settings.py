"""Runtime presentation settings (#2).

Persisted to a small JSON file (no frame DB, per #7), shared by the render loop
and the HTTP server in one process. The file is the source of truth: it is
reloaded when its mtime changes, so hand edits and admin-form writes are both
picked up live without a restart. Writes are atomic (temp + os.replace).

Presentation only - detector config lives in BirdNET-Go's own UI.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import DEFAULT_WEB_RESOLUTION, WEB_RESOLUTIONS
from .fonts import DEFAULT_FONT, DEFAULT_LABEL_SIZE, FONTS, LABEL_SIZES
from .languages import NONE, SCIENTIFIC
from .modes import DEFAULT_MODE, MODES

# How the frame hangs, counter-clockwise. 0/180 render landscape, 90/270 portrait.
ROTATIONS = (0, 90, 180, 270)

# Lookback windows offered in the admin UI, as (hours, label), shortest-first.
LOOKBACK_OPTIONS = (
    (6, "Last 6 hours"),
    (12, "Last 12 hours"),
    (24, "Today (24 hours)"),
    (72, "Last 3 days"),
    (168, "Last week"),
    (720, "Last 30 days"),
)


@dataclass(frozen=True)
class Settings:
    # Which page the frame shows; only the collage reads lookback_hours.
    mode: str = DEFAULT_MODE
    web_resolution: str = DEFAULT_WEB_RESOLUTION
    # Shapes both outputs; only the panel actually turns the pixels.
    rotation: int = 0
    lookback_hours: int = 24
    # How often the kiosk asks /state whether the collage changed; a check, not a render.
    kiosk_refresh_seconds: int = 3
    # Active artwork style folder; empty means "whichever is present" (resolved
    # against the filesystem at render time, so it survives a renamed style).
    style: str = ""
    auto_update: bool = False
    show_names: bool = True
    # Species-name languages: BirdNET-Go dictionary locales, resolved
    # against its API at render time like `sources`.
    primary_language: str = SCIENTIFIC
    secondary_language: str = NONE
    label_font: str = DEFAULT_FONT
    label_size: str = DEFAULT_LABEL_SIZE

    def oriented(self, resolution: tuple[int, int]) -> tuple[int, int]:
        """Apply the rotation's aspect to a landscape-native (w, h)."""
        long, short = max(resolution), min(resolution)
        return (short, long) if self.rotation % 180 else (long, short)

    def web_size(self) -> tuple[int, int]:
        """Kiosk render size: the selected resolution, oriented."""
        return self.oriented(WEB_RESOLUTIONS[self.web_resolution])


def _as_int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


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


def _language(value, default: str) -> str:
    """A locale-code shape, SCIENTIFIC, or NONE; availability is settled at
    render time, not here."""
    if not isinstance(value, str):
        return default
    value = value.strip().lower()
    return value if value in (NONE, SCIENTIFIC) or _LOCALE_RE.fullmatch(value) else default


def _coerce(raw: dict) -> Settings:
    """Build validated Settings from an untrusted dict, filling defaults and
    clamping out-of-range values. Unknown keys are ignored."""
    d = Settings()
    try:
        rotation = int(raw.get("rotation", d.rotation))
    except (TypeError, ValueError):
        rotation = d.rotation
    return Settings(
        mode=_one_of(str(raw.get("mode", d.mode)), MODES, d.mode),
        web_resolution=_one_of(
            str(raw.get("web_resolution", d.web_resolution)), WEB_RESOLUTIONS, d.web_resolution
        ),
        rotation=_one_of(rotation, ROTATIONS, d.rotation),
        lookback_hours=_as_int(raw.get("lookback_hours"), d.lookback_hours, 1, 24 * 30),
        kiosk_refresh_seconds=_as_int(
            raw.get("kiosk_refresh_seconds"), d.kiosk_refresh_seconds, 1, 3600
        ),
        style=_style(raw, d.style),
        auto_update=_as_bool(raw.get("auto_update"), d.auto_update),
        show_names=_as_bool(raw.get("show_names"), d.show_names),
        # A primary language is required: an empty pick means the scientific name.
        primary_language=_language(raw.get("primary_language"), d.primary_language) or SCIENTIFIC,
        secondary_language=_language(raw.get("secondary_language"), d.secondary_language),
        label_font=_one_of(str(raw.get("label_font", d.label_font)), FONTS, d.label_font),
        label_size=_one_of(str(raw.get("label_size", d.label_size)), LABEL_SIZES, d.label_size),
    )


def merged(base: Settings, **changes) -> Settings:
    """Validated Settings from a base plus overrides, without persisting."""
    return _coerce({**asdict(base), **changes})


class SettingsStore:
    """Thread-safe view of the settings file for the render loop + HTTP server."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._settings = Settings()
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
            raw = json.loads(self.path.read_text())
            self._mtime = self.path.stat().st_mtime
        except (OSError, json.JSONDecodeError):
            return  # missing or corrupt: fall back to what we have
        self._settings = _coerce(raw)

    def _write(self, settings: Settings) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(asdict(settings), indent=2) + "\n")
        os.replace(tmp, self.path)
        self._mtime = self.path.stat().st_mtime
