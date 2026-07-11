"""Source: *The Birds of Europe* (John Gould, 5 volumes).

Most files are named by English common name ("GouldBirdsEuropeIBarn Owl.jpg"),
but most plates carry a `<Genus species> (illustrations)` member category on
Commons - a far cleaner signal than the filename. `plan` resolves each file to
a binomial by, in order: that category; a Latin binomial embedded in the
filename ("Asio otus by John Gould.jpg"); or COMMON_NAMES, for the ~35 plates
that carry only a volume category and a bare English name.
"""
import re

from common.naming import to_binomial

NAME = "gould"

# Plates with no species category, keyed by their squashed lowercase common
# name. Modern eBird / BirdNET v2.4 binomials, so a curated cut-out drops
# straight into assets/birds/. Gould's "Pelican" and "Shag" are omitted: no
# BirdNET v2.4 label, so the frame can never surface them.
COMMON_NAMES = {
    "hawkowl": "surnia ulula",
    "bullfinch": "pyrrhula pyrrhula",
    "chaffinch": "fringilla coelebs",
    "chough": "pyrrhocorax pyrrhocorax",
    "goldfinch": "carduelis carduelis",
    "hoopoe": "upupa epops",
    "raven": "corvus corax",
    "rook": "corvus frugilegus",
    "siskin": "spinus spinus",
    "starling": "sturnus vulgaris",
    "twite": "linaria flavirostris",
    "wryneck": "jynx torquilla",
    "avocet": "recurvirostra avosetta",
    "capercailzie": "tetrao urogallus",
    "coot": "fulica atra",
    "dottrell": "charadrius morinellus",
    "dunlin": "calidris alpina",
    "greenshank": "tringa nebularia",
    "knot": "calidris canutus",
    "lapwing": "vanellus vanellus",
    "marshsandpiper": "tringa stagnatilis",
    "quail": "coturnix coturnix",
    "redshank": "tringa totanus",
    "ringdottrell": "charadrius hiaticula",
    "ruff": "calidris pugnax",
    "sanderling": "calidris alba",
    "spoonbill": "platalea leucorodia",
    "turnstone": "arenaria interpres",
    "whimbrel": "numenius phaeopus",
    "woodcock": "scolopax rusticola",
    "gadwall": "mareca strepera",
    "goldeneye": "bucephala clangula",
    "goosander": "mergus merganser",
    "smew": "mergellus albellus",
    "widgeon": "mareca penelope",
}
CATEGORIES = [
    "Category:The Birds of Europe (Gould) Volume 1",
    "Category:The Birds of Europe (Gould) Volume 2",
    "Category:The Birds of Europe (Gould) Volume 3",
    "Category:The Birds of Europe (Gould) Volume 4",
    "Category:The Birds of Europe (Gould) Volume 5",
]

ATTRIBUTION = """Images derived from *The Birds of Europe* by John Gould
(1832-1837), via the Wikimedia Commons categories "The Birds of Europe (Gould)
Volume 1-5". Public domain (PD-old-70-expired)."""

# "Category:Genus species (illustrations)" (also matches a trailing subspecies).
_SPECIES_CAT = re.compile(r"^Category:([A-Z][a-z]+) ([a-z]+)(?: [a-z]+)? \(illustrations\)$")


def _from_categories(cats):
    for c in cats:
        m = _SPECIES_CAT.match(c)
        if m:
            return f"{m.group(1).lower()} {m.group(2)}"
    return None


# A bulk archive.org upload of the whole book: every page (plates and text)
# titled with only the book title and a numeric id, e.g. "The birds of Europe
# (1837) (14565247670).jpg". No species signal in title, category, or
# description, so to_binomial would mistake the book title's first two words
# ("The birds") for a binomial. Reject them so they resolve to None and drop.
_BOOK_TITLE = re.compile(r"^The birds of Europe \(\d{4}\)", re.I)


def _from_filename(title):
    n = re.sub(r"\.(jpg|jpeg|png)$", "", title.replace("File:", ""), flags=re.I)
    if _BOOK_TITLE.match(n):
        return None
    n = re.sub(r"\b(by John|John)?\s*Gould\b", "", n, flags=re.I)
    return to_binomial(n)


def _from_common_name(title):
    """Squash the 'GouldBirdsEurope<vol><CommonName>.jpg' tail to a lookup key."""
    n = re.sub(r"\.(jpg|jpeg|png)$", "", title.replace("File:", ""), flags=re.I)
    n = re.sub(r"^GouldBirdsEurope[IVX]+", "", n)
    return COMMON_NAMES.get(re.sub(r"[^a-z]", "", n.lower()))


def plan(info):
    out = []
    for t in sorted(info):
        name = (_from_categories(info[t]["categories"])
                or _from_filename(t) or _from_common_name(t))
        if name:
            out.append((name, t))
    return out
