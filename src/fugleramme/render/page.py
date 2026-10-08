"""Page furniture shared by every display mode.

Getting an asset and a piece of text onto paper is the same job whether the page
holds forty birds or one, so the collage and the plate draw from here.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import NamedTuple

from PIL import Image, ImageDraw, ImageFont

from . import fonts
from .paper import PAD, PANEL_PAPER, paper_texture, process_sprite

INK = (30, 30, 30)
PANEL_INK = (0, 0, 0)  # exact palette black: the dither leaves it alone

MIN_LABEL_PX = 11
_CUTOFF = 110  # alpha threshold when flattening text for the panel
_LINE_SPACING = 0.1  # extra leading between a label's two lines, em
_PERCH_FILL = 0.7  # of the page's short side
# Ends a label's first line for a bird new to the station. Drawn as the face's
# own asterisk, larger and centred on the capitals rather than raised.
NEW = "\u2605"
_MARK_SCALE = 1.5  # the asterisk, against the text's size
_MARK_GAP = 0.2  # text to asterisk, of the cap height


class Edges(NamedTuple):
    """Bare paper along each edge of the page as it hangs, fractions of the short side."""

    top: float
    right: float
    bottom: float
    left: float

    @classmethod
    def even(cls, margin: float) -> Edges:
        return cls(margin, margin, margin, margin)

    def window(self, size: tuple[int, int]) -> tuple[int, int, int, int]:
        """The box inside the edges, as (x0, y0, x1, y1)."""
        width, height = size
        short = min(size)
        return (
            round(short * self.left),
            round(short * self.top),
            width - round(short * self.right),
            height - round(short * self.bottom),
        )


NO_MARGIN = Edges(0, 0, 0, 0)


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


def _cap(font: ImageFont.FreeTypeFont) -> float:
    return -font.getbbox("H", anchor="ls")[1]


def _mark(font: ImageFont.FreeTypeFont) -> tuple[Image.Image, int]:
    """The face's asterisk at `_MARK_SCALE`, trimmed to its ink, and how far its
    middle sits past the end of the text."""
    mark = Image.new("L", (1, 1))
    big = fonts.resized(font, round(font.size * _MARK_SCALE))
    x0, y0, x1, y1 = ImageDraw.Draw(mark).textbbox((0, 0), "*", font=big)
    mark = Image.new("L", (math.ceil(x1 - x0) + 2, math.ceil(y1 - y0) + 2), 0)
    ImageDraw.Draw(mark).text((1 - x0, 1 - y0), "*", font=big, fill=255)
    ink = mark.crop(mark.getbbox())
    mark = Image.new("L", (ink.width + 2, ink.height + 2), 0)  # +1px, as the text has
    mark.paste(ink, (1, 1))
    return mark, round(_cap(font) * _MARK_GAP + mark.width / 2)


def _mark_corner(mark: Image.Image, offset: int, x: float, baseline: float, cap: float):
    """Where the mark goes for text ending at `x`: in line, centred on the caps."""
    return round(x + offset - mark.width / 2), round(baseline - cap / 2 - mark.height / 2)


def mark_room(font: ImageFont.FreeTypeFont) -> int:
    """How far past the end of its text a mark reaches."""
    mark, offset = _mark(font)
    return offset + math.ceil(mark.width / 2)


def draw_mark(mask: Image.Image, x: float, baseline: float, font: ImageFont.FreeTypeFont) -> None:
    """A newcomer's mark into `mask`, in line with text that ends at `x`."""
    mark, offset = _mark(font)
    mask.paste(255, _mark_corner(mark, offset, x, baseline, _cap(font)), mark)


def text_mask(text: str, font: ImageFont.FreeTypeFont, flat: bool) -> Image.Image:
    """Text as an "L" alpha mask, +1px so the italic's overhang is not shaved.
    Newlines stack centred (a second language) on the text layout's own
    baselines - separately trimmed masks would sit unevenly. Flat drops the
    antialiasing, which would otherwise dither into colour speckle. A first
    line ending in NEW gets its mark; whatever it reaches past the text on the
    right is matched on the left, so the name stays centred. A label with a line in a fallback face (`fonts.face`) is stacked by hand."""
    first, *rest = text.split("\n")
    marked = first.endswith(NEW)
    lines = [first.removesuffix(NEW), *rest]
    faces = [fonts.face(line, font) for line in lines]
    if all(face is font for face in faces):
        mask, origin = _multiline("\n".join(lines), font)
    else:
        mask, origin = _stacked(lines, faces, font)
    if marked:
        mask = _with_mark(mask, lines, faces, origin)
    return flatten(mask) if flat else mask


