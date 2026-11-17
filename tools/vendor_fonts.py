"""Fetch the Noto faces a label falls back to, into assets/fonts/noto/.

    uv run python tools/vendor_fonts.py

Every face comes from the Noto project at a pinned commit. Noto Sans CJK is
16 MB whole, so it is cut down to the characters it can ever be asked for: the
Chinese, Japanese and Korean names in BirdNET v2.4's label files and in
BirdWeather's names for every bird, the dates babel writes in those languages,
and printable ASCII.

It also cuts Cormorant Garamond down to the title of the admin and the Wi-Fi
portal, from the face already under assets/fonts/.
"""

from __future__ import annotations

import io
import json
import string
import urllib.request
from datetime import UTC, datetime

from fontTools import subset
from fontTools.ttLib import TTFont

from fugleramme.birdweather import translations
from fugleramme.languages import NONE, Namer
from fugleramme.render.fonts import FONTS, FONTS_DIR, TITLE_CUT
from fugleramme.web.portal import TITLE

NOTO = "https://raw.githubusercontent.com/notofonts/notofonts.github.io/51a53382c7fca5180dd6030d79a4464c1a2730c8/fonts"
CJK = "https://raw.githubusercontent.com/notofonts/noto-cjk/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans"
LABELS = "https://raw.githubusercontent.com/birdnet-team/BirdNET-Analyzer/v2.4.0/birdnet_analyzer/labels/V2.4/BirdNET_GLOBAL_6K_V2.4_Labels_{}.txt"
BIRDWEATHER = "https://app.birdweather.com/graphql"
SPECIES = """
query ($ids: [ID!]!, $first: Int) {
  allSpecies(ids: $ids, first: $first) {
    nodes { classification translations { locale commonName } }
  }
}
"""
BATCH = 500  # allSpecies answers at most this many a call
# Empty batches in a row that end the sweep: ids 18001-19000 hold no species, and
# the ones after them do.
GAP = 5

# file -> the notofonts repo whose OFL.txt covers it. The "full" builds carry the
# Latin digits and punctuation that dates mix in.
FACES = {
    "NotoNaskhArabic-Regular.ttf": "arabic",
    "NotoSansHebrew-Regular.ttf": "hebrew",
    "NotoSerifThai-Regular.ttf": "thai",
    "NotoSerifMalayalam-Regular.ttf": "malayalam",
}
CJK_FACE = "NotoSansCJKsc-Regular.otf"
CJK_LOCALES = ("zh", "ja", "ko")

OUT = FONTS_DIR / "noto"


def fetch(url: str | urllib.request.Request) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def label_text(locale: str) -> str:
    """Every common name in BirdNET v2.4's labels for `locale`."""
    lines = fetch(LABELS.format(locale)).decode().splitlines()
    return "".join(line.partition("_")[2] for line in lines)


def birdweather_species(ids: range) -> list[dict]:
    body = json.dumps(
        {"query": SPECIES, "variables": {"ids": [str(i) for i in ids], "first": BATCH}}
    )
    request = urllib.request.Request(
        BIRDWEATHER,
        data=body.encode(),
        headers={"Content-Type": "application/json", "User-Agent": "fugleramme"},
    )
    return json.loads(fetch(request))["data"]["allSpecies"]["nodes"]


def birdweather_text() -> str:
    """Every bird's name BirdWeather has in `CJK_LOCALES`. There is no list of
    its species, so their ids are asked in batches from 1 until `GAP` batches in
    a row come back empty. Only birds: a BirdWeather source drops every other
    classification before it asks for names."""
    names: list[str] = []
    start, misses = 1, 0
    while misses < GAP:
        nodes = birdweather_species(range(start, start + BATCH))
        start, misses = start + BATCH, 0 if nodes else misses + 1
        names += [
            name
            for node in nodes
            if node["classification"] == "avian"
            for code, name in translations(node).items()
            if code in CJK_LOCALES
        ]
    return "".join(names)


def date_text(locale: str) -> str:
    """Every date the frame can write in `locale`: each month, and each hour of a
    day for the clock's AM/PM words."""
    namer = Namer(locale, NONE, {}, ())
    days = [
        datetime(2026, month, 28, hour, tzinfo=UTC) for month in range(1, 13) for hour in range(24)
    ]
    return "".join(namer.date(day) + namer.moment(day) for day in days)


def cjk_subset(font: bytes) -> TTFont:
    labels = "".join(label_text(code) + date_text(code) for code in CJK_LOCALES)
    text = labels + birdweather_text()
    options = subset.Options()
    options.layout_features = ["*"]
    options.notdef_outline = True  # an unknown character still draws a box
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=text + string.printable)
    subset_font = TTFont(io.BytesIO(font), recalcTimestamp=False)  # reruns write the same bytes
    subsetter.subset(subset_font)
    return subset_font


def title_cut() -> TTFont:
    subsetter = subset.Subsetter()
    subsetter.populate(text=TITLE)
    cut = TTFont(FONTS_DIR / FONTS["cormorant"][1], recalcTimestamp=False)
    subsetter.subset(cut)
    return cut


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    licences = []
    for name, repo in FACES.items():
        family = name.split("-")[0]
        (OUT / name).write_bytes(fetch(f"{NOTO}/{family}/full/ttf/{name}"))
        licences.append(
            (name, fetch(f"https://raw.githubusercontent.com/notofonts/{repo}/main/OFL.txt"))
        )
    cjk_subset(fetch(f"{CJK}/OTF/SimplifiedChinese/{CJK_FACE}")).save(OUT / CJK_FACE)
    licences.append((CJK_FACE, fetch(f"{CJK}/LICENSE")))
    title_cut().save(FONTS_DIR / TITLE_CUT)
    # One file for the folder, each upstream's own text under the faces it covers.
    (OUT / "OFL.txt").write_text(
        "\n\n".join(f"===== {name}\n\n{text.decode().strip()}" for name, text in licences) + "\n"
    )
    for file in sorted(OUT.iterdir()):
        print(f"{file.stat().st_size / 1024:8.0f} KB  {file.name}")


if __name__ == "__main__":
    main()
