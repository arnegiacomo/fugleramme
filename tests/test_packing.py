"""Layout invariants: whichever packer the admin picks, opaque pixels never
overlap and nothing runs off the page - and the page is a function of the pick,
so switching layouts is not answered from the cache."""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from fugleramme.render import collage, packing
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


def test_the_layout_is_part_of_the_collage_cache_key(crowded):
    pages = [
        np.asarray(render_collage(crowded(6), (500, 400), show_names=False, layout=layout))
        for layout in ("spiral", "voids")
    ]
    assert not np.array_equal(*pages)  # the cache would have served the first twice


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_a_lone_bird_is_not_shrunk_by_the_size_search(crowded, layout):
    """The size search bisects between a fit and a failure. A set that fits at
    full size has no failure to bisect against."""
    page = render_collage(crowded(1), (800, 600), show_names=False, layout=layout)
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


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_an_anchor_pins_that_point_of_the_first_sprite_to_the_middle(layout):
    """The bird, not its plate: the anchor is where the bird is on the sprite."""
    width, height = 500, 400
    placed = LAYOUTS[layout].pack(_sprites(), width, height, (20, 30))
    assert placed is not None
    _first, x, y = placed[0]
    assert abs(x + 20 - width // 2) < packing.K and abs(y + 30 - height // 2) < packing.K


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_the_spotlit_bird_is_one_size_however_full_the_page(crowded, layout):
    """Not sized by the size search, so a crowd round it does not shrink it."""

    def pack(count: int) -> dict[int, int]:
        collage._layouts.clear()
        render_collage(crowded(count), (800, 600), layout=layout, spotlight="Genus species0")
        (placed, _px), *_ = collage._layouts.values()
        return {p.index: p.dim for p in placed}

    alone, crowd = pack(1), pack(20)
    assert alone[0] == crowd[0] > max(dim for i, dim in crowd.items() if i)


def test_the_spotlit_birds_name_keeps_its_place_inside_the_gap():
    """The gap holds the neighbours off; the name stays as close as any other."""
    bird = np.zeros((60, 80), dtype=bool)
    bird[10:50, 10:70] = True
    named = collage._with_label(0, 80, bird, Image.new("L", (50, 12), 255), 4)
    spaced = collage._spaced(named, 9)
    assert named.label_at is not None and spaced.label_at is not None
    assert (
        np.subtract(spaced.label_at, spaced.art_at).tolist()
        == np.subtract(named.label_at, named.art_at).tolist()
    )
    assert spaced.mask.shape == (named.mask.shape[0] + 18, named.mask.shape[1] + 18)


def test_the_spotlit_birds_name_is_set_larger(crowded):
    render_collage(crowded(6), (800, 600), spotlight="Genus species0")
    (placed, _px), *_ = collage._layouts.values()
    widths = {p.index: p.label_w for p in placed}
    assert widths[0] > 1.3 * max(w for i, w in widths.items() if i)
