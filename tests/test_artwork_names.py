"""Consistency guards for shipped artwork filenames and attribution.

The filename check replaces a hand-maintained mapping: every bird must use a
BirdNET v2.4 label or an explicit exception. The manifest check ensures every
shipped bird and perch names the work it came from, and that the work it names
is one ATTRIBUTION.md actually describes - a manifest key is only a word until
something maps it to terms and a licence. The bird box checks hold geometry.json
and the plates to each other, both ways: the boxes are hand-made data the collage
scales by, and a wrong one comes out as a bird drawn at the wrong size rather than
as an error.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path

from fugleramme.names import BIRDS, MANIFEST, PERCHES, SUFFIXES, normalize
from fugleramme.render.sizes import GEOMETRY

REPO = Path(__file__).resolve().parents[1]
IMAGES = REPO / "assets" / "artwork"
LABELS = REPO / "assets" / "birdnet_labels_v2.4.txt"
SIZES = REPO / "assets" / "bird_sizes.csv"
ATTRIBUTION = "ATTRIBUTION.md"

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
    """Every label as a filename key, under the species' current name.

    v2.4's label set is frozen at its training taxonomy, so 236 of its 6522
    labels now name a species the detector reports under a newer name.
    `normalize` folds both spellings to the current one, which is what every
    other table in the frame is keyed on - so that is the one spelling a
    shipped plate may use. `variants_for` still reads the label's spelling for
    the sake of a user's own style folder, which no test ever sees; accepting
    it here too would leave the convention unenforced and shipped assets free
    to drift back into two namesets.
    """
    keys = set()
    for line in LABELS.read_text().splitlines():
        if "_" in line:
            keys.add(normalize(line.split("_", 1)[0]))
    return keys


def _base(stem: str) -> str:
    """Drop a trailing -N variant suffix."""
    return re.sub(r"-\d+$", "", stem)


def _artwork(folder: Path) -> list[Path]:
    """Every image under `folder` the frame would draw. Off names.SUFFIXES, so a
    format the frame learns to read is one these guards cover too."""
    return sorted(path for suffix in SUFFIXES for path in folder.rglob(f"*{suffix}"))


def _plates() -> list[tuple[Path, str]]:
    """Every shipped bird plate with its species key, bare branches aside."""
    return [
        (plate, _base(plate.stem))
        for plate in _artwork(IMAGES)
        if plate.parent.name != PERCHES  # perches are named for the plant
    ]


def _bird_boxes() -> list[tuple[Path, str, dict]]:
    """Every bird box a shipped style keeps, with its style and the key it is
    filed under. A style with no geometry.json simply contributes none - boxes
    are optional, and `span_ratio` answers a plate without one at 1.0."""
    boxes = []
    for style in sorted(path for path in IMAGES.iterdir() if path.is_dir()):
        path = style / GEOMETRY
        if not path.exists():
            continue
        for key, box in json.loads(path.read_text()).items():
            boxes.append((style, key, box))
    return boxes


def test_every_artwork_name_is_a_birdnet_label_or_exception():
    labels = _labels()
    unknown = []
    for plate, stem in _plates():
        if "-x-" in stem:  # hybrids: BirdNET never emits these
            continue
        if stem in labels or stem in EXCEPTIONS:
            continue
        unknown.append(plate.name)
    assert not unknown, (
        "artwork filenames not naming a BirdNET species under its current name,\n"
        "and not listed as an exception (a superseded spelling belongs in the\n"
        "rename, not here):\n" + "\n".join(unknown)
    )


def test_every_detectable_plate_has_a_body_mass():
    """A plate the detector can put on the page must have a size to draw it at.

    `sizes.mass_of` falls back to the dataset median rather than raising, so a
    missing row costs no crash and no blank frame - the bird is simply drawn at
    35g whatever it really weighs, which for a large one is half the size it
    should be. Membership of the label set is the test: a hybrid or a species
    v2.4 has no label for can never be detected, so its fallback is unreachable
    and AVONET has no row for it to find anyway.
    """
    with SIZES.open() as handle:
        masses = {normalize(row["scientific_name"]) for row in csv.DictReader(handle)}
    labels = _labels()
    missing = sorted({stem for _plate, stem in _plates() if stem in labels} - masses)
    assert not missing, "shipped plates with no body mass in bird_sizes.csv:\n" + "\n".join(missing)


def test_every_bird_box_names_a_plate_that_exists():
    """A box is keyed by path, and paths move.

    Variants are numbered contiguously, so dropping one renumbers the rest: a
    key left behind by a deleted or renamed plate is not merely unused data, it
    comes back as the box of whichever bird inherited the name. The reverse is
    fine - a plate with no box is drawn at the ratio the old code used.
    """
    dead = [
        f"{style.name}/{key}" for style, key, _box in _bird_boxes() if not (style / key).exists()
    ]
    assert not dead, "bird boxes keyed to artwork that is not there:\n" + "\n".join(dead)


def test_every_shipped_bird_has_a_box():
    """A plate with no box draws as its whole picture.

    That is right for a bird cut tight and wrong for the third of them carrying
    a second bird or a wash of ground, and the two are indistinguishable once
    drawn - a ratio of 1.0 looks the same whether someone judged it or nobody
    looked. Perches are not in this; nothing sizes them by mass.
    """
    missing = []
    for style in sorted(path for path in IMAGES.iterdir() if path.is_dir()):
        path = style / GEOMETRY
        listed = json.loads(path.read_text()) if path.exists() else {}
        for plate in _artwork(style / BIRDS):
            key = plate.relative_to(style).as_posix()
            if key not in listed:
                missing.append(f"{style.name}/{key}")
    assert not missing, "shipped birds with no box in geometry.json:\n" + "\n".join(missing)


def test_every_bird_box_is_well_formed():
    """Four coordinates in 0..1, left of right and above bottom.

    `sizes._box` drops an entry it cannot read, so a bad box never reaches the
    render - the plate just falls back to the ratio the old code used. That makes
    it silent, which is why it is caught here instead: a box nobody can see being
    ignored is a bird quietly drawn at the wrong size for as long as it takes to
    notice.
    """
    malformed = []
    for style, key, entry in _bird_boxes():
        box = entry.get("box") if isinstance(entry, dict) else None
        cut = entry.get("cut") if isinstance(entry, dict) else None
        if not isinstance(box, list) or len(box) != 4 or not isinstance(cut, list) or len(cut) != 2:
            malformed.append(f"{style.name}/{key}: {entry}")
            continue
        if not all(isinstance(value, (int, float)) for value in [*box, *cut]):
            malformed.append(f"{style.name}/{key}: {entry}")
            continue
        x0, y0, x1, y1 = box
        if not all(0.0 <= value <= 1.0 for value in box) or x0 >= x1 or y0 >= y1:
            malformed.append(f"{style.name}/{key}: {entry}")
    assert not malformed, (
        "bird boxes that are not four ordered coordinates plus a cut:\n" + "\n".join(malformed)
    )


def test_every_bird_box_was_drawn_on_the_plate_it_is_filed_under(library):
    """The recorded cut is the size of the plate as it is now.

    `sizes.span_ratio` ignores a box whose cut has moved, which keeps a stale box
    from mis-scaling a bird and also keeps it from ever being noticed: the plate
    draws at 1.0, smaller than it was boxed to, and nothing says so. `forget_box`
    covers a plate re-added through `add_bird`; this covers every other route -
    a plate retouched by hand, a bulk re-cut, a box merged in beside a newer file.
    A missing plate or a malformed entry is for the tests above to report.
    """
    stale = []
    for style, key, entry in _bird_boxes():
        cut = entry.get("cut") if isinstance(entry, dict) else None
        plate = library.get(style / key)
        if plate is None or not isinstance(cut, list) or len(cut) != 2:
            continue
        if tuple(cut) != plate.size:
            stale.append(f"{style.name}/{key}: boxed at {tuple(cut)}, plate is {plate.size}")
    assert not stale, "bird boxes drawn on a crop that has since moved:\n" + "\n".join(stale)


def test_every_artwork_image_has_attribution():
    missing = []
    for style in sorted(path for path in IMAGES.iterdir() if path.is_dir()):
        path = style / MANIFEST
        listed = json.loads(path.read_text()) if path.exists() else {}
        for plate in _artwork(style):
            key = plate.relative_to(style).as_posix()
            entry = listed.get(key)
            source = entry.get("source") if isinstance(entry, dict) else None
            if not isinstance(source, str) or not source.strip():
                missing.append(f"{style.name}/{key}")
    assert not missing, "artwork images without attribution:\n" + "\n".join(missing)


def test_every_manifest_source_is_named_in_attribution():
    """A source key has to resolve to terms someone wrote down.

    `source_of` hands the admin page the manifest's key and nothing more, so a
    key with no ATTRIBUTION.md entry ships artwork whose licence is recorded
    nowhere. Entries name their key as inline code (``Manifest key: `gould` ``),
    since the prose heading is for humans and does not match the key by rule.
    """
    orphans = []
    for style in sorted(path for path in IMAGES.iterdir() if path.is_dir()):
        path = style / MANIFEST
        if not path.exists():
            continue
        credits = style / ATTRIBUTION
        text = credits.read_text() if credits.exists() else ""
        named = set(re.findall(r"`([^`]+)`", text))
        for entry in json.loads(path.read_text()).values():
            source = entry.get("source") if isinstance(entry, dict) else None
            if isinstance(source, str) and source.strip() and source not in named:
                orphans.append(f"{style.name}: {source}")
    assert not orphans, "manifest sources with no ATTRIBUTION.md entry naming them:\n" + "\n".join(
        sorted(set(orphans))
    )
