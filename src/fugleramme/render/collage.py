"""Kiosk collage: full-color composite of the species seen in the lookback window.

This is the web/kiosk view (also dithered onto the panel). It uses the source
PNGs at full color and packs them by their silhouettes: opaque pixels never
overlap and nothing clips off screen, but the transparent margins are free to
overlap so birds nestle closely. Birds are sized by their real body mass
(compressed, see sizes.py) and placed largest-first on an outward spiral from
the centre, so big birds land in the middle; the whole set is then scaled to
fill the canvas.

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
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from ..db import Database
from ..names import image_for
from ..picks import Picks
from . import fonts
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
_MARGIN = 0.04  # page edge to content on short side. Hardcoded now, maybe add configurability?
_MAX_BIRDS = 40  # keeps the render quick, not the page tidy
_ALPHA_CUTOFF = 24
_OVERLAP_PX = 2  # erode the collision mask slightly so birds nestle into
# each other's (invisible on paper) halos. No rotation:
# it tilts the ground/water on birds drawn with terrain.
_STEP = 6
_ATTEMPTS = 20


def _scaled_sprite(
    img: Image.Image, max_dim: int, flip: bool = False
) -> tuple[Image.Image, np.ndarray]:
    """Scale a trimmed sprite to max_dim on its longest side, optionally mirror
    it, and return it with an eroded opaque mask (bool array, True = keep-clear).
    Eroding lets the paper halos overlap so birds pack a little tighter; their
    bodies still can't. Mirroring (not rotation) adds variety while keeping any
    ground or water level."""
    scale = max_dim / max(img.width, img.height)
    if scale != 1.0:
        img = img.resize(
            (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
            Image.Resampling.LANCZOS,
        )
    if flip:
        img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    mask = img.getchannel("A").point(lambda a: 255 if a > _ALPHA_CUTOFF else 0)
    if _OVERLAP_PX:
        mask = mask.filter(ImageFilter.MinFilter(_OVERLAP_PX * 2 + 1))
    return img, np.asarray(mask, dtype=bool)


@dataclass(frozen=True, eq=False)  # eq: a generated __eq__ would raise on the ndarray
class _Sprite:
    """A bird, and optionally its name, as one packable unit: `mask` is the whole
    footprint, `art_at` and `label_at` locate the two inside it."""

    art: Image.Image
    mask: np.ndarray
    art_at: tuple[int, int] = (0, 0)
    label: Image.Image | None = None
    label_at: tuple[int, int] = (0, 0)


def _spiral(cx: float, cy: float, max_r: float):
    yield cx, cy
    r = _STEP
    while r <= max_r:
        count = max(8, int(2 * math.pi * r / _STEP))
        for i in range(count):
            a = 2 * math.pi * i / count
            yield cx + r * math.cos(a), cy + r * math.sin(a)
        r += _STEP


def _pack(sprites: list[_Sprite], width: int, height: int):
    """Place every sprite with no opaque overlap and fully on-screen, or return
    None if one does not fit. Sprites should be pre-sorted largest-first."""
    occ = np.zeros((height, width), dtype=bool)
    placed = []
    max_r = math.hypot(width, height)
    for sprite in sprites:
        h, w = sprite.mask.shape
        spot = None
        for px, py in _spiral(width / 2, height / 2, max_r):
            x, y = int(px - w / 2), int(py - h / 2)
            if x < 0 or y < 0 or x + w > width or y + h > height:
                continue
            if not (occ[y : y + h, x : x + w] & sprite.mask).any():
                spot = (x, y)
                break
        if spot is None:
            return None
        x, y = spot
        occ[y : y + h, x : x + w] |= sprite.mask
        placed.append((sprite, x, y))
    return placed


def _center(placed, width: int, height: int):
    """Shift the packed cluster so its bounding box is centred on the canvas."""
    xs0 = min(x for _, x, _ in placed)
    ys0 = min(y for _, _, y in placed)
    xs1 = max(x + s.mask.shape[1] for s, x, _ in placed)
    ys1 = max(y + s.mask.shape[0] for s, _, y in placed)
    dx = (width - (xs1 - xs0)) // 2 - xs0
    dy = (height - (ys1 - ys0)) // 2 - ys0
    return [(sprite, x + dx, y + dy) for sprite, x, y in placed]


def _with_label(art: Image.Image, art_mask: np.ndarray, label: Image.Image, gap: int) -> _Sprite:
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
    return _Sprite(art, mask, (ax, 0), label, (lx, top))


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
    arts: list[tuple[str, Image.Image]],
    order: list[int],
    weights: list[float],
    flips: list[bool],
    base: float,
    width: int,
    height: int,
    font_key: str | None,
    name_px: int,
    flat: bool,
    label_text: Callable[[str], str] = str,
):
    """Shrink the set to the first size where every bird, name included, fits.
    Names have to shrink too: a fixed-size name never yields, so a full page of
    them cannot converge at all."""
    labels: list[Image.Image] = []
    last_px = gap = 0
    for attempt in range(_ATTEMPTS):
        shrink = 0.9**attempt
        if font_key:
            px = max(MIN_LABEL_PX, round(name_px * shrink))
            if px != last_px:
                font = fonts.load(font_key, px)
                labels = [text_mask(label_text(arts[i][0]), font, flat) for i in order]
                last_px, gap = px, round(px * 0.35)
        sprites = []
        for n, i in enumerate(order):
            art, mask = _scaled_sprite(
                arts[i][1], max(24, int(base * shrink * weights[i])), flips[i]
            )
            sprites.append(
                _with_label(art, mask, labels[n], gap) if font_key else _Sprite(art, mask)
            )
        placed = _pack(sprites, width, height)
        if placed is not None:
            return _center(placed, width, height)
    return None


def render_collage(
    entries: list[tuple[str, Path | None]],
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    show_names: bool = True,
    textured: bool = True,
    font_key: str = fonts.DEFAULT_FONT,
    label_size: str = fonts.DEFAULT_LABEL_SIZE,
    label_text: Callable[[str], str] = str,
    perches: Sequence[Path] = (),
) -> Image.Image:
    """Composite the given (name, image) entries into a tightly packed collage.

    textured: paper grain for the web, flat paper for the panel, whose dither
    would otherwise turn the grain into noise. It also picks the label ink.
    label_text: scientific name -> what the label reads; str leaves it alone.
    perches: the active style's bare branches, for a page with no birds on it.
    """
    width, height = resolution
    canvas = blank(resolution, textured)

    arts = [(name, trim(path)) for name, path in entries if path is not None][:_MAX_BIRDS]
    if not arts:
        draw_perch(canvas, perches, day_ordinal(), textured)
        return canvas

    # Each bird's target size scales with its real mass (compressed); the whole
    # set then overshoots and shrinks to the first fit that fills the canvas.
    # Placing biggest-first on the center-out spiral keeps large birds central.
    weights = _size_weights([name for name, _ in arts])
    order = sorted(range(len(arts)), key=lambda i: -weights[i])
    flips = [_flip(name) for name, _ in arts]
    base = min(
        math.sqrt(width * height * 1.5 / sum(w * w for w in weights)),
        min(width, height) * 0.7 / max(weights),
    )
    # Pack inside the margin but size off the whole page, so only a set that
    # doesn't fit has to shrink.
    margin = round(min(resolution) * _MARGIN)
    box = (width - 2 * margin, height - 2 * margin)
    args = (arts, order, weights, flips, base, *box)
    name_px = label_px(width, height, label_size)
    placed = _layout(
        *args,
        font_key if show_names else None,
        name_px,
        flat=not textured,
        label_text=label_text,
    )
    if placed is None and show_names:
        log.warning("No layout fits %d species with names at %dx%d", len(arts), *box)
        placed = _layout(*args, None, name_px, flat=not textured)  # birds beat blank paper

    if placed:
        placed = [(sprite, x + margin, y + margin) for sprite, x, y in placed]
        for sprite, x, y in placed:
            ax, ay = sprite.art_at
            proc = process_sprite(sprite.art, textured=textured)
            canvas.paste(proc, (x + ax - PAD, y + ay - PAD), proc)
        _draw_names(canvas, placed, textured)

    return canvas


def _draw_names(canvas, placed, textured: bool) -> None:
    """A second pass: halos feather past the collision mask, so a name drawn
    inline with the birds would be washed over by the next neighbour."""
    for sprite, x, y in placed:
        if sprite.label is None:
            continue
        lx, ly = sprite.label_at
        stamp(canvas, sprite.label, (x + lx, y + ly), textured)


def gather_entries(
    db: Database,
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
        for name, _count in sorted(db.species_since(hours))
    ]
