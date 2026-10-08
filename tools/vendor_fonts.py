"""Fetch the Noto faces a label falls back to, into assets/fonts/noto/.

    uv run python tools/vendor_fonts.py

Every face comes from the Noto project at a pinned commit. Noto Sans CJK is
16 MB whole, so it is cut down to the characters it can ever be asked for: the
Chinese, Japanese and Korean names in BirdNET v2.4's label files, the dates
babel writes in those languages, and printable ASCII.
"""

from __future__ import annotations

import io
import string
import urllib.request
from datetime import UTC, datetime

from fontTools import subset
from fontTools.ttLib import TTFont

from fugleramme.languages import NONE, Namer
from fugleramme.render.fonts import FONTS_DIR

NOTO = "https://raw.githubusercontent.com/notofonts/notofonts.github.io/51a53382c7fca5180dd6030d79a4464c1a2730c8/fonts"
CJK = "https://raw.githubusercontent.com/notofonts/noto-cjk/f8d157532fbfaeda587e826d4cd5b21a49186f7c/Sans"
LABELS = "https://raw.githubusercontent.com/birdnet-team/BirdNET-Analyzer/v2.4.0/birdnet_analyzer/labels/V2.4/BirdNET_GLOBAL_6K_V2.4_Labels_{}.txt"

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


def fetch(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=60) as response:
        return response.read()


def label_text(locale: str) -> str:
    """Every common name in BirdNET v2.4's labels for `locale`."""
    lines = fetch(LABELS.format(locale)).decode().splitlines()
    return "".join(line.partition("_")[2] for line in lines)


def date_text(locale: str) -> str:
    """Every date the frame can write in `locale`: each month, and each hour of a
    day for the clock's AM/PM words."""
    namer = Namer(locale, NONE, {}, ())
    days = [
        datetime(2026, month, 28, hour, tzinfo=UTC) for month in range(1, 13) for hour in range(24)
    ]
    return "".join(namer.date(day) + namer.moment(day) for day in days)


def cjk_subset(font: bytes) -> TTFont:
    text = "".join(label_text(code) + date_text(code) for code in CJK_LOCALES)
    options = subset.Options()
    options.layout_features = ["*"]
    options.notdef_outline = True  # an unknown character still draws a box
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=text + string.printable)
    subset_font = TTFont(io.BytesIO(font), recalcTimestamp=False)  # reruns write the same bytes
    subsetter.subset(subset_font)
    return subset_font


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
    # One file for the folder, each upstream's own text under the faces it covers.
    (OUT / "OFL.txt").write_text(
        "\n\n".join(f"===== {name}\n\n{text.decode().strip()}" for name, text in licences) + "\n"
    )
    for file in sorted(OUT.iterdir()):
        print(f"{file.stat().st_size / 1024:8.0f} KB  {file.name}")


if __name__ == "__main__":
    main()
