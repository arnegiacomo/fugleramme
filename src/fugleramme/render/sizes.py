"""Real-world bird size, used to scale birds in the collage.

Body mass (grams) per species from AVONET (Tobias et al. 2022, Ecology Letters,
CC BY 4.0), vendored as `assets/bird_sizes.csv` keyed by eBird scientific name.
AVONET has no body-length column, so mass is the size metric; the collage
compresses it with a fractional exponent (see SIZE_EXPONENT) so big birds read
bigger without small ones vanishing.

Mass answers how big a bird should be drawn; the bird box answers how big the
plate has to be drawn for it to come out that size (`span_ratio`).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import NamedTuple

from ..config import REPO_ROOT
from ..names import normalize

# Display size scales as mass ** SIZE_EXPONENT. <1 is the "diminishing returns"
# compression: 0 = all equal, 1 = proportional to mass. ~0.14 makes the
# heaviest species roughly 2.5x the lightest, linearly.
SIZE_EXPONENT = 0.14

_SIZES_CSV = REPO_ROOT / "assets" / "bird_sizes.csv"


def _load() -> dict[str, float]:
    masses: dict[str, float] = {}
    with _SIZES_CSV.open() as f:
        for row in csv.DictReader(f):
            masses[normalize(row["scientific_name"])] = float(row["mass_g"])
    return masses


_MASS = _load()
_MEDIAN = sorted(_MASS.values())[len(_MASS) // 2] if _MASS else 1.0


def mass_of(scientific_name: str) -> float:
    """Body mass in grams, or the dataset median for an unknown species."""
    return _MASS.get(normalize(scientific_name), _MEDIAN)


# "birds/<file>.webp" -> {"box": [x0, y0, x1, y1], "cut": [w, h]}.
GEOMETRY = "geometry.json"


class Geometry(NamedTuple):
    """A bird box, and the trimmed cut-out somebody drew it on.

    The box is fractions, which mean nothing without the crop they were measured
    against - so the crop is recorded beside them and checked before use.
    """

    box: tuple[float, float, float, float]
    cut: tuple[int, int]


_boxes: dict[Path, tuple[float, dict[str, Geometry]]] = {}


def _entry(value: object) -> Geometry | None:
    """One record entry, or None if it is not one.

    Checked per entry because the file is hand-edited: one typo must not cost a
    style its boxes, nor stop a render loop that has no page to fall back to.
    """
    if not isinstance(value, dict):
        return None
    box, cut = value.get("box"), value.get("cut")
    if not isinstance(box, list) or len(box) != 4:
        return None
    if not isinstance(cut, list) or len(cut) != 2:
        return None
    try:
        x0, y0, x1, y1 = (float(number) for number in box)
        width, height = (int(number) for number in cut)
    except (TypeError, ValueError):
        return None
    if width <= 0 or height <= 0:
        return None
    if 0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0:
        return Geometry((x0, y0, x1, y1), (width, height))
    return None


def _geometry(folder: Path) -> dict[str, Geometry]:
    """A style folder's bird boxes, or {} if it keeps none. Cached on mtime like
    the manifest: the collage asks once per bird per pack."""
    path = folder / GEOMETRY
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _boxes.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    record = {
        str(key): found for key, value in loaded.items() if (found := _entry(value)) is not None
    }
    _boxes[path] = (mtime, record)
    return record


def geometry_of(path: Path) -> Geometry | None:
    """The record for one cut-out, from the nearest one at or above it: a style
    keeps one file, so a plate is keyed by its path under that folder."""
    for folder in (path.parent, path.parent.parent):
        listed = _geometry(folder)
        if listed:
            return listed.get(path.relative_to(folder).as_posix())
    return None


def span_ratio(path: Path, size: tuple[int, int]) -> float:
    """How much bigger a cut-out is than the bird in it, along the axis the
    collage measures.

    The collage sizes a plate by its longest side, which is the bird's own
    length only when the file is one bird cut tight. 1.0 without a usable box,
    which is what every plate drew at before boxes existed.
    """
    found = geometry_of(path)
    # A box drawn on a different crop measures a part of the picture that has
    # moved, and every number in it still looks valid. Nothing else catches this.
    if found is None or found.cut != size:
        return 1.0
    box, (width, height) = found.box, size
    span = max((box[2] - box[0]) * width, (box[3] - box[1]) * height)
    return max(width, height) / span if span > 0 else 1.0
