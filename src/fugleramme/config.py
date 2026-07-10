"""Static, per-launch configuration for the frame service.

Paths and the network binding come from CLI flags. Presentation settings that
change at runtime (panel size, orientation, lookback, refresh) live in the
admin-owned settings file instead - see settings.py.
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

# Network defaults, single source for the app. The kiosk + admin bind here; the
# BirdNET-Go container publishes its own UI on BIRDNET_PORT (detector/docker-compose.yml).
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
BIRDNET_PORT = 8090

# Repo root: src/fugleramme/config.py -> repo root is three parents up.
REPO_ROOT = Path(__file__).resolve().parents[2]

# BirdNET-Go's SQLite, bind-mounted to detector/data and read directly by the frame.
DEFAULT_DB_PATH = REPO_ROOT / "detector" / "data" / "birdnet.db"

# Runtime presentation settings (#2), gitignored next to the DB.
DEFAULT_CONFIG_PATH = REPO_ROOT / "detector" / "data" / "settings.json"


@dataclass(frozen=True)
class Config:
    images_dir: Path
    db_path: Path
    output_path: Path
    host: str
    port: int
    config_path: Path
