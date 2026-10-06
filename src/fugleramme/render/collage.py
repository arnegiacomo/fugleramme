"""Kiosk collage: full-color composite of the species seen in the lookback window.

This is the web/kiosk view (also dithered onto the panel). It uses the source
PNGs at full color and packs them by their silhouettes: opaque pixels never
overlap and nothing clips off screen, but the transparent margins are free to
overlap so birds nestle closely. Birds are sized by their real body mass
(compressed, see sizes.py) and placed largest-first by the packer
`settings.layout` picks (packing.py); the default spiral works outward from the
centre, so big birds land in the middle. The whole set is then scaled to fill
the canvas.

Species with no artwork are omitted (there is nothing to draw for them once
names are off). The name label is an admin toggle, on by default, and reads in
the admin's chosen language(s); it packs as part of its bird, tucked up under
the silhouette, so a name can never land on a neighbour or clip. As a numbered
key, each bird gets a number there instead and the names are listed beside or
below the birds.

Nothing here rolls dice per render: a species holds its artwork for as long as
it is in the window (picks.py) and the mirror is a hash of the name, so a bird
is unaffected by which other birds are on the page, or by a restart.
"""

from __future__ import annotations

import hashlib
import logging
import math
import threading
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from functools import cache
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..names import canonical, drawable_keys, image_for, normalize
from ..picks import Picks
from ..source import Source
from . import fonts, packing
from .page import (
    MIN_LABEL_PX,
    NEW,
    NO_MARGIN,
    Edges,
    blank,
    day_ordinal,
    draw_mark,
    draw_perch,
    figures_mask,
    flatten,
    label_px,
    mark_room,
    stamp,
    text_mask,
    trim,
)
from .paper import PAD, process_sprite
from .sizes import SIZE_EXPONENT, bird_centre, mass_of, span_ratio

log = logging.getLogger(__name__)

DEFAULT_RESOLUTION = (1280, 800)
# Short side the layout is packed at, then scaled to whatever is drawn. The
# packer works in whole pixels, so packing at the output size would put the
# panel and the kiosk on different pages.
_PACK_SHORT = 1200
DEFAULT_MARGIN = 0.04  # page edge to content, fraction of the short side (settings.margin)
_DEFAULT_EDGES = Edges.even(DEFAULT_MARGIN)
# How many species the admin lets on, and which ones (#53). NO_LIMIT is every
# bird the window holds - the frame keeps no ceiling of its own.
NO_LIMIT = 0
KEY_LIMIT = 40  # a key of more names than this no longer fits beside the birds
RANK_MOST_HEARD = "heard"
RANK_RAREST = "rarest"
RANK_RAREST_EVER = "rarest_ever"
RANKINGS = {
    RANK_MOST_HEARD: "The most heard",
    RANK_RAREST: "The rarest in the window",
    RANK_RAREST_EVER: "The rarest all time",
}
DEFAULT_RANKING = RANK_MOST_HEARD
_ALPHA_CUTOFF = 24
_OVERLAP_PX = 2  # erode the collision mask slightly so birds nestle into
# each other's (invisible on paper) halos. No rotation:
# it tilts the ground/water on birds drawn with terrain.
_ATTEMPTS = 20
_MAX_SHARE = 0.7  # the most of the short side one plate may take
# The spotlit bird's own span, of the short side of the paper it packs into:
# not sized by mass, so a wren in the middle is not tiny.
SPOTLIGHT_SHARE = 0.6
SPOTLIGHT_GAP = 0.05  # bare paper kept round it, of its own size
SPOTLIGHT_LABEL = 1.5  # its name, against the other birds' names
_KEY_SHARE = 0.4  # the most of the page the key may take, across its depth
_KEY_LEADING = 1.2  # the key's line height, em

# (text, font, flat) -> the label's alpha mask, as page.text_mask draws it.
_Mask = Callable[[str, ImageFont.FreeTypeFont, bool], Image.Image]


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
    eroded = np.asarray(mask.filter(ImageFilter.MinFilter(_OVERLAP_PX * 2 + 1)), dtype=bool)
    # A bird thinner than the erosion would reserve nothing and be packed over.
    return eroded if eroded.any() else np.asarray(mask, dtype=bool)


