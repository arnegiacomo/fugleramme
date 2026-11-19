"""The halo and the panel's dither, pixel for pixel against the pictures in
`tests/expected/`: a rewrite of either for speed or memory must not move a pixel
that shows.

The cut-outs and the page are made up here, in whole numbers, so they are the same
on every machine and no recut of the shipped artwork moves them.

After a change that is meant to move a pixel, write the pictures again and look at
each one it says moved before committing it:

    uv run python tests/test_golden.py
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from fugleramme.render.dither import dither
from fugleramme.render.paper import PAD, PANEL_PAPER, process_sprite

EXPECTED = Path(__file__).parent / "expected"


def _cutout(
    width: int, height: int, plumage: tuple[int, int, int], gap: bool = False
) -> Image.Image:
    """A bird as a scan leaves it: plumage inside an ink outline, in a ring of scan
    paper cut with a soft edge, which runs off the plate at its sides as a trimmed
    plate's does. The paper is yellower than the page, shades from left to right, and
    carries a stain and bright specks. With a `gap` the outline is open, so the halo
    reaches the plumage. Low on the bird the plumage thins to the paper, each channel
    by its own amount, so there are pixels either side of every test of what is paper,
    and a perch of ink runs out through the cut, where the paper's tone is sampled."""
    y, x = np.mgrid[:height, :width]
    # How far out a pixel is, in thousandths of the ellipse that touches the plate's sides.
    out = (1000 * (2 * x - width + 1) ** 2) // width**2 + (
        1000 * (2 * y - height + 1) ** 2
    ) // height**2
    grain = (7 * x + 13 * y) % 5 - 2
    stain = np.clip(24 - abs(3 * x - 2 * y - width), 0, 24)
    speck = 22 * ((5 * x + 3 * y) % 29 == 0)
    paper = (14 * x) // width + grain - stain + speck
    bird = out < 150
    outline = (out >= 115) & bird & ((x < 2 * width // 3) | (not gap))
    barred = bird & ((x + 2 * y) % 16 < 3)
    thin = bird & (2 * y > height)
    wash = ((7 * x + 3 * y) % 71, (2 * x + 5 * y) % 67, (3 * x + 11 * y) % 73)
    perch = (abs(x - y - (width - height) // 2) < 3) & (2 * x > width) & ~bird
    art = np.empty((height, width, 4), np.int64)
    for c, (tone, colour) in enumerate(zip((226, 216, 190), plumage, strict=True)):
        feathers = np.where(barred, colour * 2 // 3, colour + grain)
        art[..., c] = np.where(bird, np.where(thin, tone - wash[c], feathers), tone + paper)
    art[outline | perch, :3] = (38, 32, 30)
    art[..., 3] = (1040 - out) * 3  # through 24, the level that counts as opaque
    return Image.fromarray(art.clip(0, 255).astype(np.uint8), "RGBA")


def _page() -> Image.Image:
    """The panel's flat paper with two birds on it, one saturated and one pale, each in
    a halo a few levels off the paper, and a strip of pure colour straight on the paper.
    The pale bird's halo runs off the page at two sides, deeper than the dither follows
    a halo, with no bare paper in it and some of it at the very tone where a halo ends."""
    width, height = 181, 150
    y, x = np.mgrid[:height, :width]
    page = np.empty((height, width, 3), np.int64)
    page[:] = PANEL_PAPER
    for cx, cy, pale in ((52, 58, False), (128, 62, True)):
        out = (x - cx) ** 2 + (y - cy) ** 2
        halo, bird = out < 44**2, out < 27**2
        tint = np.stack([(x + y) % 7 - 3, (2 * x + y) % 5 - 2, (x + 3 * y) % 9 - 4], -1)
        if pale:
            halo, tint = (x > 96) & (y < 120), tint + (0, 0, 8)
        page[halo] += tint[halo]
        if pale:
            ramp = np.stack([244 - (x + y) % 23, 240 - (2 * x) % 19, 228 - y % 17], -1)
        else:
            ramp = np.stack([(5 * x) % 256, (3 * y + x) % 256, (255 - 4 * x) % 256], -1)
        page[bird] = ramp[bird]
    for n, colour in enumerate([(200, 30, 30), (30, 140, 60), (30, 50, 170), (230, 200, 40)]):
        page[128:143, 14 + 39 * n : 50 + 39 * n] = colour
    page[128:143, 14:170] -= (y[128:143, 14:170, None] - 128) * 6
    return Image.fromarray(page.clip(0, 255).astype(np.uint8), "RGB")


_COLOURED = (113, 79, (168, 74, 40))
_PALE = (70, 97, (247, 244, 236), True)

# What is drawn for each picture kept. The textured halos land across a seam of the
# paper's tile, placed as the collage places one: by where the art goes, less its margin.
# No size here is a whole number of the halo's or the dither's blocks.
DRAWN: dict[str, Callable[[], Image.Image]] = {
    "halo-coloured-textured": lambda: process_sprite(_cutout(*_COLOURED), (456 - PAD, 516 - PAD)),
    "halo-coloured-flat": lambda: process_sprite(_cutout(*_COLOURED), (0, 0), textured=False),
    "halo-pale-textured": lambda: process_sprite(_cutout(*_PALE), (516 - PAD, 456 - PAD)),
    "halo-pale-flat": lambda: process_sprite(_cutout(*_PALE), (0, 0), textured=False),
    "dither-page": lambda: dither(_page()),
}


def _seen(picture: Image.Image) -> np.ndarray:
    """What a picture puts on a page: cut to where it is not clear, with no colour kept
    under a clear pixel. RGBA, so the dither's six colours are compared as well as
    where they fall."""
    rgba = picture.convert("RGBA")
    pixels = np.asarray(rgba.crop(rgba.getchannel("A").getbbox())).astype(np.int16)
    pixels[pixels[..., 3] == 0] = 0
    return pixels


def _moved(drawn: Image.Image, kept: Image.Image) -> tuple[int, int]:
    """How many pixels differ in what two pictures show, and by how many levels at most."""
    seen, expected = _seen(drawn), _seen(kept)
    if drawn.mode != kept.mode or seen.shape != expected.shape:
        return seen.shape[0] * seen.shape[1], 255
    apart = np.abs(seen - expected).max(axis=2)
    return int((apart > 0).sum()), int(apart.max())


@pytest.mark.parametrize("name", sorted(DRAWN))
def test_the_picture_drawn_is_the_one_kept(name, tmp_path):
    drawn = DRAWN[name]()
    pixels, levels = _moved(drawn, Image.open(EXPECTED / f"{name}.png"))
    if pixels:
        drawn.save(tmp_path / f"{name}.png")
    assert not pixels, (
        f"{pixels} pixels differ, by up to {levels} levels, drawn as {tmp_path / name}.png"
    )


def write_expected() -> None:
    """Draw every picture again, keep each one that moved and say by how much. One that
    did not move is left alone: another Pillow packs the same pixels into other bytes."""
    EXPECTED.mkdir(exist_ok=True)
    for name, draw in DRAWN.items():
        path, drawn = EXPECTED / f"{name}.png", draw()
        new = (drawn.width * drawn.height, 255)
        pixels, levels = _moved(drawn, Image.open(path)) if path.exists() else new
        if pixels:
            drawn.save(path, optimize=True)
        moved = f"{pixels} pixels moved, by up to {levels} levels" if pixels else "unchanged"
        print(f"{name}: {moved}")


if __name__ == "__main__":
    write_expected()
