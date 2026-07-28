"""Kiosk collage: full-color composite of the species seen in the last 24h.

This is the web/kiosk view (also dithered onto the panel). It uses the source
PNGs at full color and packs them by their silhouettes: opaque pixels never
overlap and nothing clips off screen, but the transparent margins are free to
overlap so birds nestle closely. Birds are sized by their real body mass
(compressed, see sizes.py) and placed largest-first on an outward spiral from
the centre, so big birds land in the middle; the whole set is then scaled to
fill the canvas.

Species with no artwork are omitted (there is nothing to draw for them once
names are off). Names are off by default; they will become an admin toggle.
"""

from __future__ import annotations

import io
import math
import random
import threading
from collections.abc import Sequence
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .config import REPO_ROOT
from .db import Database
from .names import image_for
from .paper import PAD, TARGET_PAPER, paper_texture, process_sprite
from .sizes import SIZE_EXPONENT, mass_of

DEFAULT_RESOLUTION = (1280, 800)
PERCHES_DIR = REPO_ROOT / "assets" / "perches"
_INK = (30, 30, 30)
_MAX_BIRDS = 40
_ALPHA_CUTOFF = 24
_OVERLAP_PX = 2        # erode the collision mask slightly so birds nestle into
                       # each other's (invisible on paper) halos. No rotation:
                       # it tilts the ground/water on birds drawn with terrain.
_STEP = 6


def _trim(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    bbox = img.getchannel("A").getbbox()  # trim by alpha, not by RGB
    return img.crop(bbox) if bbox else img


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
            Image.LANCZOS,
        )
    if flip:
        img = img.transpose(Image.FLIP_LEFT_RIGHT)
    mask = img.getchannel("A").point(lambda a: 255 if a > _ALPHA_CUTOFF else 0)
    if _OVERLAP_PX:
        mask = mask.filter(ImageFilter.MinFilter(_OVERLAP_PX * 2 + 1))
    return img, np.asarray(mask, dtype=bool)


def _spiral(cx: float, cy: float, max_r: float):
    yield cx, cy
    r = _STEP
    while r <= max_r:
        count = max(8, int(2 * math.pi * r / _STEP))
        for i in range(count):
            a = 2 * math.pi * i / count
            yield cx + r * math.cos(a), cy + r * math.sin(a)
        r += _STEP


def _pack(sprites: list[tuple[Image.Image, np.ndarray]], width: int, height: int):
    """Place every sprite with no opaque overlap and fully on-screen, or return
    None if one does not fit. Sprites should be pre-sorted largest-first."""
    occ = np.zeros((height, width), dtype=bool)
    placed = []
    max_r = math.hypot(width, height)
    for img, mask in sprites:
        h, w = mask.shape
        spot = None
        for px, py in _spiral(width / 2, height / 2, max_r):
            x, y = int(px - w / 2), int(py - h / 2)
            if x < 0 or y < 0 or x + w > width or y + h > height:
                continue
            if not (occ[y:y + h, x:x + w] & mask).any():
                spot = (x, y)
                break
        if spot is None:
            return None
        x, y = spot
        occ[y:y + h, x:x + w] |= mask
        placed.append((img, x, y))
    return placed


def _center(placed, width: int, height: int):
    """Shift the packed cluster so its bounding box is centred on the canvas."""
    xs0 = min(x for _, x, _ in placed)
    ys0 = min(y for _, _, y in placed)
    xs1 = max(x + img.width for img, x, _ in placed)
    ys1 = max(y + img.height for img, _, y in placed)
    dx = (width - (xs1 - xs0)) // 2 - xs0
    dy = (height - (ys1 - ys0)) // 2 - ys0
    return [(img, x + dx, y + dy) for img, x, y in placed]


def _size_weights(names: list[str]) -> list[float]:
    """Per-bird display weight from real mass, centered on the present set's
    geometric mean and compressed by SIZE_EXPONENT."""
    masses = [mass_of(n) for n in names]
    geo = math.exp(sum(math.log(m) for m in masses) / len(masses))
    return [(m / geo) ** SIZE_EXPONENT for m in masses]


