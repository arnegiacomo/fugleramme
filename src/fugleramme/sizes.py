"""Real-world bird size, used to scale birds in the collage.

Body mass (grams) per species from AVONET (Tobias et al. 2022, Ecology Letters,
CC BY 4.0), vendored as `assets/bird_sizes.csv` keyed by eBird scientific name.
AVONET has no body-length column, so mass is the size metric; the collage
compresses it with a fractional exponent (see SIZE_EXPONENT) so big birds read
bigger without small ones vanishing.
"""

from __future__ import annotations

import csv

from .config import REPO_ROOT
from .names import normalize

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
