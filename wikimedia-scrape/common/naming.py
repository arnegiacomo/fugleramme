"""Turn free-text names into `genus-species` slugs and assign the numeric
variant suffixes (`-2`, `-3`, ...) that let the frame keep several plates of
the same species.
"""
import re

# Tokens that appear between/around the two Latin words but are not part of the
# binomial (common-name fragments, sex/age markers, authorities).
JUNK = {"now", "bird", "owl", "l", "lin", "male", "female", "and", "young"}


def to_binomial(cand):
    """Best-effort `'genus species'` from a messy candidate string, or None."""
    cand = re.sub(r"[\(\[][^\)\]]*[\)\]]", " ", cand)   # drop subgenus groups
    cand = cand.replace(".", " ")
    toks = [t for t in re.findall(r"[A-Za-z]+", cand) if t.lower() not in JUNK]
    if len(toks) < 2:
        return None
    g, s = toks[0].lower(), toks[1].lower()
    if len(g) < 3 or len(s) < 3:
        return None
    return f"{g} {s}"


def slug(name):
    return re.sub(r"[^a-z]+", "-", name.lower()).strip("-")


class Variants:
    """Assign `<slug>.ext`, `<slug>-2.ext`, ... as duplicates are seen."""

    def __init__(self):
        self._counts = {}

    def assign(self, name, title):
        s = slug(name)
        self._counts[s] = self._counts.get(s, 0) + 1
        base = s if self._counts[s] == 1 else f"{s}-{self._counts[s]}"
        ext = "png" if title.lower().endswith(".png") else "jpg"
        return f"{base}.{ext}"
