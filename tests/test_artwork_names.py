"""Consistency guards for shipped artwork filenames and attribution.

The filename check replaces a hand-maintained mapping: every bird must use a
BirdNET v2.4 label or an explicit exception. The manifest check ensures every
shipped bird and perch names the work it came from.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fugleramme.names import MANIFEST, PERCHES

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


def test_every_artwork_image_has_attribution():
    missing = []
    for style in sorted(path for path in IMAGES.iterdir() if path.is_dir()):
        path = style / MANIFEST
        listed = json.loads(path.read_text()) if path.exists() else {}
        for png in sorted(style.rglob("*.png")):
            key = png.relative_to(style).as_posix()
            entry = listed.get(key)
            source = entry.get("source") if isinstance(entry, dict) else None
            if not isinstance(source, str) or not source.strip():
                missing.append(f"{style.name}/{key}")
    assert not missing, "artwork images without attribution:\n" + "\n".join(missing)


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
