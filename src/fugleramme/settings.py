"""Runtime presentation settings (#2).

Persisted to a small JSON file (no frame DB, per #7), shared by the render loop
and the HTTP server in one process. The file is the source of truth: it is
reloaded when its mtime changes, so hand edits and admin-form writes are both
picked up live without a restart. Writes are atomic (temp + os.replace).

Presentation only - detector config lives in BirdNET-Go's own UI, and bird-name
display / language is #5.
"""

from __future__ import annotations

import json
import os
import threading
from dataclasses import asdict, dataclass
from pathlib import Path

from .config import DEFAULT_WEB_RESOLUTION, WEB_RESOLUTIONS

ORIENTATIONS = ("landscape", "portrait")

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
    web_resolution: str = DEFAULT_WEB_RESOLUTION
    # Applies to both outputs: the kiosk render and the panel push.
    orientation: str = "landscape"
    lookback_hours: int = 24
    # How often the kiosk asks /state whether the collage changed; a check, not a render.
    kiosk_refresh_seconds: int = 3
    # Active artwork source folders; empty means "all present" (resolved against
    # the filesystem at render time, so it survives added/removed sources).
    sources: tuple[str, ...] = ()

    def oriented(self, resolution: tuple[int, int]) -> tuple[int, int]:
        """Apply orientation to a landscape-native (w, h)."""
        long, short = max(resolution), min(resolution)
        return (long, short) if self.orientation == "landscape" else (short, long)

    def web_size(self) -> tuple[int, int]:
        """Kiosk render size: the selected resolution, oriented."""
        return self.oriented(WEB_RESOLUTIONS[self.web_resolution])


def _as_int(value, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(value)))
    except (TypeError, ValueError):
        return default


def _sources(value) -> tuple[str, ...]:
    """A deduped tuple of source names, order preserved. Existence isn't checked
    here (settings has no filesystem view) - names.resolve does that at use."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict.fromkeys(s for s in value if isinstance(s, str) and s))


def _coerce(raw: dict) -> Settings:
    """Build validated Settings from an untrusted dict, filling defaults and
    clamping out-of-range values. Unknown keys are ignored."""
    d = Settings()
    web_resolution = str(raw.get("web_resolution", d.web_resolution))
    if web_resolution not in WEB_RESOLUTIONS:
        web_resolution = d.web_resolution
    orientation = str(raw.get("orientation", d.orientation)).lower()
    if orientation not in ORIENTATIONS:
        orientation = d.orientation
    return Settings(
        web_resolution=web_resolution,
        orientation=orientation,
        lookback_hours=_as_int(raw.get("lookback_hours"), d.lookback_hours, 1, 24 * 30),
        kiosk_refresh_seconds=_as_int(
            raw.get("kiosk_refresh_seconds"), d.kiosk_refresh_seconds, 1, 3600
        ),
        sources=_sources(raw.get("sources")),
    )


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
            new = _coerce({**asdict(self._settings), **changes})
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
