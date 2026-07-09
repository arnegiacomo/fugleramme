"""Composite the latest detection into a frame image, dithered for the panel.

Rendering is resolution-driven (from config) and hardware-free: it produces a
PNG that is identical whether it later goes to the Inky panel or only the web
endpoint. The 6-color Floyd-Steinberg dither approximates the Inky Impression
(Spectra 6) palette so the Mac preview looks close to the real panel.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .db import Detection
from .names import image_for

# Inky Impression Spectra 6 palette (approximate sRGB). Used for the preview
# dither; the physical panel applies its own calibrated palette on push.
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (220, 40, 40)
GREEN = (40, 140, 60)
BLUE = (40, 60, 180)
YELLOW = (230, 200, 40)
PALETTE_6 = [BLACK, WHITE, RED, GREEN, BLUE, YELLOW]

_TEXT_BAND = 0.24  # fraction of height reserved for the text band at the bottom
_MARGIN = 16


def _palette_image() -> Image.Image:
    pal = Image.new("P", (1, 1))
    flat: list[int] = []
    for colour in PALETTE_6:
        flat += list(colour)
    flat += [0, 0, 0] * (256 - len(PALETTE_6))
    pal.putpalette(flat)
    return pal


def dither(image: Image.Image) -> Image.Image:
    """Quantize an RGB image to the 6-color panel palette (returns RGB)."""
    quantized = image.convert("RGB").quantize(
        palette=_palette_image(), dither=Image.Dither.FLOYDSTEINBERG
    )
    return quantized.convert("RGB")


def _fit(bird: Image.Image, box: tuple[int, int]) -> Image.Image:
    bird = bird.copy()
    bird.thumbnail(box, Image.LANCZOS)
    return bird


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    cx: int,
    y: int,
    fill=BLACK,
) -> int:
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text((cx - (right - left) / 2, y), text, font=font, fill=fill)
    return bottom - top


def render_frame(
    detection: Detection | None,
    images_dir: Path,
    resolution: tuple[int, int],
    out_path: Path,
) -> Image.Image:
    """Render the frame for a detection and save it, dithered, to out_path."""
    width, height = resolution
    canvas = Image.new("RGB", (width, height), WHITE)
    draw = ImageDraw.Draw(canvas)

    band_h = int(height * _TEXT_BAND)
    art_h = height - band_h
    cx = width // 2

    name_font = ImageFont.load_default(size=max(20, height // 14))
    meta_font = ImageFont.load_default(size=max(14, height // 22))

    if detection is None:
        _draw_centered(draw, "Ingen registreringer enno", name_font, cx, art_h // 2)
        canvas = dither(canvas)
        canvas.save(out_path)
        return canvas

    art_path = image_for(detection.scientific_name, images_dir)
    if art_path is not None:
        bird = Image.open(art_path).convert("RGBA")
        bird = _fit(bird, (width - 2 * _MARGIN, art_h - 2 * _MARGIN))
        pos = (cx - bird.width // 2, _MARGIN + (art_h - 2 * _MARGIN - bird.height) // 2)
        canvas.paste(bird, pos, bird)
    else:
        # No artwork for this species: name-only placeholder in the art area.
        _draw_centered(draw, "(ingen illustrasjon)", meta_font, cx, art_h // 2, fill=RED)

    # Text band: scientific name, then timestamp + confidence.
    local_time = detection.detected_at.astimezone().strftime("%Y-%m-%d %H:%M")
    meta = f"{local_time}    {detection.confidence:.0%}"
    y = art_h + (band_h - _text_height(draw, name_font, meta_font)) // 2
    y += _draw_centered(draw, detection.scientific_name, name_font, cx, y) + 6
    _draw_centered(draw, meta, meta_font, cx, y, fill=BLACK)

    canvas = dither(canvas)
    canvas.save(out_path)
    return canvas


def _text_height(
    draw: ImageDraw.ImageDraw,
    name_font: ImageFont.FreeTypeFont,
    meta_font: ImageFont.FreeTypeFont,
) -> int:
    _, t1, _, b1 = draw.textbbox((0, 0), "Ay", font=name_font)
    _, t2, _, b2 = draw.textbbox((0, 0), "Ay", font=meta_font)
    return (b1 - t1) + 6 + (b2 - t2)


def now() -> datetime:
    return datetime.now().astimezone()
