"""Map a detector's scientific name to a bird artwork file.

The detector emits modern eBird names, capitalized and space-separated
("Turdus merula"); artwork files are lowercase and hyphenated
("turdus-merula.png"). Since the files are named with modern taxonomy, the
lookup is just format normalization plus an exact/variant filename match - no
alias table. Names with no artwork resolve to None and the caller renders a
fallback card.

Artwork is grouped by provenance into per-source subfolders of `images_dir`
("vonwright", "gould", a user's "custom", ...); the admin UI (#2) selects which
sources are active. `available_sources` lists the folders present, `resolve`
turns a saved selection into the folders to actually draw from, and lookups
union variants across those folders.
"""

from __future__ import annotations

import random
import re
from collections.abc import Sequence
from pathlib import Path


def normalize(scientific_name: str) -> str:
    """"Turdus merula" -> "turdus-merula" (the file-key shape)."""
    return scientific_name.strip().lower().replace(" ", "-")


def available_sources(images_dir: Path) -> list[str]:
    """Source folder names present under `images_dir`, sorted."""
    try:
        return sorted(d.name for d in images_dir.iterdir() if d.is_dir())
    except OSError:
        return []


def resolve(requested: Sequence[str], images_dir: Path) -> list[str]:
    """The source folders to draw from: the requested ones that still exist, or
    every available source when the request is empty or names nothing present
    (a mis-click or a renamed folder must never blank the frame)."""
    available = available_sources(images_dir)
    chosen = [s for s in requested if s in available]
    return chosen or available


def variants_for(
    scientific_name: str, images_dir: Path, sources: Sequence[str]
) -> list[Path]:
    """All artwork for a name across `sources`: each source's "<key>.png" plus
    its "<key>-N.png" variants.

    Numbered-only matching keeps a species key (e.g. tetrao-urogallus) from
    picking up a hybrid file (tetrao-urogallus-x-lagopus-lagopus.png).
    """
    key = normalize(scientific_name)
    variant_re = re.compile(rf"{re.escape(key)}-\d+")
    matches: list[Path] = []
    for source in sources:
        folder = images_dir / source
        base = folder / f"{key}.png"
        if base.exists():
            matches.append(base)
        matches += [
            p for p in folder.glob(f"{key}-*.png") if variant_re.fullmatch(p.stem)
        ]
    return sorted(matches)


def image_for(
    scientific_name: str,
    images_dir: Path,
    sources: Sequence[str],
    rng: random.Random | None = None,
) -> Path | None:
    """A random artwork for a name (for panel variety), or None if none exists."""
    matches = variants_for(scientific_name, images_dir, sources)
    if not matches:
        return None
    return (rng or random).choice(matches)