def _multiline(text: str, font: ImageFont.FreeTypeFont) -> tuple[Image.Image, tuple[float, float]]:
    """Lines in one face, and where the first line's ascender starts."""
    spacing = round(font.size * _LINE_SPACING)
    measure = ImageDraw.Draw(Image.new("L", (1, 1)))
    x0, y0, x1, y1 = measure.multiline_textbbox(
        (0, 0), text, font=font, spacing=spacing, align="center"
    )
    # Ceil: a multi-line bbox is fractional, and a short box shaves the text.
    mask = Image.new("L", (math.ceil(x1 - x0) + 2, math.ceil(y1 - y0) + 2), 0)
    origin = (1 - x0, 1 - y0)
    ImageDraw.Draw(mask).multiline_text(
        origin, text, font=font, fill=255, spacing=spacing, align="center"
    )
    return mask, origin


def _stacked(
    lines: list[str], faces: list[ImageFont.FreeTypeFont], font: ImageFont.FreeTypeFont
) -> tuple[Image.Image, tuple[float, float]]:
    """`_multiline` for lines in faces of their own: centred on the widest, and
    a line apart by Pillow's own multiline rule (the foot of an "A" plus the
    spacing) in the tallest of the faces, so a fallback keeps the Latin rhythm."""
    widths = [face.getlength(line) for face, line in zip(faces, lines, strict=True)]
    pitch = max(face.getbbox("A")[3] for face in faces) + round(font.size * _LINE_SPACING)
    spots = [((max(widths) - width) / 2, k * pitch) for k, width in enumerate(widths)]
    inks = [face.getbbox(line, anchor="la") for face, line in zip(faces, lines, strict=True)]
    boxes = [
        (x + left, y + top, x + right, y + bottom)
        for (x, y), (left, top, right, bottom) in zip(spots, inks, strict=True)
    ]
    x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x1, y1 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    mask = Image.new("L", (math.ceil(x1 - x0) + 2, math.ceil(y1 - y0) + 2), 0)
    origin = (1 - x0, 1 - y0)
    draw = ImageDraw.Draw(mask)
    for (x, y), face, line in zip(spots, faces, lines, strict=True):
        draw.text((origin[0] + x, origin[1] + y), line, font=face, fill=255, anchor="la")
    return mask, origin


def _with_mark(
    mask: Image.Image,
    lines: list[str],
    faces: list[ImageFont.FreeTypeFont],
    origin: tuple[float, float],
) -> Image.Image:
    """`mask` grown to hold the mark after its first line, as much on each side."""
    mark, offset = _mark(faces[0])
    # Lines are centred on the widest, so a short first line ends short of it.
    widths = [face.getlength(line) for face, line in zip(faces, lines, strict=True)]
    end = origin[0] + (max(widths) + widths[0]) / 2
    baseline = origin[1] + faces[0].getmetrics()[0]
    sx, sy = _mark_corner(mark, offset, end, baseline, _cap(faces[0]))
    side = max(0, sx + mark.width - mask.width)
    top, bottom = min(0, sy), max(mask.height, sy + mark.height)
    grown = Image.new("L", (mask.width + 2 * side, bottom - top), 0)
    grown.paste(mask, (side, -top))
    grown.paste(255, (sx + side, sy - top), mark)
    return grown


def figures_mask(text: str, font: ImageFont.FreeTypeFont, flat: bool) -> Image.Image:
    """A number on a line box from the face's highest figure to its lowest, so
    every number is as tall as every other: old-style figures rise and hang."""
    figures = [font.getbbox(c, anchor="ls") for c in "0123456789"]
    top, bottom = min(b[1] for b in figures), max(b[3] for b in figures)
    x0, _, x1, _ = font.getbbox(text, anchor="ls")
    mask = Image.new("L", (math.ceil(x1 - x0) + 2, math.ceil(bottom - top) + 2), 0)
    ImageDraw.Draw(mask).text((1 - x0, 1 - top), text, font=font, fill=255, anchor="ls")
    return flatten(mask) if flat else mask


def flatten(mask: Image.Image) -> Image.Image:
    """Hard-threshold antialiased text for the panel."""
    return mask.point(lambda v: 255 if v > _CUTOFF else 0)


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
    fitted = fit(perch, (target, target))
    origin = ((canvas.width - fitted.width) // 2 - PAD, (canvas.height - fitted.height) // 2 - PAD)
    proc = process_sprite(fitted, origin, textured=textured)
    canvas.paste(proc, origin, proc)


def blank(resolution: tuple[int, int], textured: bool) -> Image.Image:
    """An empty sheet: grained for the web, flat for the panel, whose dither
    would otherwise turn the grain into noise."""
    width, height = resolution
    if textured:
        return paper_texture(width, height)
    return Image.new("RGB", (width, height), PANEL_PAPER)
