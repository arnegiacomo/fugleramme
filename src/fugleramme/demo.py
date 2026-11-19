"""Made-up birds for a frame with no detector (`Settings.detector_kind` DEMO, #358).

The birds come from GBIF checklists around the frame's location, by month, read
out of a tile built by `tools/demo_tiles.py`. A tile holds a quadtree of GBIF's
EQDGC cells: each code is its parent's plus a quadrant letter, A to D (north-west,
north-east, south-west, south-east), so the cell for a place is the longest code
the tile has, and dense areas keep small cells while sparse ones stay at 1°.

With no location or no tile, every bird with artwork is equally likely.

The detections are a fixed function of the location and the hour, so the page and
the panel agree, a restart does not reshuffle them, and the lookbacks, "new" and
the life list behave as they do with a detector.
"""

from __future__ import annotations

import bisect
import gzip
import json
import logging
import random
import threading
from collections import Counter
from datetime import UTC, datetime, timedelta
from functools import cache
from itertools import accumulate
from pathlib import Path

from .config import REPO_ROOT
from .names import artwork_keys, canonical
from .source import DEMO, Detection, Species
from .taxa import LABELS, common_of, is_bird

log = logging.getLogger(__name__)

TILE_DEGREES = 10
# EQDGC level 3 is 1/8°, about 14 x 10 km: records are placed to a few km at
# best, so a finer cell would show where birders walk rather than where birds are.
DEEPEST = 3
# A bird on fewer of a cell's checklists than this in a month is a stray there.
FLOOR = 0.01
# Below this many checklists a month is too thin to stand alone: the year stands in.
THIN_MONTH = 20
HISTORY_DAYS = 365
# Most detections an hour may hold, by local hour: a dawn chorus, a quiet night.
PER_HOUR = (1, 1, 1, 1, 2, 8, 10, 10, 8, 6, 5, 4, 4, 4, 4, 4, 5, 6, 6, 4, 2, 1, 1, 1)
_ARTWORK = REPO_ROOT / "assets" / "artwork"

Weights = tuple[tuple[str, ...], tuple[float, ...]]


