"""Which detections are birds.

A station classifies more than birds, and can run a bat or multi-taxa model beside
the one that hears them. Two halves, because there are two ways to not be a bird:

The v2.4 label set is an allowlist, and that is what catches a bat whatever its
genus - artwork filenames are pinned to those labels, so a name outside the set
could never be drawn anyway.

`NON_BIRD_GENERA` covers the 101 labels inside v2.4 that are noise classes, frogs,
crickets, squirrels and other mammals. It was read off eBird's own taxonomy, which
prefixes a non-bird taxon's species code with `t-`, and cross-checked against
BirdNET-Go's genus map, which disagreed nowhere.

An unreadable label file fails open: the odd frog on the glass beats a blank one.
"""

from __future__ import annotations

import logging
from functools import cache

from .config import REPO_ROOT
from .names import normalize

log = logging.getLogger(__name__)

LABELS = REPO_ROOT / "assets" / "birdnet_labels_v2.4.txt"

# Both spellings where a species has been reclassified, since `normalize` hands
# over the current one: the label file says "Orocharis saltator", the detector
# says "Hapithus saltator". "human" and "power" are two-word noise labels
# ("Human vocal", "Power tools"), which read as a genus like any other.
_GENERA = """
dog engine environmental fireworks gun human noise power siren
acris anaxyrus dryophytes eleutherodactylus gastrophryne hyliola incilius
lithobates pseudacris scaphiopus spea
allonemobius amblycorypha anaxipha apis atlanticus conocephalus cyrtoxipha
eunemobius gryllus hapithus microcentrum miogryllus neoconocephalus neonemobius
oecanthus orchelimum orocharis phyllopalpus pterophylla scudderia
alouatta canis odocoileus sciurus tamias tamiasciurus
"""

NON_BIRD_GENERA = frozenset(_GENERA.split())


@cache
def _labels() -> dict[str, str]:
    """Every v2.4 name as an artwork key, against the common name beside it in the
    file, so a reclassified species answers to the label's spelling and the
    detector's alike. Empty if the file cannot be read, which turns the allowlist
    off rather than emptying the page."""
    try:
        text = LABELS.read_text()
    except OSError as error:
        log.warning("No label list at %s (%s): only the genus check applies", LABELS, error)
        return {}
    rows = (line.split("_", 1) for line in text.splitlines() if line)
    return {normalize(row[0]): row[-1] if len(row) > 1 else "" for row in rows}


def common_of(scientific_name: str) -> str:
    """The label's own English common name, or "" for a name v2.4 never emitted.
    Needs no detector and no dictionary, unlike every other name here."""
    return _labels().get(normalize(scientific_name), "")


def is_bird(scientific_name: str) -> bool:
    key = normalize(scientific_name)
    known = _labels()
    if known and key not in known:
        return False  # another model's label: nothing here can draw it
    return key.partition("-")[0] not in NON_BIRD_GENERA
