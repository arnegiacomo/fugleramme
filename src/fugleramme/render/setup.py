"""The Wi-Fi setup screen the panel shows while the hotspot is up (#308).

"Fugleramme" across the top, then a QR code that joins the hotspot and the same in words.
Black and white only: a QR code dithered into the panel's colours stops scanning. Pillow's own
typeface (Aileron) sets the words; the name takes the face it is handed.

Pillow and segno only, and nothing from the rest of the package, so a frame that only drives a
panel (examples/inky) can carry a copy.
"""

from __future__ import annotations

import re

import segno
from PIL import Image, ImageDraw, ImageFont

_PAD = 0.05  # of the short side, inside the mat's margin, so nothing touches the glass's edge
_GAP = 0.05  # between the code and the words
_TITLE = 0.075  # type sizes, of the short side, before shrinking to fit
_BODY = 0.045
_NAME = 0.17  # "Fugleramme" across the top

NAME = "Fugleramme"
_QUIET = 4  # modules of white around the code, which scanners need
_LEADING = 1.35


def wifi_qr(name: str, password: str) -> str:
    """What a phone's camera reads as "join this network". Backslash, semicolon, comma,
    double quote and colon are escaped."""

    def escape(text: str) -> str:
        return re.sub(r'([\\;,":])', r"\\\1", text)

    if password:
        return f"WIFI:T:WPA;S:{escape(name)};P:{escape(password)};;"
    return f"WIFI:T:nopass;S:{escape(name)};;"


def _lines(name: str, password: str, address: str, error: str) -> list[tuple[str, bool]]:
    """The words, each marked whether it is set as a title."""
    rows = [(error, False), ("", False)] if error else []
    rows += [
        ("Scan the code, or join the Wi-Fi hotspot", False),
        (name, True),
    ]
    if password:
        rows += [(f"Password: {password}", False)]
    return rows + [
        ("", False),
        ("A setup page should open.", False),
        ("If it doesn't, open", False),
        (address, True),
    ]


def _face(size: int) -> ImageFont.FreeTypeFont:
    face = ImageFont.load_default(max(8, size))
    if not isinstance(face, ImageFont.FreeTypeFont):  # Pillow built without FreeType
        raise TypeError("the setup screen needs Pillow with FreeType")
    return face


def _fonts(rows: list[tuple[str, bool]], short: int, width: int, height: int):
    """The title and body faces, shrunk together until the words fit the box."""
    scale = 1.0
    while True:
        title = _face(round(short * _TITLE * scale))
        body = _face(round(short * _BODY * scale))
        faces = [title if big else body for _, big in rows]
        widest = max(face.getlength(text) for face, (text, _) in zip(faces, rows, strict=True))
        tall = sum(face.size * _LEADING for face in faces)
        if (widest <= width and tall <= height) or scale < 0.3:
            return title, body
        scale *= 0.9


def _name(draw: ImageDraw.ImageDraw, short: int, box: tuple[int, int, int], font: str) -> int:
    """ "Fugleramme", centred across the top of `box` (left, top, right). Returns its depth."""
    x0, y0, x1 = box
    size = round(short * _NAME)
    face = ImageFont.truetype(font, size) if font else _face(size)
    while face.getlength(NAME) > x1 - x0 and size > 8:
        size = round(size * 0.9)
        face = ImageFont.truetype(font, size) if font else _face(size)
    draw.text(((x0 + x1 - face.getlength(NAME)) / 2, y0), NAME, font=face, fill=0)
    return round(face.size * 1.2)


def setup_page(
    size: tuple[int, int],
    margins: tuple[float, float, float, float],
    name: str,
    password: str,
    address: str,
    error: str = "",
    name_font: str = "",
) -> Image.Image:
    """The screen at `size` as the frame hangs, in mode "1". `margins` are the mat's top,
    right, bottom and left, as fractions of the short side. Landscape sets the code left of
    the words, portrait above them. `name_font` is a font file for "Fugleramme" across the
    top; empty sets it in Aileron."""
    width, height = size
    short = min(size)
    top, right, bottom, left = (round(short * (m + _PAD)) for m in margins)
    x0, y0, x1, y1 = left, top, width - right, height - bottom
    gap = round(short * _GAP)
    landscape = width >= height

    page = Image.new("1", size, 1)
    draw = ImageDraw.Draw(page)
    y0 += _name(draw, short, (x0, y0, x1), name_font) + gap

    matrix = segno.make(wifi_qr(name, password), error="m").matrix
    modules = len(matrix) + 2 * _QUIET
    box = min(y1 - y0, (x1 - x0) * 45 // 100) if landscape else min(x1 - x0, (y1 - y0) * 45 // 100)
    unit = max(1, box // modules)
    side = unit * modules

    rows = _lines(name, password, address, error)
    if landscape:
        title, body = _fonts(rows, short, x1 - x0 - side - gap, y1 - y0)
    else:
        title, body = _fonts(rows, short, x1 - x0, y1 - y0 - side - gap)
    faces = [title if big else body for _, big in rows]
    lengths = [round(face.getlength(text)) for face, (text, _) in zip(faces, rows, strict=True)]
    pitches = [round(face.size * _LEADING) for face in faces]

    # The code and the words are centred as one block.
    if landscape:
        qx = x0 + max(0, (x1 - x0 - side - gap - max(lengths)) // 2)
        qy = y0 + (y1 - y0 - side) // 2
        ty = y0 + max(0, (y1 - y0 - sum(pitches)) // 2)
    else:
        qx = x0 + (x1 - x0 - side) // 2
        qy = y0 + max(0, (y1 - y0 - side - gap - sum(pitches)) // 2)
        ty = qy + side + gap

    for row, line in enumerate(matrix):
        for col, dark in enumerate(line):
            if dark:
                x, y = qx + (col + _QUIET) * unit, qy + (row + _QUIET) * unit
                draw.rectangle((x, y, x + unit - 1, y + unit - 1), fill=0)
    for (text, _), face, length, pitch in zip(rows, faces, lengths, pitches, strict=True):
        tx = qx + side + gap if landscape else x0 + (x1 - x0 - length) // 2
        draw.text((tx, ty), text, font=face, fill=0)
        ty += pitch
    return page
