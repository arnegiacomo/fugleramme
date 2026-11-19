"""Panel color reduction.

The Inky Impression (Spectra 6) shows only 6 colors. The kiosk collage is full
color; for the panel it is reduced here rather than in the driver, because
`inky.set_image` re-dithers anything that is not already a 6-color "P" image -
dithering an already-dithered image smears it. Handing it a "P" image with
exactly 6 palette entries makes it skip its own dither and just remap indices,
so this module owns the reduction and the saved frame matches the glass.

Index order below is the driver's (`inky.inky_el133uf1`), which the remap
depends on. The palette is a blend of the driver's two: the "desaturated" set is
what it writes, the "saturated" set is nearer what the panel actually shows, so
dithering against the blend measures color distance in roughly panel space.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .paper import PANEL_PAPER, _reach

# Driver index order: black, white, yellow, red, blue, green.
_DESATURATED = [(0, 0, 0), (255, 255, 255), (255, 255, 0), (255, 0, 0), (0, 0, 255), (0, 255, 0)]
_SATURATED = [(0, 0, 0), (161, 164, 165), (208, 190, 71), (156, 72, 75), (61, 59, 94), (58, 91, 70)]

BLACK = 0  # the index, for painting straight onto a dithered page

# Matches the inky default. Raising it dithers against duller targets, which
# spreads more ink; the blend must stay nearest-neighbour to _DESATURATED or the
# driver's remap will land on the wrong color.
SATURATION = 0.5

_LIFT = np.array([0.887, 0.906, 0.950])
_PIVOT = 182
_CONTRAST = 1.15
_FADE = 4
_HALO = 12
_HALO_REACH = 32
# `_pop` goes through the page this many rows at a time: in float64 a row is eight times its size.
_BAND = 64

PALETTE_6 = [
    tuple(int(s * SATURATION + d * (1.0 - SATURATION)) for s, d in zip(sat, desat, strict=True))
    for sat, desat in zip(_SATURATED, _DESATURATED, strict=True)
]


def _palette_image() -> Image.Image:
    pal = Image.new("P", (1, 1))
    flat: list[int] = []
    for colour in PALETTE_6:
        flat += list(colour)
    # Pad with black, already index 0, so the palette still reads as 6 unique colors.
    flat += [0, 0, 0] * (256 - len(PALETTE_6))
    pal.putpalette(flat)
    return pal


def _boost(rgb: np.ndarray, lift: np.ndarray | float = _LIFT) -> np.ndarray:
    return _PIVOT + (rgb * lift - _PIVOT) * _CONTRAST


def _pop(image: Image.Image) -> Image.Image:
    """Darken the birds so pale plumage takes ink. The paper and the halos keep
    their tone, or the halos would ring the birds."""
    rgb = np.asarray(image.convert("RGB"))
    paper = np.array(PANEL_PAPER, np.float64)
    bands = [slice(top, top + _BAND) for top in range(0, rgb.shape[0], _BAND)]
    # A channel at a time, here and below: across an axis of three numpy works pixel by pixel.
    dist = np.concatenate(
        [np.sqrt(sum((rgb[rows, :, c] - paper[c]) ** 2 for c in range(3))) for rows in bands]
    )
    halo = _reach(dist <= 1, dist <= _HALO, _HALO_REACH) > 0
    out = np.empty_like(rgb)
    back = paper - _boost(paper)
    for rows in bands:
        keep = np.maximum(np.exp(-dist[rows] / _FADE), halo[rows])
        for c in range(3):
            boosted = _boost(rgb[rows, :, c], _LIFT[c])
            out[rows, :, c] = np.clip(np.rint(boosted + keep * back[c]), 0, 255)
    return Image.fromarray(out)


def dither(image: Image.Image) -> Image.Image:
    """Quantize an RGB image to the 6-color panel palette (returns mode "P")."""
    return _pop(image).quantize(palette=_palette_image(), dither=Image.Dither.FLOYDSTEINBERG)


def monochrome(image: Image.Image) -> Image.Image:
    """A black and white page onto the panel palette as it is, undithered: the setup screen's
    QR code stops scanning once it is smeared."""
    return image.convert("RGB").quantize(palette=_palette_image(), dither=Image.Dither.NONE)
