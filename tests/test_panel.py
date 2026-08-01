"""Panel push invariants. The driver is Pi-only, so a fake device stands in for
the two things this side has to get right off-hardware: the buffer handed to
`set_image` is always the panel's native landscape, and the dithered image is
one the driver will pass through instead of dithering a second time."""

from __future__ import annotations

import numpy
import pytest
from PIL import Image

from fugleramme.panel import Panel
from fugleramme.render import dither

# inky.inky_el133uf1.DESATURATED_PALETTE - what the driver quantizes against.
DESATURATED = [
    [0, 0, 0], [255, 255, 255], [255, 255, 0], [255, 0, 0],
    [0, 0, 255], [0, 255, 0], [255, 255, 255],
]


class FakeInky:
    resolution = (1600, 1200)

    def __init__(self):
        self.image = None
        self.shown = 0

    def set_image(self, image):
        if image.size != self.resolution:
            raise ValueError("wrong size")
        self.image = image

    def show(self):
        self.shown += 1


def _panel() -> tuple[Panel, FakeInky]:
    device = FakeInky()
    return Panel(device), device


def test_landscape_image_pushes_unrotated():
    panel, device = _panel()
    panel.push(Image.new("P", (1600, 1200)))
    assert device.image.size == (1600, 1200)
    assert device.shown == 1


def test_portrait_image_is_rotated_to_native():
    panel, device = _panel()
    source = Image.new("RGB", (1200, 1600))
    source.putpixel((0, 0), (255, 0, 0))  # top-left; ROTATE_90 puts it bottom-left
    panel.push(source)
    assert device.image.size == (1600, 1200)
    assert device.image.getpixel((0, 1199)) == (255, 0, 0)


def test_mismatched_size_raises_rather_than_pushing():
    panel, device = _panel()
    with pytest.raises(ValueError):
        panel.push(Image.new("P", (800, 480)))
    assert device.shown == 0


def test_dither_survives_the_driver_untouched():
    # The driver re-dithers unless the image is "P" with exactly 6 palette
    # colours, and then remaps by nearest DESATURATED colour - which must be the
    # identity, or the panel shows the wrong ink.
    noise = Image.effect_noise((160, 120), 90).convert("L")
    source = Image.merge("RGB", (noise, noise.rotate(37), noise.rotate(90)))
    image = dither(source)
    assert image.mode == "P"
    assert len(image.palette.colors) == 6

    palette_image = Image.new("P", (1, 1))
    palette_image.putpalette(numpy.array(DESATURATED, dtype=numpy.uint8).flatten().tobytes())
    remapped = image.convert("RGB").quantize(6, palette=palette_image, dither=Image.Dither.NONE)

    assert numpy.array_equal(numpy.array(image), numpy.array(remapped))
