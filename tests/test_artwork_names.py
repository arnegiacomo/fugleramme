"""Consistency guard: every artwork filename must be a name BirdNET-Go can emit.

This is the deterministic replacement for a hand-maintained mapping: if a file
is added or renamed with a stem that is not a BirdNET v2.4 label (and not an
explicit exception), this test fails. It is what keeps the detector-name ->
image lookup a plain exact match forever.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fugleramme.names import PERCHES

REPO = Path(__file__).resolve().parents[1]
IMAGES = REPO / "assets" / "artwork"
LABELS = REPO / "assets" / "birdnet_labels_v2.4.txt"
# Curation priority list: workstation-only tooling, so absent from a clone.
PRIORITY = REPO / "scripts" / "bergen_species.txt"

# Modern scientific names with no BirdNET v2.4 label - the artwork is kept but
# can never be triggered, so it is exempt from the label check.
EXCEPTIONS = {
    "alle-alle",  # Little Auk / Dovekie
    "branta-ruficollis",  # Red-breasted Goose
    "polysticta-stelleri",  # Steller's Eider
    "pagophila-eburnea",  # Ivory Gull
    "gulosus-aristotelis",  # European Shag
    "aquila-fasciata",  # Bonelli's Eagle
    "bubo-ascalaphus",  # Pharaoh Eagle-Owl
    "curruca-ruppeli",  # Rüppell's Warbler
    "falco-biarmicus",  # Lanner Falcon
    "falco-concolor",  # Sooty Falcon
    "gypaetus-barbatus",  # Bearded Vulture
    "neophron-percnopterus",  # Egyptian Vulture
    "numenius-tenuirostris",  # Slender-billed Curlew
    "pelecanus-crispus",  # Dalmatian Pelican
    "pinguinus-impennis",  # Great Auk (extinct)
}


def _labels() -> set[str]:
    keys = set()
    for line in LABELS.read_text().splitlines():
        if "_" in line:
            keys.add(line.split("_", 1)[0].strip().lower().replace(" ", "-"))
    return keys


def _base(stem: str) -> str:
    """Drop a trailing -N variant suffix."""
    return re.sub(r"-\d+$", "", stem)


def test_every_artwork_name_is_a_birdnet_label_or_exception():
    labels = _labels()
    unknown = []
    for png in sorted(IMAGES.rglob("*.png")):
        if png.parent.name == PERCHES:  # bare branches, named for the plant
            continue
        stem = _base(png.stem)
        if "-x-" in stem:  # hybrids: BirdNET never emits these
            continue
        if stem in labels or stem in EXCEPTIONS:
            continue
        unknown.append(png.name)
    assert not unknown, (
        "artwork filenames not matching a BirdNET label or exception:\n" + "\n".join(unknown)
    )


@pytest.mark.skipif(not PRIORITY.exists(), reason="curation tooling is workstation-only")
def test_curation_priority_names_are_birdnet_labels():
    # A typo here would silently sink a common bird to the bottom of the sheet.
    labels = _labels()
    listed = [
        line.strip().lower().replace(" ", "-")
        for line in PRIORITY.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    assert len(listed) == len(set(listed)), "duplicate species in the priority list"
    assert not [key for key in listed if key not in labels]