def _grow(mask: np.ndarray, px: int) -> np.ndarray:
    """`mask` dilated by a `px` square, padded to hold it. The shifts double up,
    so a wide gap costs a handful of passes rather than one per pixel."""
    out = np.pad(mask, px)
    for axis in (0, 1):
        reach = 0
        while reach < px:
            # The padding is clear, so what a roll wraps round is clear too.
            step = min(max(reach, 1), px - reach)
            out = out | np.roll(out, step, axis) | np.roll(out, -step, axis)
            reach += step
    return out


def _spaced(sprite: _Sprite, gap: int) -> _Sprite:
    """The sprite with `gap` of bare paper kept clear all round it, name included."""

    def moved(at: tuple[int, int]) -> tuple[int, int]:
        return at[0] + gap, at[1] + gap

    label_at = None if sprite.label_at is None else moved(sprite.label_at)
    return replace(
        sprite, mask=_grow(sprite.mask, gap), art_at=moved(sprite.art_at), label_at=label_at
    )


def _held(pin: _Pin, alpha: Image.Image, flip: bool) -> tuple[np.ndarray, tuple[int, int]]:
    """A pinned bird's footprint, and where the bird's own middle is on its art."""
    art = _footprint(_scaled(alpha, pin.dim, flip))
    fx, fy = pin.centre
    return art, (round((1 - fx if flip else fx) * art.shape[1]), round(fy * art.shape[0]))


