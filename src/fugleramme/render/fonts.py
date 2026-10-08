"""Vendored typefaces for the species names on the page.

Seven italics - scientific names are conventionally italic - spanning old-style,
Didone, calligraphic, transitional and slab, picked for how they survive the
panel's six colors: at label size a hairline thin speckles or drops out
entirely. Cormorant Garamond is the exception, an engraved display face for the
plate modes, where the name is set large enough to carry its hairlines; on a
crowded collage it is the first to break up. All SIL OFL, vendored under
assets/fonts/ with their licences.

A label line its face cannot set takes the first of `FALLBACKS` that can:
Gentium for the Greek and Cyrillic some italics miss, a Noto face for the
scripts none has.
"""

from __future__ import annotations

from functools import cache
from typing import Any, NamedTuple, cast

from fontTools.ttLib import TTFont
from PIL import ImageFont, features

from ..config import REPO_ROOT

FONTS_DIR = REPO_ROOT / "assets" / "fonts"

# key -> (admin label, file under FONTS_DIR)
FONTS: dict[str, tuple[str, str]] = {
    "gentium": ("Gentium Book Plus", "gentiumbookplus/GentiumBookPlus-Italic.ttf"),
    "garamond": ("EB Garamond", "ebgaramond/EBGaramond-Italic.ttf"),
    "cormorant": ("Cormorant Garamond", "cormorantgaramond/CormorantGaramond-Italic.ttf"),
    "baskerville": ("Libre Baskerville", "librebaskerville/LibreBaskerville-Italic.ttf"),
    "playfair": ("Playfair Display", "playfairdisplay/PlayfairDisplay-Italic.ttf"),
    "alegreya": ("Alegreya", "alegreya/Alegreya-Italic.ttf"),
    "bitter": ("Bitter", "bitter/Bitter-Italic.ttf"),
}

DEFAULT_FONT = "gentium"

# Fraction of the page's short side, so a name holds its proportion at any resolution.
LABEL_SIZES: dict[str, tuple[str, float]] = {
    "small": ("Small", 0.024),
    "medium": ("Medium", 0.032),
    "large": ("Large", 0.042),
    "xlarge": ("Extra large", 0.055),
}

DEFAULT_LABEL_SIZE = "medium"


class Fallback(NamedTuple):
    file: str  # under FONTS_DIR
    ratio: float  # its size against the label's, so it reads as large
    shaped: bool  # unreadable without raqm: joined, reordered or right-to-left


# Gentium's x-height is small: at 1.15 it stands level with Baskerville, Bitter
# and Playfair, which fall back to it. Noto Sans CJK is a subset (tools/vendor_fonts.py).
FALLBACKS = (
    Fallback("gentiumbookplus/GentiumBookPlus-Italic.ttf", 1.15, False),
    Fallback("noto/NotoSansCJKsc-Regular.otf", 0.88, False),
    Fallback("noto/NotoSerifThai-Regular.ttf", 1.0, False),
    Fallback("noto/NotoNaskhArabic-Regular.ttf", 1.0, True),
    Fallback("noto/NotoSansHebrew-Regular.ttf", 1.0, True),
    Fallback("noto/NotoSerifMalayalam-Regular.ttf", 1.0, True),
)


def load(key: str, size: int) -> ImageFont.FreeTypeFont:
    """Open a label font at a pixel size. Uncached on purpose: the render loop and
    the HTTP server draw on separate threads, and a FreeType face is not shareable.

    Basic layout, which Pillow uses without libfribidi: a Pi that gains it for the
    fallbacks must not re-kern every Latin name."""
    _name, filename = FONTS.get(key, FONTS[DEFAULT_FONT])
    font = ImageFont.truetype(str(FONTS_DIR / filename), size, layout_engine=ImageFont.Layout.BASIC)
    _pin_weight(font)
    return font


@cache
def _cmap(path: str) -> frozenset[int]:
    with TTFont(path, lazy=True) as font:
        return frozenset(font.getBestCmap())


def _covers(path: str, line: str) -> bool:
    cmap = _cmap(path)
    return all(ord(c) in cmap for c in line)


def _fallback(line: str) -> Fallback | None:
    raqm = features.check("raqm")
    return next(
        (f for f in FALLBACKS if (raqm or not f.shaped) and _covers(str(FONTS_DIR / f.file), line)),
        None,
    )


def face(line: str, font: ImageFont.FreeTypeFont) -> ImageFont.FreeTypeFont:
    """The face one label line is set in: `font` if it has every character, else
    the first usable fallback that does. Per line, never per character: a line
    split across faces loses its bidi ordering."""
    fallback = None if _covers(str(font.path), line) else _fallback(line)
    if fallback is None:
        return font
    return ImageFont.truetype(
        str(FONTS_DIR / fallback.file), max(1, round(font.size * fallback.ratio))
    )


def settable(line: str, font_key: str) -> bool:
    """Whether a label line has a face here, in `font_key` or a fallback."""
    _name, filename = FONTS.get(font_key, FONTS[DEFAULT_FONT])
    return _covers(str(FONTS_DIR / filename), line) or _fallback(line) is not None


def needs_shaping(line: str) -> bool:
    """Whether a line waits on raqm: no fallback sets it now, and a shaped one
    would. Naskh has Latin too, so a shaped face covering it is not enough."""
    return _fallback(line) is None and any(
        f.shaped and _covers(str(FONTS_DIR / f.file), line) for f in FALLBACKS
    )


def resized(font: ImageFont.FreeTypeFont, size: int) -> ImageFont.FreeTypeFont:
    """The same face at another size, its weight pinned as `load` pins it."""
    sized = font.font_variant(size=size)
    _pin_weight(sized)
    return sized


def _pin_weight(font: ImageFont.FreeTypeFont) -> None:
    """Pillow instantiates a variable font at each axis's minimum, which would
    draw Bitter as Thin."""
    try:
        # Pillow's Axis marks every field optional; FreeType fills them.
        axes = cast(list[dict[str, Any]], font.get_variation_axes())
    except OSError:
        return  # static font
    values = []
    for axis in axes:
        name = axis["name"]
        want = (
            400
            if (name.decode() if isinstance(name, bytes) else name) == "Weight"
            else axis["default"]
        )
        values.append(max(axis["minimum"], min(axis["maximum"], want)))
    font.set_variation_by_axes(values)
