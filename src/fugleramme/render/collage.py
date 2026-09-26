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
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ..names import canonical, drawable_keys, image_for, normalize
from ..picks import Picks
from ..source import Source
from . import fonts, packing
from .page import (
    MIN_LABEL_PX,
    blank,
    day_ordinal,
    draw_perch,
    flatten,
    label_px,
    stamp,
    text_mask,
    trim,
)
from .paper import PAD, process_sprite
from .sizes import SIZE_EXPONENT, mass_of, span_ratio

log = logging.getLogger(__name__)

DEFAULT_RESOLUTION = (1280, 800)
# Short side the layout is packed at, then scaled to whatever is drawn. The
# packer works in whole pixels, so packing at the output size would put the
# panel and the kiosk on different pages.
_PACK_SHORT = 1200
DEFAULT_MARGIN = 0.04  # page edge to content, fraction of the short side (settings.margin)
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
_KEY_SHARE = 0.4  # the most of the page the key may take, across its depth
_KEY_LEADING = 1.2  # the key's line height, em


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
):
    """Shrink the set until every bird, name included, fits, then bisect back
    toward the size that failed, for as many steps as the layout affords.
    Returns the placements with the name size they were reserved at. Names have
    to shrink too: a fixed-size name never yields, so a full page of them cannot
    converge at all."""
    chosen = packing.layout_of(layout)

    @cache  # a midpoint often lands back on a size already rasterized
    def rasterize(px: int) -> tuple[list[Image.Image], int]:
        if not font_key:
            return [], 0
        font = fonts.load(font_key, px)  # only the size is packed; the draw pass re-rasterizes
        return [text_mask(label_text(names[i]), font, False) for i in order], round(px * 0.35)

    def attempt(shrink: float):
        px = max(MIN_LABEL_PX, round(name_px * shrink)) if font_key else 0
        labels, gap = rasterize(px)
        sprites = []
        for n, i in enumerate(order):
            dim = max(24, int(base * shrink * weights[i]))
            mask = _footprint(_scaled(alphas[i], dim, flips[i]))
            sprites.append(
                _with_label(i, dim, mask, labels[n], gap) if font_key else _Sprite(i, dim, mask)
            )
        placed = chosen.pack(sprites, width, height)
        return None if placed is None else (_center(placed, width, height), px)

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
    margin: float,
) -> tuple[tuple[_Placed, ...], int]:
    """Pack the page, or return the cached packing. A kiosk locked to the panel
    packs identically to it - only `scale` and the paper differ - so whichever
    renders first pays for both. The lock is held across the pack for the same
    reason: the second caller should wait for the first rather than pack its own copy."""
    with _layouts_lock:
        hit = _layouts.get(key)
        if hit is not None:
            return hit

        # Each bird's target size scales with its real mass (compressed); the whole
        # set then overshoots and shrinks until it fits the canvas, biggest first.
        # The ratio rides in the weight, so `base` below still measures what is drawn.
        weights = [w * r for w, r in zip(_size_weights(names), ratios, strict=True)]
        order = sorted(range(len(names)), key=lambda i: -weights[i])
        base = min(
            math.sqrt(width * height * 1.5 / sum(w * w for w in weights)),
            min(width, height) * 0.7 / max(weights),
        )
        # Pack inside the margin but size off the whole page, so only a set that
        # doesn't fit has to shrink.
        inset = round(min(width, height) * margin)
        box = (width - 2 * inset, height - 2 * inset)
        alphas = [img.getchannel("A") for img in arts]
        args = (names, alphas, order, weights, flips, base, *box)

        placed, used_px = _layout(*args, font_key, name_px, label_text, layout)
        if placed is None and font_key:  # birds beat blank paper
            log.warning("No layout fits %d species with names at %dx%d", len(names), *box)
            placed, used_px = _layout(*args, None, name_px, label_text, layout)

        result = (
            tuple(
                _Placed(
                    s.index,
                    s.dim,
                    (x + inset + s.art_at[0], y + inset + s.art_at[1]),
                    None
                    if s.label_at is None
                    else (x + inset + s.label_at[0], y + inset + s.label_at[1]),
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
    margin: float = DEFAULT_MARGIN,
    name_key: bool = False,
) -> Image.Image:
    """Composite the given (name, image) entries into a tightly packed collage.

    textured: paper grain for the web, flat paper for the panel, whose dither
    would otherwise turn the grain into noise. It also picks the label ink.
    label_text: scientific name -> what the label reads; str leaves it alone.
    perches: the active style's bare branches, for a page with no birds on it.
    layout: how the birds are packed (packing.LAYOUTS).
    margin: bare paper along the edge, as a fraction of the short side.
    name_key: with names on, number the birds and list the names in a key.
    """
    canvas = blank(resolution, textured)

    kept = [(name, path) for name, path in entries if path is not None]
    if not kept:
        draw_perch(canvas, perches, day_ordinal(), textured)
        return canvas
    if show_names and name_key:
        _draw_keyed(canvas, kept, textured, font_key, label_size, label_text, layout, margin)
        return canvas

    names = [name for name, _ in kept]
    placed, scale, used_px = _draw_birds(
        canvas,
        kept,
        (0, 0),
        resolution,
        textured,
        font_key if show_names else None,
        label_size,
        label_text,
        layout,
        margin,
    )
    # Names last: halos feather past the collision mask, so a name drawn inline
    # with the birds would be washed over by the next neighbour.
    if used_px:
        font = fonts.load(font_key, max(1, round(used_px * scale)))
        texts = {p.index: label_text(names[p.index]) for p in placed}
        _stamp_labels(canvas, placed, texts, font, scale, (0, 0), textured)
    return canvas


def _draw_birds(
    canvas: Image.Image,
    kept: list[tuple[str, Path]],
    origin: tuple[int, int],
    size: tuple[int, int],
    textured: bool,
    font_key: str | None,
    label_size: str,
    label_text: Callable[[str], str],
    layout: str,
    margin: float,
) -> tuple[tuple[_Placed, ...], float, int]:
    """Pack the birds into the `size` box at `origin` and draw them, labels
    reserved but not drawn. Returns the placements, their scale and label size."""
    arts = [trim(path) for _, path in kept]
    # Mass sizes the bird; this sizes the plate it is drawn on.
    ratios = [span_ratio(path, art.size) for (_, path), art in zip(kept, arts, strict=True)]

    # Pack pixels from here down; `scale` takes them to the output.
    scale = min(size) / _PACK_SHORT
    width, height = round(size[0] / scale), round(size[1] / scale)

    names = [name for name, _ in kept]
    flips = [_flip(name) for name in names]
    name_px = label_px(width, height, label_size)
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
    )

    for p in placed:
        art = _scaled(arts[p.index], max(1, round(p.dim * scale)), flips[p.index])
        at = _at(p.at, scale, origin)
        corner = (at[0] - PAD, at[1] - PAD)
        proc = process_sprite(art, corner, textured=textured)
        canvas.paste(proc, corner, proc)
    return placed, scale, used_px


def _stamp_labels(
    canvas: Image.Image,
    placed: Iterable[_Placed],
    texts: dict[int, str],
    font: ImageFont.FreeTypeFont,
    scale: float,
    origin: tuple[int, int],
    textured: bool,
) -> None:
    """Each text centred in the box its bird reserved for it."""
    for p in placed:
        if p.label_at is None:
            continue
        mask = text_mask(texts[p.index], font, not textured)
        at = _at(p.label_at, scale, origin)
        centred = at[0] + round((p.label_w * scale - mask.width) / 2)
        stamp(canvas, mask, (centred, at[1]), textured)


@dataclass(frozen=True)
class _Key:
    """The key's grid, in output pixels: numbers right-aligned in their own
    column, names after, filled down each column first."""

    px: int
    depth: int  # lines per name: a second language that cannot fit is dropped
    rows: int
    line: int
    entry: int  # one name's lines, and the space after it
    num_w: int
    space: int
    col_w: int  # one entry, gutter included
    size: tuple[int, int]
    at: tuple[int, int]


def _fit_key(
    texts: list[list[str]], font_key: str, px: int, box: tuple[int, int, int, int]
) -> tuple[_Key, tuple[int, int, int, int]]:
    """Lay the key out below a portrait page's birds or beside a landscape
    one's, shrinking its type until it takes no more than `_KEY_SHARE` of the
    page. A second language that does not fit even at the smallest size is left
    out of the key. Returns the key and the box left for the birds."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    below = bh > bw
    for depth in dict.fromkeys((max(len(t) for t in texts), 1)):
        size = px
        while True:
            font = fonts.load(font_key, size)
            line = round(size * _KEY_LEADING)
            # Air between two-line names, or one reads as its neighbour's.
            entry = depth * line + (round(line * 0.25) if depth > 1 else 0)
            num_w = math.ceil(font.getlength(f"{len(texts)}."))
            space = round(size * 0.4)
            gutter = round(size * 1.2)
            widest = max(font.getlength(part) for t in texts for part in t[:depth])
            col_w = num_w + space + math.ceil(widest) + gutter
            if below:
                cols = max(1, min(len(texts), (bw + gutter) // col_w))
            else:
                cols = math.ceil(len(texts) / max(1, bh // entry))
            rows = math.ceil(len(texts) / cols)
            kw, kh = cols * col_w - gutter, rows * entry
            taken, room = (kh, bh) if below else (kw, bw)
            fits = taken <= room * _KEY_SHARE
            if fits or size <= MIN_LABEL_PX:
                break
            size -= 1
        if fits:
            break
    if below:
        at, birds = (x0 + (bw - kw) // 2, y1 - kh), (x0, y0, x1, y1 - kh - gutter)
    else:
        at, birds = (x1 - kw, y0 + (bh - kh) // 2), (x0, y0, x1 - kw - gutter, y1)
    return _Key(size, depth, rows, line, entry, num_w, space, col_w, (kw, kh), at), birds


def _reading_order(placed: Sequence[_Placed], width: int, height: int) -> list[_Placed]:
    """Left to right in bands down the page, the way a plate's key is numbered."""
    rows = max(1, round(math.sqrt(len(placed) * height / width)))
    band = height / rows

    def spot(p: _Placed) -> tuple[int, float]:
        x, y = p.label_at or p.at
        return int(y // band), x + p.label_w / 2

    return sorted(placed, key=spot)


def _draw_keyed(
    canvas: Image.Image,
    kept: list[tuple[str, Path]],
    textured: bool,
    font_key: str,
    label_size: str,
    label_text: Callable[[str], str],
    layout: str,
    margin: float,
) -> None:
    """The birds with a number each, and their names in a key."""
    w, h = canvas.size
    inset = round(min(w, h) * margin)
    texts = [label_text(name).split("\n") for name, _ in kept]
    key, (bx0, by0, bx1, by1) = _fit_key(
        texts, font_key, label_px(w, h, label_size), (inset, inset, w - inset, h - inset)
    )

    # Numbering waits on the pack, so every bird reserves the widest number.
    widest = "8" * len(str(len(kept)))
    size = (bx1 - bx0, by1 - by0)
    placed, scale, used_px = _draw_birds(
        canvas,
        kept,
        (bx0, by0),
        size,
        textured,
        font_key,
        label_size,
        lambda _: widest,
        layout,
        0,
    )
    order = _reading_order(placed, round(size[0] / scale), round(size[1] / scale))
    if used_px:
        font = fonts.load(font_key, max(1, round(used_px * scale)))
        numbers = {p.index: str(n) for n, p in enumerate(order, 1)}
        _stamp_labels(canvas, order, numbers, font, scale, (bx0, by0), textured)

    font = fonts.load(font_key, key.px)
    ascent = font.getmetrics()[0]
    mask = Image.new("L", (key.size[0] + key.px, key.size[1] + key.px), 0)
    draw = ImageDraw.Draw(mask)
    for n, p in enumerate(order):
        col, row = divmod(n, key.rows)
        x, y = col * key.col_w + key.num_w, row * key.entry + ascent
        draw.text((x, y), f"{n + 1}.", font=font, fill=255, anchor="rs")
        for k, part in enumerate(texts[p.index][: key.depth]):
            draw.text((x + key.space, y + k * key.line), part, font=font, fill=255, anchor="ls")
    stamp(canvas, mask if textured else flatten(mask), key.at, textured)


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
) -> list[str]:
    """The species that make the page, in name order.

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
    return sorted(name for name, _n in sorted(counted, key=_rank(ranking))[:limit])


def gather_entries(
    source: Source,
    images_dir: Path,
    style: str,
    picks: Picks,
    hours: float = 24,
    limit: int = NO_LIMIT,
    ranking: str = DEFAULT_RANKING,
) -> list[tuple[str, Path | None]]:
    """The page's species paired with the artwork each is wearing. The None only
    stands for a file that vanished between `selected_species` and here."""
    return [
        (name, image_for(name, images_dir, style, picks))
        for name in selected_species(source, images_dir, style, hours, limit, ranking)
    ]
