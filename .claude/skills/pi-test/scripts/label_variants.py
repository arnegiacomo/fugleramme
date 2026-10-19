"""A text-only panel page comparing label rasterisation variants, for the glass.

One row per vendored font and variant: the label at the 13.3" medium size (38 px)
on the left and the small size (29 px) on the right. The variants draw the text
themselves, so the page is the same whichever checkout runs it:

    L>110        antialiased "L" raster cut to black at alpha 110
    mode 1       drawn into a mode "1" image, FreeType's mono hinting target
    w600 ...     the variable Weight axis at 600 instead of 400, then as above

Static fonts (Gentium) have no weight rows. Run on the Pi, in the checkout, so its
own FreeType draws the glyphs, then hand the PNG to push_page.py:

    uv run python label_variants.py out.png
"""

import sys
from typing import Any, cast

from PIL import Image, ImageDraw, ImageFont, features

from fugleramme.render import fonts
from fugleramme.render.dither import dither
from fugleramme.render.paper import PANEL_PAPER

LABEL = "Ficedula hypoleuca (Trauerschnäpper)"  # the label photographed in discussion #76
SIZES = (38, 29)  # 13.3" medium and small, from fonts.LABEL_SIZES
KEYS = ("gentium", "garamond", "playfair", "alegreya", "bitter")
CUTOFF = 110  # the threshold the panel used before the mode "1" change
PITCH = 60
TOP, CAPTION_X, COL_X = 36, 40, (330, 1070)


def load(key: str, px: int, weight: int) -> ImageFont.FreeTypeFont:
    font = fonts.load(key, px)  # pins Weight to 400
    if weight == 400:
        return font
    axes = cast(list[dict[str, Any]], font.get_variation_axes())  # OSError if static
    values = []
    for axis in axes:
        name = axis["name"]
        name = name.decode() if isinstance(name, bytes) else name
        want = weight if name == "Weight" else axis["default"]
        values.append(max(axis["minimum"], min(axis["maximum"], want)))
    font.set_variation_by_axes(values)
    return font


def mask(font: ImageFont.FreeTypeFont, text: str, mode: str) -> Image.Image:
    x0, y0, x1, y1 = ImageDraw.Draw(Image.new(mode, (1, 1))).textbbox((0, 0), text, font=font)
    m = Image.new(mode, (int(x1 - x0) + 2, int(y1 - y0) + 2), 0)
    ImageDraw.Draw(m).text((1 - x0, 1 - y0), text, font=font, fill=255)
    if mode == "L":
        return m.point(lambda v: 255 if v > CUTOFF else 0)
    return m.convert("L")


def variants(key: str):
    yield "L>110", 400, "L"
    yield "mode 1", 400, "1"
    try:
        fonts.load(key, 12).get_variation_axes()
    except OSError:
        return
    yield "w600 L>110", 600, "L"
    yield "w600 mode 1", 600, "1"


page = Image.new("RGB", (1600, 1200), PANEL_PAPER)
caption_font = fonts.load("gentium", 18)
y = TOP
for key in KEYS:
    for name, weight, mode in variants(key):
        page.paste((0, 0, 0), (CAPTION_X, y + 14), mask(caption_font, f"{key} · {name}", "1"))
        for px, x in zip(SIZES, COL_X, strict=True):
            page.paste((0, 0, 0), (x, y), mask(load(key, px, weight), LABEL, mode))
        y += PITCH
versions = f"Pillow {Image.__version__}, FreeType {features.version('freetype2')}"
page.paste((0, 0, 0), (CAPTION_X, 1200 - 30), mask(caption_font, versions, "1"))
out = dither(page)
out.save(sys.argv[1])
print("wrote", sys.argv[1], out.mode, out.size, "rows", (y - TOP) // PITCH)
