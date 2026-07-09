"""Panel color reduction.

The Inky Impression (Spectra 6) shows only 6 colors. The web/kiosk collage is
full color; for the panel the same collage is dithered down to this palette.
The physical panel applies its own calibrated palette on push - this dither is
what the Mac preview uses to approximate it.
"""

from __future__ import annotations

from PIL import Image

# Inky Impression Spectra 6 palette (approximate sRGB).
BLACK = (0, 0, 0)
WHITE = (255, 255, 255)
RED = (220, 40, 40)
GREEN = (40, 140, 60)
BLUE = (40, 60, 180)
YELLOW = (230, 200, 40)
PALETTE_6 = [BLACK, WHITE, RED, GREEN, BLUE, YELLOW]


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
