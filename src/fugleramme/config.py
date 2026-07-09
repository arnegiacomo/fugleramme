"""Runtime configuration for the frame service.

The render resolution is driven by the chosen Inky panel size and is settable
from the CLI, since the physical panel is not fixed at this stage. Rendering
reads the resolution from here rather than hardcoding it, so a different panel
only changes one flag.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Inky Impression sizes -> native resolution (width, height).
PANEL_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "4.0": (600, 400),
    "7.3": (800, 480),
    "13.3": (1600, 1200),
}

DEFAULT_PANEL = "7.3"

# Repo root: src/fugleramme/config.py -> repo root is three parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Config:
    resolution: tuple[int, int]
    images_dir: Path
    db_path: Path
    output_path: Path
    host: str
    port: int


def resolve_resolution(panel: str | None, explicit: str | None) -> tuple[int, int]:
    """Return (width, height) from a panel preset or an explicit WxH string.

    An explicit --resolution wins over --panel so unusual panels are possible.
    """
    if explicit:
        try:
            w, h = explicit.lower().split("x")
            return int(w), int(h)
        except ValueError as exc:
            raise ValueError(
                f"--resolution must look like 800x480, got {explicit!r}"
            ) from exc
    key = panel or DEFAULT_PANEL
    if key not in PANEL_RESOLUTIONS:
        raise ValueError(
            f"unknown panel {key!r}; choose one of {sorted(PANEL_RESOLUTIONS)} "
            f"or pass --resolution WxH"
        )
    return PANEL_RESOLUTIONS[key]
