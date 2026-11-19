"""Paper invariants: the tile repeats without a seam, a halo carries the page's
texture where it lands, and halo levelling stays near the cut and within its cap."""

from __future__ import annotations

import re

import numpy as np
from PIL import Image, ImageFilter

from fugleramme.render import paper
from fugleramme.render.paper import PAD, TARGET_PAPER, TILE, paper_texture, process_sprite
from fugleramme.web import STATIC_DIR


def test_the_kiosk_scales_the_same_tile():
    """The kiosk sizes its own paper from the tile, so a changed TILE that it did
    not follow would leave the surround off the page's own grain."""
    kiosk = (STATIC_DIR / "kiosk.html").read_text()
    assert re.search(r"const TILE = (\d+)", kiosk)[1] == str(TILE)


def test_the_tile_repeats_without_a_seam():
    page = np.asarray(paper_texture(2 * TILE, TILE)).astype(int)[..., 0]
    step = np.abs(np.diff(page, axis=1))
    assert step[:, TILE - 1].mean() < 1.5 * step.mean()


def test_a_halo_carries_the_page_texture_where_it_lands():
    sprite = np.zeros((120, 120, 4), np.uint8)
    sprite[20:100, 20:100] = (*TARGET_PAPER, 255)
    at = (TILE - 40, 300)  # straddles a tile edge
    page = paper_texture(700, 700)
    proc = process_sprite(Image.fromarray(sprite), at)
    drawn = page.copy()
    drawn.paste(proc, at, proc)
    assert np.array_equal(np.asarray(drawn), np.asarray(page))


def test_the_edge_ring_matches_a_max_filter():
    clear = np.random.default_rng(0).random((90, 110)) > 0.97
    expected = np.asarray(
        Image.fromarray(clear.astype(np.uint8) * 255).filter(ImageFilter.MaxFilter(9))
    )
    assert np.array_equal(paper._box_sum(clear.astype(np.int32), 4) > 0, expected > 0)


def test_reach_counts_the_steps_of_a_growth_through_neighbours():
    rng = np.random.default_rng(0)
    seed, allowed = rng.random((40, 50)) > 0.98, rng.random((40, 50)) > 0.3
    grown, expected = seed, np.zeros(seed.shape, int)
    for step in range(1, 13):
        p = np.pad(grown, 1)
        new = (p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]) & allowed & ~grown
        expected[new] = step
        grown = grown | new
    assert np.array_equal(paper._reach(seed, allowed, 12), expected)


def _flat(sprite: np.ndarray) -> np.ndarray:
    return np.asarray(process_sprite(Image.fromarray(sprite), (0, 0), textured=False)).astype(int)


def test_levelling_stays_near_the_cut_and_within_its_cap(monkeypatch):
    size, cut, ink = 200, 20, 32
    sprite = np.zeros((size, size, 4), np.uint8)
    sprite[cut : size - cut, cut : size - cut] = (*TARGET_PAPER, 255)
    # brighter toward the cut, so there is a band to level
    y, x = np.mgrid[:size, :size]
    depth = np.minimum.reduce([x - cut, size - cut - 1 - x, y - cut, size - cut - 1 - y])
    halo = (depth >= 0) & (depth < ink - cut)
    sprite[halo, :3] = np.clip(np.array(TARGET_PAPER) + 10 - depth[halo, None], 0, 255)
    # ink, with pale plumage behind it still within reach
    sprite[(depth >= ink - cut) & (depth < ink - cut + 2), :3] = 30
    plumage = depth >= ink - cut + 2
    sprite[plumage, :3] = np.clip(np.array(TARGET_PAPER) + 8, 0, 255)

    levelled, cap = _flat(sprite), paper.HALO_SHIFT
    monkeypatch.setattr(paper, "HALO_SHIFT", 0)
    moved = np.abs(levelled - _flat(sprite))[..., :3].max(2)

    inside = np.pad(plumage | (depth >= paper.HALO_REACH), PAD)
    assert moved.max() <= cap
    assert moved[np.pad(halo, PAD)].max() > 0
    assert moved[inside].max() == 0
