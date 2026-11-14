"""The splash a frame wears in its box (#355): the birds it may hear where it is going.

The giver's title across the top, the birds packed by the collage, and the giver's note
along the foot. The title is the plates'
engraved display italic, as on the setup screen; the note is the frame's own label typeface.
Every size is a fraction of the short side, inside the frame's margin, so the panel and a
browser get the same page at their own pixel counts.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageFont

from . import fonts, packing
from .collage import render_collage
from .page import Edges, stamp, text_mask

TITLE = "Birds you may hear in your garden"  # offered first; the giver may write another
_TITLE_FACE = "cormorant"
_TITLE = 0.077  # type sizes, of the short side
_NOTE = 0.032
_GAP = 0.03  # the words to the birds, above and below


def title_font(title: str, size: tuple[int, int], margin: Edges) -> ImageFont.FreeTypeFont:
    """The title's face at its own size, or the largest the title fits the page's width at:
    a portrait panel is too narrow for a long one."""
    short = min(size)
    font = fonts.load(_TITLE_FACE, round(short * _TITLE))
    x0, _y0, x1, _y1 = margin.window(size)
    wide = fonts.face(title, font).getlength(title)
    return font if wide <= x1 - x0 else fonts.load(_TITLE_FACE, int(font.size * (x1 - x0) / wide))


def smallest_title(short: int) -> ImageFont.FreeTypeFont:
    """As small as a title may shrink: the note's size. One too wide even so is too long."""
    return fonts.load(_TITLE_FACE, round(short * _NOTE))


def note_font(font_key: str, short: int) -> ImageFont.FreeTypeFont:
    return fonts.load(font_key, round(short * _NOTE))


def overflow(line: str, font: ImageFont.FreeTypeFont, size: tuple[int, int], margin: Edges) -> int:
    """How many characters too long `line` is for the splash at `size`; 0 when it fits."""
    x0, _y0, x1, _y1 = margin.window(size)
    face = fonts.face(line, font)
    fits = len(line)
    while fits and face.getlength(line[:fits]) > x1 - x0:
        fits -= 1
    return len(line) - fits


def splash(
    entries: list[tuple[str, Path | None]],
    title: str,
    notes: tuple[str, ...],
    resolution: tuple[int, int],
    margin: Edges,
    font_key: str = fonts.DEFAULT_FONT,
    label_size: str = fonts.DEFAULT_LABEL_SIZE,
    label_text: Callable[[str], str] = str,
    show_names: bool = True,
    textured: bool = True,
    layout: str = packing.DEFAULT_LAYOUT,
    name_key: bool = False,
) -> Image.Image:
    """`textured`: paper grain and antialiased words for a browser, flat paper and one-bit
    words for the panel, as the collage draws its labels."""
    short = min(resolution)
    flat = not textured
    head = text_mask(title, title_font(title, resolution, margin), flat)
    lines = [line for line in notes if line.strip()]
    note = text_mask("\n".join(lines), note_font(font_key, short), flat) if lines else None
    foot = (note.height / short + _GAP) if note else 0
    page = render_collage(
        entries,
        resolution=resolution,
        show_names=show_names,
        textured=textured,
        font_key=font_key,
        label_size=label_size,
        label_text=label_text,
        margin=Edges(
            margin.top + head.height / short + _GAP, margin.right, margin.bottom + foot, margin.left
        ),
        layout=layout,
        name_key=name_key,
    )
    x0, y0, x1, y1 = margin.window(resolution)
    middle = (x0 + x1) // 2
    stamp(page, head, (middle - head.width // 2, y0), textured)
    if note is not None:
        stamp(page, note, (middle - note.width // 2, y1 - note.height), textured)
    return page
