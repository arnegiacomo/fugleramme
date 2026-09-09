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

Size and centrality are one number, not two: whatever makes a bird bigger also
places it earlier on the spiral. What feeds that number is sizes.py's business.

Nothing here rolls dice per render: a species holds its artwork for as long as
it is in the window (picks.py) and the mirror is a hash of the name, so a bird
is unaffected by which other birds are on the page, or by a restart.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from ..names import drawable_keys, image_for, normalize
from ..picks import Picks
from ..source import Source
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
from .sizes import SIZE_EXPONENT, TIER_STEP, mass_of

log = logging.getLogger(__name__)

DEFAULT_RESOLUTION = (1280, 800)
# Short side the layout is packed at, then scaled to whatever is drawn. The
# packer works in whole pixels, so packing at the output size would put the
# panel and the kiosk on different pages.
_PACK_SHORT = 1200
_MARGIN = 0.04  # page edge to content on short side. Hardcoded now, maybe add configurability?
# The frame's own ceiling whatever the admin asks for: a render is ~90% packing
# and the Pi has to finish it. Keeps the render quick, not the page tidy.
MAX_BIRDS = 40

# How many species the admin lets on, and which ones (#53). NO_LIMIT still means
# "every bird the window holds", not "however long the Pi takes to draw them".
NO_LIMIT = 0
LIMIT_OPTIONS = (NO_LIMIT, 5, 8, 10, 12, 15, 20, 30)
RANK_MOST_HEARD = "heard"
RANK_RAREST = "rarest"
RANKINGS = {
    RANK_MOST_HEARD: "The most heard",
    RANK_RAREST: "The rarest",  # at a busy station the visitor is the interesting one
}
DEFAULT_RANKING = RANK_MOST_HEARD
_ALPHA_CUTOFF = 24
_OVERLAP_PX = 2  # erode the collision mask slightly so birds nestle into
# each other's (invisible on paper) halos. No rotation:
# it tilts the ground/water on birds drawn with terrain.
_STEP = 6
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


def _spiral(cx: float, cy: float, max_r: float):
    yield cx, cy
    r = _STEP
    while r <= max_r:
        count = max(8, int(2 * math.pi * r / _STEP))
        for i in range(count):
            a = 2 * math.pi * i / count
            yield cx + r * math.cos(a), cy + r * math.sin(a)
        r += _STEP


_PROBE_BANDS = 3


