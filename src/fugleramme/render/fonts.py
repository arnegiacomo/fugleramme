"""Vendored typefaces for the species names on the page.

Seven italics - scientific names are conventionally italic - spanning old-style,
Didone, calligraphic, transitional and slab, picked for how they survive the
panel's six colors: at label size a hairline thin speckles or drops out
entirely. Cormorant Garamond is the exception, an engraved display face for the
plate modes, where the name is set large enough to carry its hairlines; on a
crowded collage it is the first to break up. All SIL OFL, vendored under
assets/fonts/ with their licences.
"""

from __future__ import annotations

from typing import Any, cast

from PIL import ImageFont

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


def load(key: str, size: int) -> ImageFont.FreeTypeFont:
    """Open a label font at a pixel size. Uncached on purpose: the render loop and
    the HTTP server draw on separate threads, and a FreeType face is not shareable."""
    _name, filename = FONTS.get(key, FONTS[DEFAULT_FONT])
    font = ImageFont.truetype(str(FONTS_DIR / filename), size)
    _pin_weight(font)
    return font


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
