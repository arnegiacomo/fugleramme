"""Static, per-launch configuration for the frame service.

Paths and the network binding come from CLI flags. Presentation settings that
change at runtime (kiosk resolution, rotation, lookback, refresh) live in the
admin-owned settings file instead - see settings.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Kiosk render sizes offered in the admin UI, landscape-native (width, height).
# The panel render never uses these: it takes the attached Inky's own resolution.
WEB_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "720p": (1280, 720),
    "1080p": (1920, 1080),
    "1440p": (2560, 1440),
    "4K": (3840, 2160),
}

DEFAULT_WEB_RESOLUTION = "1080p"

# Panel render size when no Inky is attached (Mac dev loop): Impression 13.3".
FALLBACK_PANEL_RESOLUTION = (1600, 1200)

# Network defaults, single source for the app. The kiosk + admin bind here; the
# BirdNET-Go container publishes its own UI on BIRDNET_PORT (detector/docker-compose.yml).
DEFAULT_HOST = "0.0.0.0"
DEFAULT_PORT = 8080
BIRDNET_PORT = 8090

# Published docs site (mkdocs.yml site_url).
DOCS_URL = "https://arnegiacomo.dev/fugleramme/"

# Self-update source. HTTPS, not the ssh origin: a service fetch has no agent.
REPO_HTTPS_URL = "https://github.com/arnegiacomo/fugleramme.git"
RELEASES_API = "https://api.github.com/repos/arnegiacomo/fugleramme/releases/latest"

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
