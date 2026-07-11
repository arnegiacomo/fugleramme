"""Source: *Svenska Fåglar* (von Wright brothers).

The category holds two kinds of files:
  * "Bird illustration from Svenska Fåglar ... rawpixel ..." plates, whose
    species is taken from the API image description (in parentheses, or the
    leading text when there is no common name).
  * Other files whose species is already in the Commons filename.

`plan` emits ordered `(binomial, title)` pairs - illustration plates first (by
plate number), then the others (alphabetically) - so the shared variant
numbering is stable across runs.
"""
import html
import re

from common.naming import to_binomial

NAME = "vonwright"
CATEGORIES = ["Category:Svenska fåglar (von Wright)"]

ATTRIBUTION = """Images derived from *Svenska Fåglar* by the von Wright brothers
(Magnus 1805-1868, Wilhelm 1810-1887, Ferdinand 1822-1906), via the Wikimedia
Commons category "Svenska fåglar (von Wright)". Original artwork public domain;
340 rawpixel plates are CC BY-SA 4.0. Offered as CC BY-SA 4.0."""

# Heads (text before "illustrated by") that the generic parser gets wrong,
# mapped straight to their final binomial. Includes hybrids and plates where
# the Latin name sits outside the parentheses.
EXCEPTIONS = {
    'Strix aluco (Tawny owl)': 'strix aluco',
    'Sylvia curruca (Lesser whitethroat)': 'sylvia curruca',
    'Tringa Alpina (Dunlin)': 'tringa alpina',
    'Aegithalus caudatus (Long-tailed tit)': 'aegithalus caudatus',
    'Common Sandpiper Tringoides hypoleucus (now Actitis hypoleucos )': 'actitis hypoleucos',
    'Willow ptarmigan': 'lagopus lagopus',
    'Eider (CORACIAS SOMATERIA MOLLISSIMA)': 'somateria mollissima',
    'Hybrid between Black grouse and Willow ptarmigan (Lyrurus tetrix ♂ x lagopus lagopus ♀)': 'lyrurus tetrix x lagopus lagopus',
    'Hybrid between Black grouse and Willow ptarmigan (Yrurus tetrix x lagopus lagopus)': 'lyrurus tetrix x lagopus lagopus',
    'Hybrid between Western capercaillie and Willow ptarmigan (Tetrao urogallus x lagopus lagopus)': 'tetrao urogallus x lagopus lagopus',
    'Hybrid between black grouse and western capercaillie (Lyrurus tetrix ♂ x Tetrao urogallus ♀)': 'lyrurus tetrix x tetrao urogallus',
    'Hybrid between common house-martin and barn swallow (Chelidon rustica L.xHirundo urbica)': 'chelidon rustica x hirundo urbica',
    'lyrurus tetrix tetrastes bonasia': 'lyrurus tetrix x tetrastes bonasia',
}

# Source-typo fixes so the same species collapses to one slug.
TYPO = {
    'numenius arquatusf': 'numenius arquata',
    'pavoncella pugnaxr': 'pavoncella pugnax',
    'larus canu': 'larus canus',
    'lagopus lagoups': 'lagopus lagopus',
    'picoides tridactylu': 'picoides tridactylus',
    'turdus usicus': 'turdus musicus',
    'odiceps grisegena': 'podiceps grisegena',
    'emberiza carlandra': 'emberiza calandra',
    'nyroca fuligule': 'nyroca fuligula',
    'hypolais hipolais': 'hippolais hippolais',
}

_TAG = re.compile("<[^>]+>")


def _get_head(desc):
    """Description text up to (but not including) 'illustrated ...'."""
    txt = html.unescape(_TAG.sub(" ", desc))
    txt = re.sub(r"\s+", " ", txt).strip()
    return re.split(r"illustrated", txt, flags=re.I)[0].strip()


def _parse_illustration(head):
    if head in EXCEPTIONS:
        return EXCEPTIONS[head]
    h = re.sub(r"[0-9]*\s*[♀♂]", "", head)                       # strip sex markers
    m = re.search(r"\(([^()]*(?:\([^()]*\)[^()]*)*)\)", h)        # first (nested) paren
    binom = to_binomial(m.group(1)) if m else None
    if binom is None:
        binom = to_binomial(h)                                   # fall back to whole head
    return TYPO.get(binom, binom) if binom else None


def _parse_other(title):
    """Species from a plain Commons filename such as 'Falco aesalon male.jpg'."""
    n = re.sub(r"\.(jpg|jpeg|png)$", "", title.replace("File:", ""), flags=re.I)
    n = re.sub(r"^Magnus von Wright\s*-\s*", "", n)
    m = re.search(r"Svenska Fåglar\s*\(([^)]*)\)", n)
    if m:
        n = m.group(1)
    n = n.split(",")[0]                                          # first species before comma
    drop = {"f", "m", "female", "male", "ung", "von", "wright", "magnus"}
    toks = [t for t in re.findall(r"[A-Za-zåäöÅÄÖ]+", n)
            if t.lower() not in drop and len(t) >= 3]
    return f"{toks[0].lower()} {toks[1].lower()}" if len(toks) >= 2 else None


def _plate_number(title):
    m = re.search(r"(\d+)\.jpg", title)
    return int(m.group(1)) if m else 0


def plan(info):
    titles = list(info)
    plates = sorted((t for t in titles if t.startswith("File:Bird illustration")),
                    key=_plate_number)
    others = sorted(t for t in titles if not t.startswith("File:Bird illustration"))
    out = []
    for t in plates:
        name = _parse_illustration(_get_head(info[t]["desc"]))
        if name:
            out.append((name, t))
    for t in others:
        name = _parse_other(t)
        if name:
            out.append((name, t))
    return out
