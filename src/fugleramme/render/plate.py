"""One bird, large, with its name under it - a single plate from the book.

Three modes draw this page and differ only in which bird they hand it and what
the caption reads: the latest species heard, the bird of the day, the newest
arrival. The bird and its caption are centred as one block, so a tall bird and a
wide one both sit on the page rather than against its top edge.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from . import fonts
from .page import (
    NO_MARGIN,
    Edges,
    blank,
    day_ordinal,
    draw_perch,
    fit,
    label_px,
    stamp,
    text_mask,
    trim,
)
from .paper import PAD, process_sprite

DEFAULT_RESOLUTION = (1600, 1200)

_MARGIN = 0.08  # page edge to content, fraction of the short side
_NAME_SCALE = 1.8  # the name carries this page, unlike a label lost in a collage
_NOTE_SCALE = 0.5
_NAME_GAP = 0.5  # bird to name, em of the name
_NOTE_GAP = 0.3


def effective_margin(margin: Edges) -> Edges:
    """The plate's own margin on each edge, or the admin's where that is wider."""
    return Edges(*(max(_MARGIN, edge) for edge in margin))


def render_plate(
    art_path: Path | None,
    name: str = "",
    note: str = "",
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    show_names: bool = True,
    textured: bool = True,
    font_key: str = fonts.DEFAULT_FONT,
    label_size: str = fonts.DEFAULT_LABEL_SIZE,
    perches: Sequence[Path] = (),
    day: int | None = None,
    margin: Edges = NO_MARGIN,
) -> Image.Image:
    """The page for one bird, or the empty perch when there is none to draw."""
    width, height = resolution
    canvas = blank(resolution, textured)
    if art_path is None:
        draw_perch(canvas, perches, day_ordinal() if day is None else day, textured)
        return canvas

    name_px = round(label_px(width, height, label_size) * _NAME_SCALE)
    lines: list[tuple[Image.Image, int]] = []  # mask, gap above it
    if show_names and name:
        flat = not textured
        lines.append(
            (text_mask(name, fonts.load(font_key, name_px), flat), round(name_px * _NAME_GAP))
        )
        if note:
            lines.append(
                (
                    text_mask(note, fonts.load(font_key, round(name_px * _NOTE_SCALE)), flat),
                    round(name_px * _NOTE_GAP),
                )
            )
    caption = sum(mask.height + gap for mask, gap in lines)

    x0, y0, x1, y1 = effective_margin(margin).window(resolution)
    art = fit(trim(art_path), (x1 - x0, max(1, y1 - y0 - caption)))

    y = y0 + (y1 - y0 - art.height - caption) // 2
    origin = (x0 + (x1 - x0 - art.width) // 2 - PAD, y - PAD)
    proc = process_sprite(art, origin, textured=textured)
    canvas.paste(proc, origin, proc)

    y += art.height
    for mask, gap in lines:
        y += gap
        stamp(canvas, mask, (x0 + (x1 - x0 - mask.width) // 2, y), textured)
        y += mask.height
    return canvas
