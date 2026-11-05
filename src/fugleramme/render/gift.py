"""The splash a frame wears in its box (#355): the birds it may hear where it is going.

"Birds you may hear" across the top with the month below it, the birds packed by the collage
with the giver's favourite drawn large in the middle, and the giver's note along the foot.
The title is the plates' engraved display italic, as on the setup screen; the note is the
frame's own label typeface. Every size is a fraction of the short side, inside the frame's
margin, so the panel and a browser get the same page at their own pixel counts.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image, ImageFont

from . import fonts
from .collage import render_collage
from .page import Edges, stamp, text_mask

TITLE = "Birds you may hear"
_TITLE_FACE = "cormorant"
_TITLE = 0.077  # type sizes, of the short side
_SUBTITLE = 0.033
_NOTE = 0.032
_LEAD = 0.01  # title to subtitle
_GAP = 0.03  # the words to the birds, above and below


def note_font(font_key: str, short: int) -> ImageFont.FreeTypeFont:
    return fonts.load(font_key, round(short * _NOTE))


def note_room(size: tuple[int, int], margin: Edges) -> int:
    """How wide a note line may be, in pixels."""
    x0, _y0, x1, _y1 = margin.window(size)
    return x1 - x0


def overflow(line: str, font_key: str, size: tuple[int, int], margin: Edges) -> int:
    """How many characters too long `line` is for the splash at `size`; 0 when it fits."""
    font = note_font(font_key, min(size))
    face, room = fonts.face(line, font), note_room(size, margin)
    fits = len(line)
    while fits and face.getlength(line[:fits]) > room:
        fits -= 1
    return len(line) - fits


def splash(
    entries: list[tuple[str, Path | None]],
    spotlight: str | None,
    month: str,
    notes: tuple[str, ...],
    resolution: tuple[int, int],
    margin: Edges,
    font_key: str = fonts.DEFAULT_FONT,
    label_size: str = fonts.DEFAULT_LABEL_SIZE,
    label_text: Callable[[str], str] = str,
    show_names: bool = True,
    textured: bool = True,
) -> Image.Image:
    """`textured`: paper grain and antialiased words for a browser, flat paper and one-bit
    words for the panel, as the collage draws its labels."""
    short = min(resolution)
    flat = not textured
    title = text_mask(TITLE, fonts.load(_TITLE_FACE, round(short * _TITLE)), flat)
    subtitle = text_mask(
        f"near you, in {month}", fonts.load(_TITLE_FACE, round(short * _SUBTITLE)), flat
    )
    lines = [line for line in notes if line.strip()]
    note = text_mask("\n".join(lines), note_font(font_key, short), flat) if lines else None
    head = (title.height + subtitle.height) / short + _LEAD + _GAP
    foot = (note.height / short + _GAP) if note else 0
    page = render_collage(
        entries,
        resolution=resolution,
        show_names=show_names,
        textured=textured,
        font_key=font_key,
        label_size=label_size,
        label_text=label_text,
        margin=Edges(margin.top + head, margin.right, margin.bottom + foot, margin.left),
        spotlight=spotlight,
    )
    x0, y0, x1, y1 = margin.window(resolution)
    middle = (x0 + x1) // 2
    stamp(page, title, (middle - title.width // 2, y0), textured)
    under = y0 + title.height + round(short * _LEAD)
    stamp(page, subtitle, (middle - subtitle.width // 2, under), textured)
    if note is not None:
        stamp(page, note, (middle - note.width // 2, y1 - note.height), textured)
    return page
