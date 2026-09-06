"""Kiosk collage: full-color composite of the species seen in the lookback window.

This is the web/kiosk view (also dithered onto the panel). It uses the source
PNGs at full color and packs them by their silhouettes: opaque pixels never
overlap and nothing clips off screen, but the transparent margins are free to
overlap so birds nestle closely. Birds are sized by their real body mass
(compressed, see sizes.py) and placed largest-first, by default on an outward
spiral from the centre so the big birds land in the middle; the whole set is
then scaled to fill the canvas. `settings.layout` can hand the placing to one of
packing.py's instead.

Species with no artwork are omitted (there is nothing to draw for them once
names are off). The name label is an admin toggle, on by default, and reads in
the admin's chosen language(s); it packs as part of its bird, tucked up under
the silhouette, so a name can never land on a neighbour or clip.

Nothing here rolls dice per render: a species holds its artwork for as long as
it is in the window (picks.py) and the mirror is a hash of the name, so a bird
is unaffected by which other birds are on the page, or by a restart.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from ..names import image_for
from ..picks import Picks
from ..source import Source
from . import fonts, packing
from .page import (
    MIN_LABEL_PX,
    blank,
    day_ordinal,
    draw_perch,
    label_px,
    stamp,
    text_mask,
    trim,
)
from .paper import PAD, process_sprite
from .sizes import SIZE_EXPONENT, mass_of

log = logging.getLogger(__name__)

DEFAULT_RESOLUTION = (1280, 800)
# Short side the layout is packed at, then scaled to whatever is drawn. The
# packer works in whole pixels, so packing at the output size would put the
# panel and the kiosk on different pages.
_PACK_SHORT = 1200
_MARGIN = 0.04  # page edge to content on short side. Hardcoded now, maybe add configurability?
_MAX_BIRDS = 40  # keeps the render quick, not the page tidy
_ALPHA_CUTOFF = 24
_OVERLAP_PX = 2  # erode the collision mask slightly so birds nestle into
# each other's (invisible on paper) halos. No rotation:
# it tilts the ground/water on birds drawn with terrain.
_ATTEMPTS = 20


def _scaled(img: Image.Image, max_dim: int, flip: bool) -> Image.Image:
    """Scale a trimmed sprite to max_dim on its longest side, optionally mirroring
    it. Mirroring (not rotation) adds variety while keeping any ground or water
    level. Takes the alpha channel alone when packing, the whole plate to draw."""
    scale = max_dim / max(img.width, img.height)
    if scale != 1.0:
        img = img.resize(
            (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
            Image.Resampling.LANCZOS,
        )
    return img.transpose(Image.Transpose.FLIP_LEFT_RIGHT) if flip else img


def _footprint(alpha: Image.Image) -> np.ndarray:
    """Opaque area as a bool array (True = keep clear), eroded so birds nestle
    into each other's (invisible on paper) halos. Their bodies still can't."""
    mask = alpha.point(lambda a: 255 if a > _ALPHA_CUTOFF else 0)
    if _OVERLAP_PX:
        mask = mask.filter(ImageFilter.MinFilter(_OVERLAP_PX * 2 + 1))
    return np.asarray(mask, dtype=bool)


@dataclass(frozen=True, eq=False)  # eq: a generated __eq__ would raise on the ndarray
class _Sprite:
    """A bird, and optionally its name, as one packable unit: `mask` is the whole
    footprint, `art_at` and `label_at` locate the two inside it. Everything is in
    pack pixels - the art is redrawn from source at the size being rendered."""

    index: int
    dim: int  # the art's longest side
    mask: np.ndarray
    art_at: tuple[int, int] = (0, 0)
    label_at: tuple[int, int] | None = None
    label_w: int = 0  # the reserved box; the redrawn name is centred in it


def _center(placed, width: int, height: int):
    """Shift the packed cluster so its bounding box is centred on the canvas."""
    xs0 = min(x for _, x, _ in placed)
    ys0 = min(y for _, _, y in placed)
    xs1 = max(x + s.mask.shape[1] for s, x, _ in placed)
    ys1 = max(y + s.mask.shape[0] for s, _, y in placed)
    dx = (width - (xs1 - xs0)) // 2 - xs0
    dy = (height - (ys1 - ys0)) // 2 - ys0
    return [(sprite, x + dx, y + dy) for sprite, x, y in placed]


def _with_label(
    index: int, dim: int, art_mask: np.ndarray, label: Image.Image, gap: int
) -> _Sprite:
    """Join a bird and its name into one packable footprint.

    Reserving the name with the bird is what guarantees it a place at all: the
    packer leaves no free paper between birds, so a name placed afterwards could
    only sit outside the cluster and interior birds would get none.
    """
    ah, aw = art_mask.shape
    lw, lh = label.size
    cols = art_mask.nonzero()[1]
    centre = cols.mean() if cols.size else aw / 2  # centroid: under the body, not the tail

    # Both bounds off one rounded edge; rounding them apart clips the box a column short.
    offset = round(centre - lw / 2)
    left = min(0, offset)
    width = max(aw, offset + lw) - left
    ax, lx = -left, offset - left

    # Raise it until it clears the outline, into the gap beside a leg or under a perch.
    under = art_mask[:, max(0, lx - ax) : min(aw, lx - ax + lw)]
    bottom = np.nonzero(under.any(axis=1))[0]
    top = (bottom[-1] + 1 if bottom.size else ah) + gap

    height = max(ah, top + lh)
    mask = np.zeros((height, width), dtype=bool)
    mask[:ah, ax : ax + aw] = art_mask
    mask[top : top + lh, lx : lx + lw] = True
    return _Sprite(index, dim, mask, (ax, 0), (lx, top), lw)


def _flip(name: str) -> bool:
    """Mirror a bird or not, decided by its name alone: variety without churn,
    since a set-wide rng would re-roll every bird whenever one arrives."""
    return hashlib.blake2b(name.encode(), digest_size=1).digest()[0] < 128


def _size_weights(names: list[str]) -> list[float]:
    """Per-bird display weight from real mass, centered on the present set's
    geometric mean and compressed by SIZE_EXPONENT."""
    masses = [mass_of(n) for n in names]
    geo = math.exp(sum(math.log(m) for m in masses) / len(masses))
    return [(m / geo) ** SIZE_EXPONENT for m in masses]


def _layout(
    names: list[str],
    alphas: list[Image.Image],
    order: list[int],
    weights: list[float],
    flips: list[bool],
    base: float,
    width: int,
    height: int,
    font_key: str | None,
    name_px: int,
    label_text: Callable[[str], str] = str,
    layout: str = packing.DEFAULT_LAYOUT,
):
    """Shrink the set to the first size where every bird, name included, fits,
    and return the placements with the name size they were reserved at. Names
    have to shrink too: a fixed-size name never yields, so a full page of them
    cannot converge at all."""
    chosen = packing.layout_of(layout)

    @cache  # a midpoint often lands back on a size already rasterized
    def rasterize(key: str, px: int) -> tuple[list[Image.Image], int]:
        font = fonts.load(key, px)  # only the size is packed; the draw pass re-rasterizes
        return [text_mask(label_text(names[i]), font, False) for i in order], round(px * 0.35)

    def attempt(shrink: float):
        px = max(MIN_LABEL_PX, round(name_px * shrink)) if font_key else 0
        labels, gap = rasterize(font_key, px) if font_key else ([], 0)
        sprites = []
        for n, i in enumerate(order):
            dim = max(24, int(base * shrink * weights[i]))
            mask = _footprint(_scaled(alphas[i], dim, flips[i]))
            sprites.append(
                _with_label(i, dim, mask, labels[n], gap) if font_key else _Sprite(i, dim, mask)
            )
        placed = chosen.pack(sprites, width, height)
        return None if placed is None else (_center(placed, width, height), px)

    fit, large = None, 0.0
    for step in range(_ATTEMPTS):
        small = 0.9**step
        fit = attempt(small)
        if fit is not None:
            break
        large = small
    if fit is None:
        return None, 0

    # The descent lands up to a tenth under what the page could hold, and the
    # gap is bare paper, so bisect back into the size that failed. Nothing
    # failed means `base` was already the ceiling: there is nothing to reach for.
    for _ in range(chosen.refine if large else 0):
        middle = (small + large) / 2
        got = attempt(middle)
        if got is None:
            large = middle
        else:
            fit, small = got, middle
    return fit


@dataclass(frozen=True)
class _Placed:
    """Where one bird and its name go, in pack pixels. All the draw pass needs -
    the collision masks stay inside the packer, so this is what gets cached."""

    index: int
    dim: int
    at: tuple[int, int]
    label_at: tuple[int, int] | None
    label_w: int


_layouts: dict[tuple, tuple[tuple[_Placed, ...], int]] = {}
_layouts_lock = threading.Lock()
_LAYOUTS_MAX = 8


def _placements(
    key: tuple,
    arts: list[Image.Image],
    names: list[str],
    flips: list[bool],
    width: int,
    height: int,
    font_key: str | None,
    name_px: int,
    label_text: Callable[[str], str],
    layout: str,
) -> tuple[tuple[_Placed, ...], int]:
    """Pack the page, or return the cached packing. The panel and the kiosk pack
    identically - only `scale` and the paper differ - so whichever renders first
    pays for both. The lock is held across the pack for the same reason: the
    second caller should wait for the first rather than pack its own copy."""
    with _layouts_lock:
        hit = _layouts.get(key)
        if hit is not None:
            return hit

        # Each bird's target size scales with its real mass (compressed); the whole
        # set then overshoots and shrinks to the first fit that fills the canvas.
        # Placing biggest-first on the center-out spiral keeps large birds central.
        weights = _size_weights(names)
        order = sorted(range(len(names)), key=lambda i: -weights[i])
        base = min(
            math.sqrt(width * height * 1.5 / sum(w * w for w in weights)),
            min(width, height) * 0.7 / max(weights),
        )
        # Pack inside the margin but size off the whole page, so only a set that
        # doesn't fit has to shrink.
        margin = round(min(width, height) * _MARGIN)
        box = (width - 2 * margin, height - 2 * margin)
        alphas = [img.getchannel("A") for img in arts]
        args = (names, alphas, order, weights, flips, base, *box)

        placed, used_px = _layout(*args, font_key, name_px, label_text, layout)
        if placed is None and font_key:
            log.warning("No layout fits %d species with names at %dx%d", len(names), *box)
            placed, used_px = _layout(*args, None, name_px, layout=layout)  # birds beat blank paper

        result = (
            tuple(
                _Placed(
                    s.index,
                    s.dim,
                    (x + margin + s.art_at[0], y + margin + s.art_at[1]),
                    None
                    if s.label_at is None
                    else (x + margin + s.label_at[0], y + margin + s.label_at[1]),
                    s.label_w,
                )
                for s, x, y in placed or ()
            ),
            used_px,
        )
        if len(_layouts) >= _LAYOUTS_MAX:
            _layouts.clear()
        _layouts[key] = result
        return result


def render_collage(
    entries: list[tuple[str, Path | None]],
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    show_names: bool = True,
    textured: bool = True,
    font_key: str = fonts.DEFAULT_FONT,
    label_size: str = fonts.DEFAULT_LABEL_SIZE,
    label_text: Callable[[str], str] = str,
    perches: Sequence[Path] = (),
    layout: str = packing.DEFAULT_LAYOUT,
) -> Image.Image:
    """Composite the given (name, image) entries into a tightly packed collage.

    textured: paper grain for the web, flat paper for the panel, whose dither
    would otherwise turn the grain into noise. It also picks the label ink.
    label_text: scientific name -> what the label reads; str leaves it alone.
    perches: the active style's bare branches, for a page with no birds on it.
    layout: how the birds are packed (packing.LAYOUTS).
    """
    canvas = blank(resolution, textured)

    kept = [(name, path) for name, path in entries if path is not None][:_MAX_BIRDS]
    if not kept:
        draw_perch(canvas, perches, day_ordinal(), textured)
        return canvas
    arts = [trim(path) for _, path in kept]

    # Pack pixels from here down; `scale` takes them to the output.
    scale = min(resolution) / _PACK_SHORT
    width, height = round(resolution[0] / scale), round(resolution[1] / scale)

    names = [name for name, _ in kept]
    flips = [_flip(name) for name in names]
    name_px = label_px(width, height, label_size)
    labels = tuple(label_text(name) for name in names) if show_names else None
    key = (
        tuple((name, str(path)) for name, path in kept),
        width,
        height,
        font_key if show_names else None,
        name_px,
        labels,
        layout,
    )
    placed, used_px = _placements(
        key,
        arts,
        names,
        flips,
        width,
        height,
        font_key if show_names else None,
        name_px,
        label_text,
        layout,
    )

    for p in placed:
        art = _scaled(arts[p.index], max(1, round(p.dim * scale)), flips[p.index])
        proc = process_sprite(art, textured=textured)
        at = _at(p.at, scale)
        canvas.paste(proc, (at[0] - PAD, at[1] - PAD), proc)

    # Names last: halos feather past the collision mask, so a name drawn inline
    # with the birds would be washed over by the next neighbour.
    if used_px:
        font = fonts.load(font_key, max(1, round(used_px * scale)))
        for p in placed:
            if p.label_at is None:
                continue
            mask = text_mask(label_text(names[p.index]), font, not textured)
            at = _at(p.label_at, scale)
            centred = at[0] + round((p.label_w * scale - mask.width) / 2)
            stamp(canvas, mask, (centred, at[1]), textured)

    return canvas


def _at(at: tuple[int, int], scale: float) -> tuple[int, int]:
    return round(at[0] * scale), round(at[1] * scale)


def gather_entries(
    source: Source,
    images_dir: Path,
    style: str,
    picks: Picks,
    hours: int = 24,
) -> list[tuple[str, Path | None]]:
    """Recent-window species paired with the artwork each is wearing, or None.

    In name order, matching the collage's cache key: the page is a function of
    the species set alone, so a count moving must not reshuffle the layout.
    """
    return [
        (name, image_for(name, images_dir, style, picks))
        for name, _count in sorted(source.species_since(hours))
    ]
