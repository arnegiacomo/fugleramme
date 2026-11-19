"""Layout invariants: whichever packer the admin picks, opaque pixels never
overlap and nothing runs off the page - and the page is a function of the pick,
so switching layouts is not answered from the cache."""

from __future__ import annotations

import math
import os
import sys
from collections import Counter
from pathlib import Path
from typing import NamedTuple
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image, UnidentifiedImageError

from fugleramme.render import collage, packing
from fugleramme.render.collage import _Sprite, render_collage
from fugleramme.render.packing import LAYOUTS
from fugleramme.render.page import trim


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


@pytest.mark.parametrize("layout", sorted(LAYOUTS))
def test_a_packer_takes_the_sprites_once_and_in_order(layout):
    """The size search makes each sprite as the packer asks for it."""
    pack = LAYOUTS[layout].pack
    whole, lazy = pack(_sprites(), 500, 400), pack(iter(_sprites()), 500, 400)
    assert whole is not None and lazy is not None
    assert [(s.index, x, y) for s, x, y in lazy] == [(s.index, x, y) for s, x, y in whole]


def test_the_spiral_takes_the_first_free_place_on_its_walk():
    """Against the walk done one position at a time with nothing but the box test."""
    width, height = 240, 180
    yy, xx = np.ogrid[-1:1:40j, -1:1:56j]
    disc = xx**2 + yy**2 <= 1
    sprites = [_Sprite(n, 0, disc[: 40 - 3 * n, : 56 - 4 * n]) for n in range(10)]

    occ = np.zeros((height, width), dtype=bool)
    expected = []
    for sprite in sprites:
        h, w = sprite.mask.shape
        for px, py in packing._ring(width / 2, height / 2, math.hypot(width, height)):
            x, y = int(px - w / 2), int(py - h / 2)
            on_page = x >= 0 and y >= 0 and x + w <= width and y + h <= height
            if on_page and not (occ[y : y + h, x : x + w] & sprite.mask).any():
                break
        occ[y : y + h, x : x + w] |= sprite.mask
        expected.append((x, y))

    placed = packing.spiral(sprites, width, height)
    assert placed is not None
    assert [(x, y) for _sprite, x, y in placed] == expected


class _Pack(NamedTuple):
    """One call to the packer: the size of each footprint made since the call before,
    how many sprites it took, the paper it had and whether they all found a place."""

    made: list[int]
    taken: int
    paper: int
    fit: bool


@pytest.fixture
def packs(monkeypatch):
    """The spiral as the layout "watched", with every pack it is asked for noted."""
    noted: list[_Pack] = []
    made: list[int] = []
    footprint = collage._footprint

    def weighed(alpha):
        mask = footprint(alpha)
        made.append(int(mask.sum()))
        return mask

    def pack(sprites, width, height, anchor=None):
        taken = []
        placed = packing.spiral((taken.append(s) or s for s in sprites), width, height, anchor)
        noted.append(_Pack(made.copy(), len(taken), width * height, placed is not None))
        made.clear()
        return placed

    monkeypatch.setattr(collage, "_footprint", weighed)
    monkeypatch.setitem(packing.LAYOUTS, "watched", packing.LAYOUTS["spiral"]._replace(pack=pack))
    return noted


def test_a_pack_that_fails_makes_no_sprite_past_the_one_with_no_place(tmp_path, packs):
    """Hollow frames weigh next to nothing, so every size reaches the packer, and none
    goes inside another, so the first sizes run out of page part of the way through."""
    art = tmp_path / "frame.png"
    frame = Image.new("RGBA", (200, 200), (40, 40, 40, 255))
    frame.paste((0, 0, 0, 0), (10, 10, 190, 190))
    frame.save(art)
    count = 12
    render_collage(
        [(f"Genus species{n}", art) for n in range(count)],
        (800, 600),
        show_names=False,
        layout="watched",
    )

    # The first set is made whole to be weighed. Every set after it is made as it is taken.
    failed = [pack for pack in packs[1:] if not pack.fit]
    assert failed and packs[-1].fit
    assert all(len(pack.made) == pack.taken for pack in failed)
    assert any(pack.taken < count for pack in failed)


def test_a_set_with_more_footprint_than_paper_never_reaches_the_packer(crowded, packs):
    count = 40
    render_collage(crowded(count), (800, 600), show_names=False, layout="watched")

    first = packs[0]
    assert sum(first.made[:count]) > first.paper  # the birds start out larger than the page
    assert len(first.made) > count  # so that set was weighed and never packed
    assert sum(first.made[-count:]) <= first.paper  # and the first to be packed was not


def _plate(call) -> Path:
    """The file an `Image.open` call was for, however it was handed over."""
    fp = call.args[0] if call.args else call.kwargs["fp"]
    return Path(fp if isinstance(fp, str | os.PathLike) else fp.name)


def test_a_plate_is_decoded_once_to_pack_and_once_to_draw(tmp_path):
    """Once and kept would hold every decoded plate for the whole render, and a page
    whose layout is cached has nothing to pack."""
    entries = []
    for n in range(5):
        art = tmp_path / f"bird{n}.png"
        Image.new("RGBA", (200, 150), (40, 40, 40, 255)).save(art)
        entries.append((f"Genus species{n}", art))

    with patch.object(Image, "open", side_effect=Image.open) as opened:
        render_collage(entries, (500, 400), show_names=False)
        packed = Counter(_plate(call) for call in opened.call_args_list)
        render_collage(entries, (500, 400), show_names=False)
        both = Counter(_plate(call) for call in opened.call_args_list)

    assert packed == {art: 2 for _name, art in entries}
    assert both == {art: 3 for _name, art in entries}


def _calls(work) -> int:
    """How many functions `work` calls, Python's and C's alike."""
    count = 0

    def note(_frame, event, _arg):
        nonlocal count
        count += event in ("call", "c_call")

    before = sys.getprofile()
    sys.setprofile(note)
    try:
        work()
    finally:
        sys.setprofile(before)
    return count


def test_a_page_is_laid_out_without_a_call_per_candidate_place(crowded):
    """The spiral's walk over this page is 77,000 places, for each bird at each size
    the search tries. One at a time in Python that is millions of calls. With arrays
    the page takes 140,000, and 420,000 the first time a page of its size is packed,
    to list the places."""
    entries = crowded(20)
    assert _calls(lambda: render_collage(entries, (800, 600))) < 1_000_000


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


def test_a_plate_that_will_not_open_says_which_file(tmp_path):
    """Pillow's "image file is truncated" never names the file."""
    junk = tmp_path / "perch.png"
    junk.write_bytes(b"not an image")
    with pytest.raises(UnidentifiedImageError) as caught:
        trim(junk)
    assert any(str(junk) in note for note in caught.value.__notes__)