class _Pin(NamedTuple):
    """The bird held in the middle at a fixed size, while the rest shrink round it."""

    entry: int
    dim: int
    centre: tuple[float, float]  # the bird on its plate, as `sizes.bird_centre` has it


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
    label_text: Callable[[str], str],
    layout: str,
    mask_of: _Mask = text_mask,
    pin: _Pin | None = None,
):
    """Shrink the set until every bird, name included, fits, then bisect back
    toward the size that failed, for as many steps as the layout affords.
    Returns the placements with the name size they were reserved at. Names have
    to shrink too: a fixed-size name never yields, so a full page of them cannot
    converge at all. A `pin` comes first in `order`."""
    chosen = packing.layout_of(layout)
    art, centre_at = _held(pin, alphas[pin.entry], flips[pin.entry]) if pin else (None, (0, 0))

    @cache  # a midpoint often lands back on a size already rasterized
    def rasterize(px: int) -> tuple[list[Image.Image], int]:
        if not font_key:
            return [], 0
        font = fonts.load(font_key, px)  # only the size is packed; the draw pass re-rasterizes
        return [mask_of(label_text(names[i]), font, False) for i in order], round(px * 0.35)

    @cache  # the pinned bird only changes with its name's size
    def held(px: int) -> _Sprite:
        assert pin is not None and art is not None
        named = None
        if font_key:
            big = round(px * SPOTLIGHT_LABEL)
            label = mask_of(label_text(names[pin.entry]), fonts.load(font_key, big), False)
            named = _with_label(pin.entry, pin.dim, art, label, round(big * 0.35))
        # Its name keeps its usual place; the gap holds the neighbours off both.
        return _spaced(named or _Sprite(pin.entry, pin.dim, art), round(pin.dim * SPOTLIGHT_GAP))

    def attempt(shrink: float):
        px = max(MIN_LABEL_PX, round(name_px * shrink)) if font_key else 0
        labels, spacing = rasterize(px)
        sprites = []
        for n, i in enumerate(order):
            if pin and i == pin.entry:
                sprites.append(held(px))
                continue
            dim = max(24, int(base * shrink * weights[i]))
            mask = _footprint(_scaled(alphas[i], dim, flips[i]))
            sprites.append(
                _with_label(i, dim, mask, labels[n], spacing) if font_key else _Sprite(i, dim, mask)
            )
        anchor = _at(sprites[0].art_at, 1, centre_at) if pin else None
        placed = chosen.pack(sprites, width, height, anchor)
        if placed is None:
            return None
        return (placed if pin else _center(placed, width, height)), px

    fit = None
    failed = None  # the smallest size that did not fit, if any did
    for step in range(_ATTEMPTS):
        shrink = 0.9**step
        fit = attempt(shrink)
        if fit is not None:
            break
        failed = shrink
    if fit is None:
        return None, 0
    if failed is None:
        return fit  # nothing failed: `base` was already the ceiling

    # The descent lands up to a tenth under what the page could hold, and the
    # gap is bare paper, so bisect back into the size that failed.
    small, large = shrink, failed
    for _ in range(chosen.refine):
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
    ratios: list[float],
    flips: list[bool],
    width: int,
    height: int,
    font_key: str | None,
    name_px: int,
    label_text: Callable[[str], str],
    layout: str,
    margin: Edges,
    mask_of: _Mask,
    spotlit: tuple[int, tuple[float, float]] | None = None,
) -> tuple[tuple[_Placed, ...], int]:
    """Pack the page, or return the cached packing. A kiosk locked to the panel
    packs identically to it - only `scale` and the paper differ - so whichever
    renders first pays for both. The lock is held across the pack for the same
    reason: the second caller should wait for the first rather than pack its own copy."""
    with _layouts_lock:
        hit = _layouts.get(key)
        if hit is not None:
            return hit

        # Pack inside the margin but size off the whole page, so only a set that
        # doesn't fit has to shrink.
        x0, y0, x1, y1 = margin.window((width, height))
        box = (x1 - x0, y1 - y0)

        # Each bird's target size scales with its real mass (compressed); the whole
        # set then overshoots and shrinks until it fits the canvas, biggest first.
        # The ratio rides in the weight, so `base` below still measures what is drawn.
        rest = [i for i in range(len(names)) if not spotlit or i != spotlit[0]]
        mass = dict(zip(rest, _size_weights([names[i] for i in rest]), strict=True)) if rest else {}
        weights = [mass.get(i, 0.0) * r for i, r in enumerate(ratios)]
        order = sorted(rest, key=lambda i: -weights[i])
        base = (
            min(
                math.sqrt(width * height * 1.5 / sum(weights[i] ** 2 for i in rest)),
                min(width, height) * _MAX_SHARE / max(weights[i] for i in rest),
            )
            if rest
            else 0.0
        )
        pin = None
        if spotlit:
            index, centre = spotlit
            share = min(SPOTLIGHT_SHARE * ratios[index], _MAX_SHARE)
            pin = _Pin(index, round(share * min(box)), centre)
            order = [index, *order]
        alphas = [img.getchannel("A") for img in arts]
        args = (names, alphas, order, weights, flips, base, *box)

        placed, used_px = _layout(*args, font_key, name_px, label_text, layout, mask_of, pin)
        if placed is None and font_key:  # birds beat blank paper
            log.warning("No layout fits %d species with names at %dx%d", len(names), *box)
            placed, used_px = _layout(*args, None, name_px, label_text, layout, mask_of, pin)

        result = (
            tuple(
                _Placed(
                    s.index,
                    s.dim,
                    (x + x0 + s.art_at[0], y + y0 + s.art_at[1]),
                    None
                    if s.label_at is None
                    else (x + x0 + s.label_at[0], y + y0 + s.label_at[1]),
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
    margin: Edges = _DEFAULT_EDGES,
    name_key: bool = False,
    spotlight: str | None = None,
) -> Image.Image:
    """Composite the given (name, image) entries into a tightly packed collage.

    textured: paper grain for the web, flat paper for the panel, whose dither
    would otherwise turn the grain into noise. It also picks the label ink.
    label_text: scientific name -> what the label reads; str leaves it alone.
    perches: the active style's bare branches, for a page with no birds on it.
    layout: how the birds are packed (packing.LAYOUTS).
    margin: bare paper along each edge, as fractions of the short side.
    name_key: with names on, number the birds and list the names in a key.
    spotlight: the entry drawn large in the middle, the rest packed round it.
    """
    canvas = blank(resolution, textured)

    kept = [(name, path) for name, path in entries if path is not None]
    if not kept:
        draw_perch(canvas, perches, day_ordinal(), textured)
        return canvas
    if show_names and name_key:
        _draw_keyed(
            canvas, kept, textured, font_key, label_size, label_text, layout, margin, spotlight
        )
        return canvas

    # Pack pixels from here down; `scale` takes them to the output.
    scale = min(resolution) / _PACK_SHORT
    pack = (round(resolution[0] / scale), round(resolution[1] / scale))
    names = [name for name, _ in kept]
    placed, used_px = _draw_birds(
        canvas,
        kept,
        (0, 0),
        pack,
        scale,
        textured,
        font_key if show_names else None,
        label_px(*pack, label_size),
        label_text,
        layout,
        margin,
        spotlight=spotlight,
    )
    # Names last: halos feather past the collision mask, so a name drawn inline
    # with the birds would be washed over by the next neighbour.
    if used_px:
        font = fonts.load(font_key, max(1, round(used_px * scale)))
        texts = {p.index: label_text(names[p.index]) for p in placed}
        held = names.index(spotlight) if spotlight in names else None
        _stamp_labels(canvas, placed, texts, font, scale, (0, 0), textured, held=held)
    return canvas


def _draw_birds(
    canvas: Image.Image,
    kept: list[tuple[str, Path]],
    origin: tuple[int, int],
    pack: tuple[int, int],
    scale: float,
    textured: bool,
    font_key: str | None,
    name_px: int,
    label_text: Callable[[str], str],
    layout: str,
    margin: Edges,
    mask_of: _Mask = text_mask,
    spotlight: str | None = None,
) -> tuple[tuple[_Placed, ...], int]:
    """Pack the birds into a `pack` box and draw them at `origin`, `scale`
    times larger, labels reserved but not drawn. Returns the placements and
    the label size they packed at."""
    arts = [trim(path) for _, path in kept]
    # Mass sizes the bird; this sizes the plate it is drawn on.
    ratios = [span_ratio(path, art.size) for (_, path), art in zip(kept, arts, strict=True)]
    width, height = pack

    names = [name for name, _ in kept]
    flips = [_flip(name) for name in names]
    labels = tuple(label_text(name) for name in names) if font_key else None
    key = (
        tuple((name, str(path)) for name, path in kept),
        width,
        height,
        font_key,
        name_px,
        labels,
        layout,
        margin,
        spotlight,
    )
    placed, used_px = _placements(
        key,
        arts,
        names,
        ratios,
        flips,
        width,
        height,
        font_key,
        name_px,
        label_text,
        layout,
        margin,
        mask_of,
        _spotlit(kept, arts, spotlight),
    )

    for p in placed:
        art = _scaled(arts[p.index], max(1, round(p.dim * scale)), flips[p.index])
        at = _at(p.at, scale, origin)
        corner = (at[0] - PAD, at[1] - PAD)
        proc = process_sprite(art, corner, textured=textured)
        canvas.paste(proc, corner, proc)
    return placed, used_px


def _spotlit(
    kept: list[tuple[str, Path]], arts: list[Image.Image], spotlight: str | None
) -> tuple[int, tuple[float, float]] | None:
    """The spotlit entry's index and where its bird is on the plate, if it is on the page."""
    names = [name for name, _ in kept]
    if spotlight not in names:
        return None
    index = names.index(spotlight)
    return index, bird_centre(kept[index][1], arts[index].size)


def _stamp_labels(
    canvas: Image.Image,
    placed: Iterable[_Placed],
    texts: dict[int, str],
    font: ImageFont.FreeTypeFont,
    scale: float,
    origin: tuple[int, int],
    textured: bool,
    mask_of: _Mask = text_mask,
    held: int | None = None,
) -> None:
    """Each text centred in the box its bird reserved for it, the `held` bird's
    set larger as it was packed."""
    larger = fonts.resized(font, round(font.size * SPOTLIGHT_LABEL))
    for p in placed:
        if p.label_at is None:
            continue
        mask = mask_of(texts[p.index], larger if p.index == held else font, not textured)
        at = _at(p.label_at, scale, origin)
        centred = at[0] + round((p.label_w * scale - mask.width) / 2)
        stamp(canvas, mask, (centred, at[1]), textured)


@dataclass(frozen=True)
class _Key:
    """The key's grid, in output pixels: numbers right-aligned in their own
    column, names after, filled down each column first."""

    px: int
    rows: int
    line: int
    entry: int  # one name's lines, and the space after it
    num_w: int
    space: int
    col_w: int  # one entry, gutter included
    below: bool
    area: tuple[int, int, int, int]  # the page the key has, beside or below the birds


def _fit_key(
    texts: list[list[str]], font_key: str, px: int, box: tuple[int, int, int, int]
) -> tuple[_Key, tuple[int, int, int, int]]:
    """Lay the key out in pack pixels below a portrait page's birds or beside a
    landscape one's, shrinking its type until it takes no more than `_KEY_SHARE`
    of the page. Returns the key and the box left for the birds."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    below = bh > bw
    depth = max(len(t) for t in texts)
    while True:
        font = fonts.load(font_key, px)
        line = round(px * _KEY_LEADING)
        # Air between two-line names, or one reads as its neighbour's.
        entry = depth * line + (round(line * 0.25) if depth > 1 else 0)
        num_w = math.ceil(font.getlength(f"{len(texts)}."))
        space = round(px * 0.4)
        gutter = round(px * 1.2)
        widest = max(_line_width(part, font) for t in texts for part in t)
        col_w = num_w + space + math.ceil(widest) + gutter
        # The last entry ends at its descenders, not its leading.
        last = (depth - 1) * line + sum(font.getmetrics())
        if below:
            cols = max(1, min(len(texts), (bw + gutter) // col_w))
        else:
            cols = math.ceil(len(texts) / max(1, (bh - last) // entry + 1))
        rows = math.ceil(len(texts) / cols)
        kw, kh = cols * col_w - gutter, (rows - 1) * entry + last
        taken, room = (kh, bh) if below else (kw, bw)
        if taken <= room * _KEY_SHARE or px <= MIN_LABEL_PX:
            break
        px -= 1
    if below:
        area, birds = (x0, y1 - kh, x1, y1), (x0, y0, x1, y1 - kh - gutter)
    else:
        area, birds = (x1 - kw, y0, x1, y1), (x0, y0, x1 - kw - gutter, y1)
    return _Key(px, rows, line, entry, num_w, space, col_w, below, area), birds


def _line_width(line: str, font: ImageFont.FreeTypeFont) -> float:
    """A key line's width in the face it is set in, its mark included."""
    text = line.removesuffix(NEW)
    face = fonts.face(text, font)
    return face.getlength(text) + (mark_room(face) if text != line else 0)


def _reading_order(placed: Sequence[_Placed], width: int, height: int) -> list[_Placed]:
    """Left to right in bands down the page, the way a plate's key is numbered."""
    rows = max(1, round(math.sqrt(len(placed) * height / width)))
    band = height / rows

    def spot(p: _Placed) -> tuple[int, float]:
        x, y = p.label_at or p.at
        return int(y // band), x + p.label_w / 2

    return sorted(placed, key=spot)


def _numbered(
    placed: Sequence[_Placed], width: int, height: int, held: int | None
) -> list[_Placed]:
    """The key's order: a spotlit bird is number 1, the rest follow in reading order."""
    return sorted(_reading_order(placed, width, height), key=lambda p: p.index != held)


def _figures_box(count: int) -> _Mask:
    """Room for any number up to `count`, as `figures_mask` draws it."""

    @cache  # one font per packed size, asked once per bird
    def sized(font: ImageFont.FreeTypeFont) -> Image.Image:
        numbers = [figures_mask(str(n), font, False) for n in range(1, count + 1)]
        return Image.new("L", (max(m.width for m in numbers), numbers[0].height), 255)

    return lambda _text, font, _flat: sized(font)


def _draw_keyed(
    canvas: Image.Image,
    kept: list[tuple[str, Path]],
    textured: bool,
    font_key: str,
    label_size: str,
    label_text: Callable[[str], str],
    layout: str,
    margin: Edges,
    spotlight: str | None = None,
) -> None:
    """The birds with a number each, and their names in a key. The key is fitted
    in pack pixels like the birds, so every output of one page gets one layout."""
    w, h = canvas.size
    scale = min(w, h) / _PACK_SHORT
    pw, ph = round(w / scale), round(h / scale)
    texts = [label_text(name).split("\n") for name, _ in kept]
    key, (bx0, by0, bx1, by1) = _fit_key(
        texts, font_key, label_px(pw, ph, label_size), margin.window((pw, ph))
    )

    # Numbering waits on the pack, so every bird reserves room for any number.
    count = len(kept)
    origin = _at((bx0, by0), scale)
    placed, used_px = _draw_birds(
        canvas,
        kept,
        origin,
        (bx1 - bx0, by1 - by0),
        scale,
        textured,
        font_key,
        label_px(pw, ph, label_size),
        lambda _: f"1-{count}",  # only the cache key reads this
        layout,
        NO_MARGIN,
        _figures_box(count),
        spotlight,
    )
    held = next((i for i, (name, _) in enumerate(kept) if name == spotlight), None)
    order = _numbered(placed, bx1 - bx0, by1 - by0, held)
    if used_px:
        font = fonts.load(font_key, max(1, round(used_px * scale)))
        numbers = {p.index: str(n) for n, p in enumerate(order, 1)}
        _stamp_labels(canvas, order, numbers, font, scale, origin, textured, figures_mask, held)

    pad = max(1, round(key.px * scale))  # also room for the italic's overhang, cropped off below
    font = fonts.load(font_key, pad)
    ascent = font.getmetrics()[0]
    ax0, ay0, ax1, ay1 = (round(v * scale) for v in key.area)
    mask = Image.new("L", (ax1 - ax0 + 2 * pad, ay1 - ay0 + 2 * pad), 0)
    draw = ImageDraw.Draw(mask)
    for n, p in enumerate(order):
        col, row = divmod(n, key.rows)
        x = pad + round((col * key.col_w + key.num_w) * scale)
        y = pad + round(row * key.entry * scale) + ascent
        draw.text((x, y), f"{n + 1}.", font=font, fill=255, anchor="rs")
        for k, part in enumerate(texts[p.index]):
            at = (x + round(key.space * scale), y + round(k * key.line * scale))
            line = part.removesuffix(NEW)
            face = fonts.face(line, font)
            draw.text(at, line, font=face, fill=255, anchor="ls")
            if line != part:
                draw_mark(mask, at[0] + face.getlength(line), at[1], face)
    mask = mask if textured else flatten(mask)
    # Anchored by its ink to the page edge: the metrics miss the italic's overhang.
    ink = mask.crop(mask.getbbox())
    _, _, right, bottom = margin.window((w, h))
    if key.below:
        at = ((ax0 + ax1 - ink.width) // 2, bottom - ink.height)
    else:
        at = (right - ink.width, (ay0 + ay1 - ink.height) // 2)
    stamp(canvas, ink, at, textured)


def _at(at: tuple[int, int], scale: float, origin: tuple[int, int] = (0, 0)) -> tuple[int, int]:
    return origin[0] + round(at[0] * scale), origin[1] + round(at[1] * scale)


def _rank(ranking: str):
    """Sort key for the birds the admin asked to keep. Ties break on the name, so
    a page at its limit does not flicker between two equally-heard birds."""
    if ranking == RANK_MOST_HEARD:
        return lambda pair: (-pair[1], pair[0])
    return lambda pair: (pair[1], pair[0])  # both rarest rankings


def _by_species(counts: Iterable[tuple[str, int]]) -> dict[str, int]:
    """Counts under one name per bird. `api` already folds a reclassified
    species' two summary rows together; this is what stops anything else that
    hands the page both spellings from drawing the bird twice."""
    folded: dict[str, int] = {}
    for name, count in counts:
        current = canonical(name)
        folded[current] = folded.get(current, 0) + count
    return folded


def selected_species(
    source: Source,
    images_dir: Path,
    style: str,
    hours: float = 24,
    limit: int = NO_LIMIT,
    ranking: str = DEFAULT_RANKING,
    keys: set[str] | None = None,
    spotlight: str | None = None,
) -> list[str]:
    """The species that make the page, in name order.

    `spotlight` takes a place ahead of the ranking if the window heard it.

    Name order because the packing must not depend on the counts - a bird merely
    heard again would reshuffle the page. Which birds are on it does depend on
    them under a limit, so the page's key is built from this same list.

    What the style cannot draw is dropped before the limit, so a missing plate
    never takes one of the places. `keys` is that listing, already paid for.
    """
    if keys is None:
        keys = drawable_keys(images_dir, style)
    heard = _by_species(source.species_since(hours))
    counted = [(name, n) for name, n in heard.items() if normalize(name) in keys]
    if limit == NO_LIMIT:
        return sorted(name for name, _n in counted)  # nothing to rank: they all fit
    if ranking == RANK_RAREST_EVER:
        # A resident heard twice today is not a rarity; a first-timer is.
        ever = _by_species(source.species_since(0))  # 0 hours: the whole record
        counted = [(name, ever.get(name, n)) for name, n in counted]
    lead = canonical(spotlight) if spotlight else None
    first = [name for name, _n in counted if name == lead]
    rest = [pair for pair in counted if pair[0] != lead]
    ranked = sorted(rest, key=_rank(ranking))[: limit - len(first)]
    return sorted(first + [name for name, _n in ranked])


def gather_entries(
    source: Source,
    images_dir: Path,
    style: str,
    picks: Picks,
    hours: float = 24,
    limit: int = NO_LIMIT,
    ranking: str = DEFAULT_RANKING,
    spotlight: str | None = None,
) -> list[tuple[str, Path | None]]:
    """The page's species paired with the artwork each is wearing. The None only
    stands for a file that vanished between `selected_species` and here."""
    return [
        (name, image_for(name, images_dir, style, picks))
        for name in selected_species(
            source, images_dir, style, hours, limit, ranking, spotlight=spotlight
        )
    ]