def render_collage(
    entries: list[tuple[str, Path | None]],
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    show_names: bool = False,
    rng: random.Random | None = None,
    textured: bool = True,
) -> Image.Image:
    """Composite the given (name, image) entries into a tightly packed collage.

    textured: paper grain for the web; flat paper for the panel, whose dither
    would otherwise turn the grain into noise.
    """
    width, height = resolution
    canvas = paper_texture(width, height) if textured else Image.new("RGB", (width, height), TARGET_PAPER)
    rng = rng or random.Random()

    arts = [(name, _trim(path)) for name, path in entries if path is not None][:_MAX_BIRDS]
    if not arts:
        _draw_empty(canvas, width, height, rng, textured)
        return canvas

    # Each bird's target size scales with its real mass (compressed); the whole
    # set then overshoots and shrinks to the first fit that fills the canvas.
    # Placing biggest-first on the center-out spiral keeps large birds central.
    weights = _size_weights([name for name, _ in arts])
    order = sorted(range(len(arts)), key=lambda i: -weights[i])
    flips = [rng.random() < 0.5 for _ in arts]
    base = min(
        math.sqrt(width * height * 1.5 / sum(w * w for w in weights)),
        min(width, height) * 0.7 / max(weights),
    )
    placed = None
    for _ in range(20):
        sprites = [_scaled_sprite(arts[i][1], max(24, int(base * weights[i])), flips[i]) for i in order]
        placed = _pack(sprites, width, height)
        if placed is not None:
            break
        base *= 0.9

    if placed:
        centered = _center(placed, width, height)
        for img, x, y in centered:
            proc = process_sprite(img, textured=textured)
            canvas.paste(proc, (x - PAD, y - PAD), proc)
        if show_names:
            _draw_names(canvas, [arts[i][0] for i in order], centered)

    return canvas


def _draw_empty(canvas, width: int, height: int, rng: random.Random, textured: bool = True) -> None:
    """No detections: a single empty perch, centered on the paper page."""
    perches = sorted(PERCHES_DIR.glob("*.png"))
    if not perches:
        return
    perch = _trim(rng.choice(perches))
    if rng.random() < 0.5:
        perch = perch.transpose(Image.FLIP_LEFT_RIGHT)
    target = int(min(width, height) * 0.7)
    scale = target / max(perch.width, perch.height)
    perch = perch.resize(
        (max(1, round(perch.width * scale)), max(1, round(perch.height * scale))),
        Image.LANCZOS,
    )
    proc = process_sprite(perch, textured=textured)
    canvas.paste(proc, ((width - proc.width) // 2, (height - proc.height) // 2), proc)


def _draw_names(canvas, names, placed):
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=16)
    for name, (img, x, y) in zip(names, placed):
        draw.text((x, y + img.height - 4), name, font=font, fill=_INK)


def gather_entries(
    db: Database,
    images_dir: Path,
    sources: Sequence[str],
    rng: random.Random,
    hours: int = 24,
) -> list[tuple[str, Path | None]]:
    """Recent-window species paired with a (random) artwork path, or None if absent."""
    return [
        (name, image_for(name, images_dir, sources, rng))
        for name, _count in db.species_since(hours)
    ]


_cache: tuple[tuple, bytes] | None = None
_cache_lock = threading.Lock()
_EMPTY = None  # cache-key marker for the no-species perch


def collage_png_bytes(
    db: Database,
    images_dir: Path,
    sources: Sequence[str],
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    show_names: bool = False,
    lookback_hours: int = 24,
) -> bytes:
    """Render the current collage to PNG bytes for the HTTP endpoint.

    Both states share the single _cache slot, keyed by the species set. Birds:
    the layout is a pure function of the set, re-packed only when it changes.
    Empty: the perch is held for the whole empty period and re-rolled only when
    a new one begins (the cache still holds a bird key), so refreshes don't
    restlessly swap it.

    The lock is held across the render so concurrent kiosk requests wait for one
    render instead of each doing their own.
    """
    global _cache
    with _cache_lock:
        species = tuple(name for name, _ in db.species_since(lookback_hours))
        key = (species or _EMPTY, tuple(sources), resolution, show_names)
        if _cache is not None and _cache[0] == key:
            return _cache[1]

        if not species:
            image = render_collage([], resolution, show_names, random.Random())
        else:
            rng = random.Random(hash(species))
            image = render_collage(
                gather_entries(db, images_dir, sources, rng, lookback_hours),
                resolution, show_names, rng,
            )

        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        _cache = (key, buffer.getvalue())
        return _cache[1]
