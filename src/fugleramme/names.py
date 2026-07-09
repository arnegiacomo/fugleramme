"""Map a detector's scientific name to a bird artwork file.

The detector emits modern eBird names, capitalized and space-separated
("Turdus merula"); artwork files are lowercase and hyphenated
("turdus-merula.png"). Since the files are named with modern taxonomy, the
lookup is just format normalization plus an exact/variant filename match - no
alias table. Names with no artwork resolve to None and the caller renders a
fallback card.
"""

from __future__ import annotations

import random
import re
from pathlib import Path


def normalize(scientific_name: str) -> str:
    """"Turdus merula" -> "turdus-merula" (the file-key shape)."""
    return scientific_name.strip().lower().replace(" ", "-")


def variants_for(scientific_name: str, images_dir: Path) -> list[Path]:
    """All artwork files for a name: the base "<key>.png" plus "<key>-N.png".

    Numbered-only matching keeps a species key (e.g. tetrao-urogallus) from
    picking up a hybrid file (tetrao-urogallus-x-lagopus-lagopus.png).
    """
    key = normalize(scientific_name)
    matches = []
    base = images_dir / f"{key}.png"
    if base.exists():
        matches.append(base)
    variant_re = re.compile(rf"{re.escape(key)}-\d+")
    matches += [
        p for p in images_dir.glob(f"{key}-*.png") if variant_re.fullmatch(p.stem)
    ]
    return sorted(matches)


def image_for(
    scientific_name: str,
    images_dir: Path,
    rng: random.Random | None = None,
) -> Path | None:
    """A random artwork for a name (for panel variety), or None if none exists."""
    matches = variants_for(scientific_name, images_dir)
    if not matches:
        return None
    return (rng or random).choice(matches)