def _probes(mask: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """One row per horizontal band of a sprite, tested before its whole footprint.
    Most candidate positions on a filling page collide, and a row costs a
    hundredth of the box. Banded rather than simply the densest rows, which all
    land in the body and catch the same collisions as each other."""
    density = mask.sum(axis=1)
    probes = []
    for band in np.array_split(np.arange(len(density)), _PROBE_BANDS):
        if band.size and density[band].max():
            row = int(band[int(np.argmax(density[band]))])
            probes.append((row, mask[row]))
    return probes


def _pack(sprites: list[_Sprite], width: int, height: int):
    """Place every sprite with no opaque overlap and fully on-screen, or return
    None if one does not fit. Sprites should be pre-sorted largest-first."""
    occ = np.zeros((height, width), dtype=bool)
    placed = []
    max_r = math.hypot(width, height)
    for sprite in sprites:
        h, w = sprite.mask.shape
        probes = _probes(sprite.mask)
        spot = None
        for px, py in _spiral(width / 2, height / 2, max_r):
            x, y = int(px - w / 2), int(py - h / 2)
            if x < 0 or y < 0 or x + w > width or y + h > height:
                continue
            # A colliding probe row is a real collision, so this only ever skips
            # the box test for positions it would have rejected anyway.
            if any((occ[y + r, x : x + w] & row).any() for r, row in probes):
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


def _geometric(values: list[float]) -> float:
    return math.exp(sum(math.log(v) for v in values) / len(values))


def _size_weights(names: list[str], tiers: Mapping[str, int]) -> list[float]:
    """Per-bird display weight from real mass, optionally multiplied by how often
    the bird has been heard (`tiers`; empty means mass alone).

    Each factor is divided by the set's geometric mean, so it only ever says how
    a bird compares to its neighbours. That is what keeps the two composable and
    keeps `base`, which sizes the cluster to the page, from drifting.
    """
    masses = [mass_of(n) for n in names]
    geo = _geometric(masses)
    weights = [(m / geo) ** SIZE_EXPONENT for m in masses]
    if not tiers:
        return weights
    heard = [float(TIER_STEP ** tiers.get(n, 0)) for n in names]
    loud = _geometric(heard)
    return [w * h / loud for w, h in zip(weights, heard, strict=True)]


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
):
    """Shrink the set to the first size where every bird, name included, fits,
    and return the placements with the name size they were reserved at. Names
    have to shrink too: a fixed-size name never yields, so a full page of them
    cannot converge at all."""
    labels: list[Image.Image] = []
    last_px = gap = 0
    for attempt in range(_ATTEMPTS):
        shrink = 0.9**attempt
        if font_key:
            px = max(MIN_LABEL_PX, round(name_px * shrink))
            if px != last_px:
                font = fonts.load(font_key, px)
                # Only the size is packed; the draw pass re-rasterizes.
                labels = [text_mask(label_text(names[i]), font, False) for i in order]
                last_px, gap = px, round(px * 0.35)
        sprites = []
        for n, i in enumerate(order):
            dim = max(24, int(base * shrink * weights[i]))
            mask = _footprint(_scaled(alphas[i], dim, flips[i]))
            sprites.append(
                _with_label(i, dim, mask, labels[n], gap) if font_key else _Sprite(i, dim, mask)
            )
        placed = _pack(sprites, width, height)
        if placed is not None:
            return _center(placed, width, height), last_px
    return None, 0


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
    tiers: Mapping[str, int],
    flips: list[bool],
    width: int,
    height: int,
    font_key: str | None,
    name_px: int,
    label_text: Callable[[str], str],
) -> tuple[tuple[_Placed, ...], int]:
    """Pack the page, or return the cached packing. The panel and the kiosk pack
    identically - only `scale` and the paper differ - so whichever renders first
    pays for both. The lock is held across the pack for the same reason: the
    second caller should wait for the first rather than pack its own copy."""
    with _layouts_lock:
        hit = _layouts.get(key)
        if hit is not None:
            return hit

        # Each bird's target size scales with its real mass (compressed), and
        # optionally with how often it was heard; the whole set then overshoots
        # and shrinks to the first fit. Biggest-first on the spiral keeps the
        # birds that earned the most size central.
        weights = _size_weights(names, tiers)
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

        placed, used_px = _layout(*args, font_key, name_px, label_text=label_text)
        if placed is None and font_key:
            log.warning("No layout fits %d species with names at %dx%d", len(names), *box)
            placed, used_px = _layout(*args, None, name_px)  # birds beat blank paper

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
    tiers: Mapping[str, int] | None = None,
) -> Image.Image:
    """Composite the given (name, image) entries into a tightly packed collage.

    textured: paper grain for the web, flat paper for the panel, whose dither
    would otherwise turn the grain into noise. It also picks the label ink.
    label_text: scientific name -> what the label reads; str leaves it alone.
    perches: the active style's bare branches, for a page with no birds on it.
    tiers: how often each species was heard, in bands (sizes.count_tiers);
    empty sizes the page by body mass alone, which is the default.
    """
    canvas = blank(resolution, textured)

    kept = [(name, path) for name, path in entries if path is not None][:MAX_BIRDS]
    if not kept:
        draw_perch(canvas, perches, day_ordinal(), textured)
        return canvas
    arts = [trim(path) for _, path in kept]

    # Pack pixels from here down; `scale` takes them to the output.
    scale = min(resolution) / _PACK_SHORT
    width, height = round(resolution[0] / scale), round(resolution[1] / scale)

    names = [name for name, _ in kept]
    # Narrowed to the birds actually drawn; the window's bands cover more.
    heard = {name: tiers[name] for name in names if name in tiers} if tiers else {}
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
        # In the key because they change the sizes, and so the whole packing.
        tuple(sorted(heard.items())),
    )
    placed, used_px = _placements(
        key,
        arts,
        names,
        heard,
        flips,
        width,
        height,
        font_key if show_names else None,
        name_px,
        label_text,
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


def _rank(ranking: str):
    """Sort key that puts the birds the admin asked to keep first. Ties break on
    the name, so a page at its limit does not flicker between two equal birds."""
    if ranking == RANK_RAREST:
        return lambda pair: (pair[1], pair[0])
    return lambda pair: (-pair[1], pair[0])


def selected_species(
    source: Source,
    images_dir: Path,
    style: str,
    hours: int = 24,
    limit: int = NO_LIMIT,
    ranking: str = DEFAULT_RANKING,
) -> list[str]:
    """The species that make the page, in name order.

    Name order because the order birds are handed over must not depend on their
    counts - a bird merely heard again would reshuffle the whole packing. Which
    birds are on it does depend on the counts once a limit is set, so the page's
    key is built from this same list.

    The ranking only applies under a limit, as the admin says: with none set the
    frame's own ceiling keeps the most heard, whatever the greyed-out field holds.

    What the style cannot draw is dropped before the limit, so a plate the frame
    does not have never takes one of the places. One directory listing, not a
    probe per species: the loop asks for this on every poll, and so does the
    kiosk.
    """
    keys = drawable_keys(images_dir, style)
    counted = [(name, n) for name, n in source.species_since(hours) if normalize(name) in keys]
    if limit == NO_LIMIT:
        limit, ranking = MAX_BIRDS, DEFAULT_RANKING
    ranked = sorted(counted, key=_rank(ranking))
    return sorted(name for name, _n in ranked[: min(limit, MAX_BIRDS)])


def gather_entries(
    source: Source,
    images_dir: Path,
    style: str,
    picks: Picks,
    hours: int = 24,
    limit: int = NO_LIMIT,
    ranking: str = DEFAULT_RANKING,
) -> list[tuple[str, Path | None]]:
    """The page's species paired with the artwork each is wearing. The None only
    stands for a file that vanished between `selected_species` and here."""
    return [
        (name, image_for(name, images_dir, style, picks))
        for name in selected_species(source, images_dir, style, hours, limit, ranking)
    ]