def cell_code(lat: float, lon: float, level: int = DEEPEST) -> str:
    """The EQDGC code of the cell holding a point: W116N43 is 116-117°W and
    43-44°N, and each level after it adds the quadrant the point is in."""
    lon_whole, lat_whole = int(abs(lon) // 1), int(abs(lat) // 1)
    code = f"{'E' if lon >= 0 else 'W'}{lon_whole:03d}{'N' if lat >= 0 else 'S'}{lat_whole:02d}"
    west = lon_whole if lon >= 0 else -lon_whole - 1
    south = lat_whole if lat >= 0 else -lat_whole - 1
    x, y, size = lon - west, lat - south, 1.0
    for _ in range(level):
        size /= 2
        east, north = x >= size, y >= size
        code += "AB"[east] if north else "CD"[east]
        x -= size * east
        y -= size * north
    return code


def tile_name(lat: float, lon: float) -> str:
    """The tile a point is in, by its south-west corner: N40W120 is 40-50°N, 110-120°W."""
    south = int(lat // TILE_DEGREES) * TILE_DEGREES
    west = int(lon // TILE_DEGREES) * TILE_DEGREES
    return f"{'N' if south >= 0 else 'S'}{abs(south):02d}{'E' if west >= 0 else 'W'}{abs(west):03d}"


def tile_path(data_dir: Path, lat: float, lon: float) -> Path:
    return data_dir / "demo" / f"{tile_name(lat, lon)}.json.gz"


@cache
def drawable() -> tuple[str, ...]:
    """Every bird BirdNET names that some style has artwork for."""
    stems = {path.stem for path in _ARTWORK.glob("*/birds/*") if path.is_file()}
    names = (line.split("_", 1)[0] for line in LABELS.read_text().splitlines() if "_" in line)
    found = {
        canonical(name)
        for name in names
        if is_bird(name) and any(key in stems for key in artwork_keys(name))
    }
    return tuple(sorted(found))


def _cell(tile: dict, lat: float, lon: float) -> dict | None:
    cells = tile.get("cells", {})
    code = cell_code(lat, lon)
    while len(code) >= 7:
        if code in cells:
            return cells[code]
        code = code[:-1]
    return None


def _month_weights(cell: dict, names: list[str], month: int) -> Weights:
    """Each bird with artwork against its share of the cell's checklists in a
    month (1-12), strays dropped. A thin month reads the whole year instead."""
    totals = cell["checklists"]
    art = set(drawable())
    use_year = totals[month - 1] < THIN_MONTH
    total = sum(totals) if use_year else totals[month - 1]
    picked = []
    for index, months in cell["birds"]:
        share = (sum(months) if use_year else months[month - 1]) / max(total, 1)
        if share >= FLOOR and names[index] in art:
            picked.append((names[index], share))
    if not picked:
        return _anywhere()
    return tuple(n for n, _ in picked), tuple(accumulate(s for _, s in picked))


def _anywhere() -> Weights:
    birds = drawable()
    return birds, tuple(float(i + 1) for i in range(len(birds)))


class DemoSource:
    """A `source.Source` over made-up detections. Never `Unavailable`: there is
    nothing to reach once the tile is on disk."""

    kind = DEMO

    def __init__(self, lat: float | None, lon: float | None, data_dir: Path):
        self.base_url = "demo"
        self.station = self.base_url
        self._lock = threading.Lock()
        self._history: tuple[int, list[Detection]] = (-1, [])
        self._by_month = [_anywhere()] * 12
        if lat is None or lon is None:
            return
        self.base_url = self.station = f"demo:{lat:.3f},{lon:.3f}"
        path = tile_path(data_dir, lat, lon)
        try:
            tile = json.loads(gzip.decompress(path.read_bytes()))
        except (OSError, ValueError) as error:
            log.warning("No demo tile at %s (%s): any bird with artwork", path, error)
            return
        cell = _cell(tile, lat, lon)
        if cell is None:
            log.warning("No demo cell near %s in %s: any bird with artwork", self.base_url, path)
            return
        self._by_month = [_month_weights(cell, tile["names"], m) for m in range(1, 13)]

    def _hour(self, start: datetime) -> list[Detection]:
        """One hour's detections, from `start` (UTC, on the hour)."""
        local = start.astimezone()
        rng = random.Random(f"{self.station}:{start:%Y%m%d%H}")
        birds, cumulative = self._by_month[local.month - 1]
        count = rng.randint(0, PER_HOUR[local.hour])
        seconds = sorted(rng.sample(range(3600), count))
        slot = int(start.timestamp()) // 3600 * 100
        return [
            Detection(
                id=slot + i,
                detected_at=local + timedelta(seconds=second),
                scientific_name=birds[bisect.bisect(cumulative, rng.random() * cumulative[-1])],
                confidence=round(rng.uniform(0.7, 0.99), 2),
                clip_path=None,
            )
            for i, second in enumerate(seconds)
        ]

    def _heard(self) -> list[Detection]:
        """Every detection of the last `HISTORY_DAYS` up to now, newest first.
        Rebuilt once an hour; within it, only what has happened yet is heard."""
        now = datetime.now(UTC)
        top = now.replace(minute=0, second=0, microsecond=0)
        key = int(top.timestamp())
        with self._lock:
            if self._history[0] != key:
                hours = (top - timedelta(hours=h) for h in range(HISTORY_DAYS * 24))
                heard = [d for start in hours for d in reversed(self._hour(start))]
                self._history = (key, heard)
            heard = self._history[1]
        return [d for d in heard if d.detected_at <= now]

    def _since(self, hours: float) -> list[Detection]:
        heard = self._heard()
        if hours <= 0:
            return heard
        cutoff = datetime.now(UTC) - timedelta(hours=hours)
        return [d for d in heard if d.detected_at >= cutoff]

    def latest(self) -> Detection | None:
        heard = self._heard()
        return heard[0] if heard else None

    def recent(self, limit: int = 20) -> list[Detection]:
        return self._heard()[:limit]

    def species_since(self, hours: float = 24) -> list[tuple[str, int]]:
        counts = Counter(d.scientific_name for d in self._since(hours))
        return sorted(counts.items(), key=lambda pair: (-pair[1], pair[0]))

    def last_heard(self, hours: float = 24) -> list[str]:
        return list(dict.fromkeys(d.scientific_name for d in self._since(hours)))

    def life_list(self) -> list[Species]:
        first: dict[str, datetime] = {}
        for d in self._heard():
            first[d.scientific_name] = (
                d.detected_at
            )  # newest first, so the last write is the earliest
        return sorted((Species(n, t) for n, t in first.items()), key=lambda s: s.first_seen)

    def stats(self) -> dict:
        everything = self.species_since(0)
        return {
            "total": sum(n for _, n in everything),
            "species": len(everything),
            "last_24h": sum(n for _, n in self.species_since(24)),
            "top": [{"scientific_name": s, "n": n, "best": None} for s, n in everything[:10]],
        }

    def common_names(self) -> dict[str, dict[str, str]]:
        """English from BirdNET's own labels, for `languages`: the only names a
        frame with no detector has."""
        return {"en": {name: common_of(name) for name in drawable() if common_of(name)}}

    def close(self) -> None:
        """Nothing to release."""
