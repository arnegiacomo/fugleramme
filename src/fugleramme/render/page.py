"""Page furniture shared by every display mode.

Getting an asset and a piece of text onto paper is the same job whether the page
holds forty birds or one, so the collage and the plate draw from here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import fonts
from .paper import TARGET_PAPER, paper_texture, process_sprite

INK = (30, 30, 30)
PANEL_INK = (0, 0, 0)  # exact palette black: the dither leaves it alone

MIN_LABEL_PX = 11
_CUTOFF = 110  # alpha threshold when flattening text for the panel
_LINE_SPACING = 0.1  # extra leading between a label's two lines, em
_PERCH_FILL = 0.7  # of the page's short side


def label_px(width: int, height: int, size_key: str) -> int:
    _name, scale = fonts.LABEL_SIZES.get(size_key, fonts.LABEL_SIZES[fonts.DEFAULT_LABEL_SIZE])
    return max(MIN_LABEL_PX, round(min(width, height) * scale))


def trim(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    bbox = img.getchannel("A").getbbox()  # trim by alpha, not by RGB
    return img.crop(bbox) if bbox else img


def fit(img: Image.Image, box: tuple[int, int]) -> Image.Image:
    """Scale to fit inside `box`, keeping the aspect."""
    scale = min(box[0] / img.width, box[1] / img.height)
    return img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
        Image.Resampling.LANCZOS,
    )


def text_mask(text: str, font: ImageFont.FreeTypeFont, flat: bool) -> Image.Image:
    """Text as an "L" alpha mask, +1px so the italic's overhang is not shaved.
    Newlines stack centred (a second language) on the text layout's own
    baselines - separately trimmed masks would sit unevenly. Flat drops the
    antialiasing, which would otherwise dither into colour speckle."""
    spacing = round(font.size * _LINE_SPACING)
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    x0, y0, x1, y1 = measure.multiline_textbbox(
        (0, 0), text, font=font, spacing=spacing, align="center"
    )
    # Ceil: a multi-line bbox is fractional, and a short box shaves the text.
    mask = Image.new("L", (math.ceil(x1 - x0) + 2, math.ceil(y1 - y0) + 2), 0)
    ImageDraw.Draw(mask).multiline_text(
        (1 - x0, 1 - y0), text, font=font, fill=255, spacing=spacing, align="center"
    )
    return mask.point(lambda v: 255 if v > _CUTOFF else 0) if flat else mask


def stamp(canvas: Image.Image, mask: Image.Image, at: tuple[int, int], textured: bool) -> None:
    canvas.paste(Image.new("RGB", mask.size, INK if textured else PANEL_INK), at, mask)


def day_ordinal() -> int:
    """Today as a number that turns over daily.

    The panel and the kiosk each render their own copy, so a day-varying choice
    rolled at render time would leave them showing different pages - and the
    panel, which only re-renders when its key changes, would then hold its one
    roll for as long as the frame stayed quiet. Deriving it from the date makes
    both agree by construction and gives a silent frame something that moves.
    """
    return date.today().toordinal()


def draw_perch(
    canvas: Image.Image, perches: Sequence[Path], day: int, textured: bool = True
) -> None:
    """Nothing to show: a single empty perch, centered on the paper page."""
    if not perches:
        return
    perch = trim(perches[day % len(perches)])
    if (day // len(perches)) % 2:  # mirrored on the second lap, so it cycles twice as far
        perch = perch.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    target = int(min(canvas.width, canvas.height) * _PERCH_FILL)
    proc = process_sprite(fit(perch, (target, target)), textured=textured)
    canvas.paste(proc, ((canvas.width - proc.width) // 2, (canvas.height - proc.height) // 2), proc)


def blank(resolution: tuple[int, int], textured: bool) -> Image.Image:
    """An empty sheet: grained for the web, flat for the panel, whose dither
    would otherwise turn the grain into noise."""
    width, height = resolution
    if textured:
        return paper_texture(width, height)
    return Image.new("RGB", (width, height), TARGET_PAPER)
