"""How big a bird is drawn, and so how central it lands on the page.

`Settings.size_by` picks what decides it: real body mass alone, or mass times
how often the species was actually heard. Body mass (grams) per species from
AVONET (Tobias et al. 2022, Ecology Letters, CC BY 4.0), vendored as
`assets/bird_sizes.csv` keyed by eBird scientific name; AVONET has no
body-length column, so mass is the size metric. Both inputs are compressed hard
on their way to the page - it is an illustrated plate, not a chart.
"""

from __future__ import annotations

import csv
import math
from collections.abc import Iterable

from ..config import REPO_ROOT
from ..names import normalize

# Display size scales as mass ** SIZE_EXPONENT. <1 is the "diminishing returns"
# compression: 0 = all equal, 1 = proportional to mass. ~0.14 makes the
# heaviest species roughly 2.5x the lightest, linearly.
SIZE_EXPONENT = 0.14

# Stored in settings.json, so renaming a value resets every frame that had it.
SIZE_BY_MASS = "mass"
SIZE_BY_HEARD = "heard"
SIZE_BY_OPTIONS = {
    SIZE_BY_MASS: "Real body size",
    SIZE_BY_HEARD: "Body size, and how often heard",
}
DEFAULT_SIZE_BY = SIZE_BY_MASS

# Each band up multiplies display size by this, so top to bottom is ~2.6x -
# level with SIZE_EXPONENT's ~2.5x, so neither input can flatten the other.
TIER_STEP = 1.6

# Band edges in halvings below the busiest species: within ~2.8x of it is the
# top band, within ~16x the middle. Wide on purpose, see `count_tiers`.
_BAND_EDGES = (1.5, 4.0)

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


def count_tiers(counts: Iterable[tuple[str, int]]) -> dict[str, int]:
    """Species to a broad "how often heard" band, 2 = busiest, 0 = quietest.

    Bands, never the count itself: the layout is a function of its cache key and
    the loop repaints when that key moves, so a raw count would repack the page
    on every single detection. Measured against the busiest species rather than
    fixed numbers, so a band means the same at a quiet feeder and a loud one.
    """
    tally = {name: count for name, count in counts if count > 0}
    if not tally:
        return {}
    top = max(tally.values())
    return {
        name: len(_BAND_EDGES) - sum(math.log2(top / count) >= edge for edge in _BAND_EDGES)
        for name, count in tally.items()
    }
