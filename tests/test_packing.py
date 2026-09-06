"""Layout invariants: whichever packer the admin picks, opaque pixels never
overlap and nothing runs off the page - and the page is a function of the pick,
so switching layouts is not answered from the cache."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from fugleramme.render import packing
from fugleramme.render.collage import _Sprite, render_collage
from fugleramme.render.packing import LAYOUTS


def _sprites(count: int = 8) -> list[_Sprite]:
    """Birds of a few sizes, largest first, as _layout hands them to a packer."""
    return [
        _Sprite(n, 90 - 8 * n, np.ones((90 - 8 * n, 70 - 6 * n), dtype=bool)) for n in range(count)
    ]


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_a_packed_page_never_overlaps_and_never_clips(layout):
    width, height = 500, 400
    placed = LAYOUTS[layout].pack(_sprites(), width, height)
    assert placed is not None

    occupied = np.zeros((height, width), dtype=bool)
    for sprite, x, y in placed:
        h, w = sprite.mask.shape
        assert x >= 0 and y >= 0 and x + w <= width and y + h <= height
        assert not (occupied[y : y + h, x : x + w] & sprite.mask).any()
        occupied[y : y + h, x : x + w] |= sprite.mask


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_a_set_that_cannot_fit_is_reported_rather_than_squeezed(layout):
    assert LAYOUTS[layout].pack(_sprites(4), 100, 60) is None


def test_the_layout_is_part_of_the_collage_cache_key(tmp_path):
    art = Image.new("RGBA", (120, 90), (30, 30, 30, 255))
    path = tmp_path / "bird.png"
    art.save(path)
    entries = [(f"Genus species{n}", path) for n in range(6)]

    pages = [
        np.asarray(render_collage(entries, (500, 400), show_names=False, layout=layout))
        for layout in ("spiral", "voids")
    ]
    assert not np.array_equal(*pages)  # the cache would have served the first twice


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_a_lone_bird_is_not_shrunk_by_the_size_search(tmp_path, layout):
    """The size search bisects between a fit and a failure. A set that fits at
    full size has no failure to bisect against, and used to be halved into one."""
    art = Image.new("RGBA", (300, 200), (30, 30, 30, 255))
    path = tmp_path / "bird.png"
    art.save(path)

    page = render_collage([("Turdus merula", path)], (800, 600), show_names=False, layout=layout)
    drawn = (np.asarray(page.convert("L")) < 200).sum()
    assert drawn > 800 * 600 * 0.2  # a fifth of the page, not a stamp in the middle


def test_the_grid_collision_test_agrees_with_the_pixels():
    board = packing.Board(240, 180)
    mask = packing._pool(np.ones((37, 53), dtype=bool))
    board.take(mask, 3, 4)  # cells are the packer's unit; the promise is about pixels
    legal = board.legal(mask, 53, 37)

    fine = np.zeros((180, 240), dtype=bool)
    fine[3 * packing.K : 3 * packing.K + 37, 4 * packing.K : 4 * packing.K + 53] = True
    for y, x in zip(*legal.nonzero(), strict=True):
        py, px = int(y) * packing.K, int(x) * packing.K
        assert not fine[py : py + 37, px : px + 53].any()
