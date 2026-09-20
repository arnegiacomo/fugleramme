"""Guards against the same cut-out shipping twice under two species.

A shared source URL carries no signal - a plate holding several birds is cut
once per bird. Two files holding the same *bird* is the defect, and it arrives
either from a plate whose description names two species or from re-cutting a
sheet the library already has off a different scan. The frame then states a
species that was never there.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from fugleramme.names import MANIFEST, SUFFIXES

REPO = Path(__file__).resolve().parents[1]
IMAGES = REPO / "assets" / "artwork"

# Silhouette overlap, intersection over union; closest unrelated pair is 0.97.
OUTLINE = 0.90

# Mean grey difference; the known re-cuts scored 0.6 and 2.9, the closest pair 8.3.
INK = 5.0


def _styles() -> list[Path]:
    return sorted(path for path in IMAGES.iterdir() if path.is_dir())


def _plates(style: Path) -> list[Path]:
    return sorted(path for suffix in SUFFIXES for path in style.rglob(f"*{suffix}"))


def test_no_plate_is_another_plate_cut_twice(library):
    twins = []
    for style in _styles():
        plates = _plates(style)
        if len(plates) < 2:
            continue
        outlines = np.array([library[plate].outline for plate in plates])
        inks = np.array([library[plate].ink for plate in plates])

        overlap = outlines.astype(np.uint16) @ outlines.T.astype(np.uint16)
        area = outlines.sum(axis=1)
        union = np.maximum(area[:, None] + area[None, :] - overlap, 1)
        similar = np.triu(overlap / union >= OUTLINE, k=1)

        for left, right in zip(*np.where(similar), strict=True):
            ink = float(np.abs(inks[left] - inks[right]).mean())
            if ink < INK:
                names = (plates[left].relative_to(style), plates[right].relative_to(style))
                twins.append(f"{style.name}: {names[0]} and {names[1]} (ink {ink:.1f})")

    assert not twins, (
        "plates holding the same bird twice - one of each pair names a species\n"
        "it does not show, so check both against the source plate and drop the\n"
        "wrong one:\n" + "\n".join(twins)
    )


def test_every_manifest_entry_names_a_shipped_file():
    """The other half of the attribution guard, which only checks file to entry."""
    orphans = []
    for style in _styles():
        path = style / MANIFEST
        if not path.exists():
            continue
        for key in json.loads(path.read_text()):
            if not (style / key).exists():
                orphans.append(f"{style.name}: {key}")
    assert not orphans, "manifest entries with no image on disk:\n" + "\n".join(orphans)
