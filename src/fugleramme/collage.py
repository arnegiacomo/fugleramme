"""Kiosk collage: full-color composite of the species seen in the last 24h.

This is the web/kiosk view (also dithered onto the panel). It uses the source
PNGs at full color and packs them tightly by their silhouettes: opaque pixels
never overlap and nothing clips off screen, but the transparent margins are
free to overlap so birds nestle closely. Placement is largest-first on an
outward spiral from the centre, maximising bird size so gaps stay small.

Species with no artwork are omitted (there is nothing to draw for them once
names are off). Names are off by default; they will become an admin toggle.
"""

from __future__ import annotations

import io
import math
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .db import Database
from .names import image_for

DEFAULT_RESOLUTION = (1280, 800)
_BG = (250, 249, 246)  # warm off-white
_INK = (30, 30, 30)
_MAX_BIRDS = 40
_ALPHA_CUTOFF = 24     # pixels above this alpha count as opaque
_GAP_PX = 3            # min gap enforced between opaque regions (mask dilation)
_STEP = 8             # spiral search step in px


def _trim(path: Path) -> Image.Image:
    img = Image.open(path).convert("RGBA")
    bbox = img.getchannel("A").getbbox()  # trim by alpha, not by RGB
    return img.crop(bbox) if bbox else img


def _scaled_sprite(img: Image.Image, max_dim: int) -> tuple[Image.Image, np.ndarray]:
    """Scale a trimmed sprite to max_dim on its longest side and return it with
    its dilated opaque mask (bool array, True = keep-clear)."""
    scale = max_dim / max(img.width, img.height)
    if scale != 1.0:
        img = img.resize(
            (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
            Image.LANCZOS,
        )
    mask = img.getchannel("A").point(lambda a: 255 if a > _ALPHA_CUTOFF else 0)
    mask = mask.filter(ImageFilter.MaxFilter(_GAP_PX * 2 + 1))  # dilate for a gap
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


def render_collage(
    entries: list[tuple[str, Path | None]],
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    show_names: bool = False,
    rng: random.Random | None = None,
) -> Image.Image:
    """Composite the given (name, image) entries into a tightly packed collage."""
    width, height = resolution
    canvas = Image.new("RGBA", (width, height), (*_BG, 255))
    rng = rng or random.Random()

    arts = [(name, _trim(path)) for name, path in entries if path is not None][:_MAX_BIRDS]
    if not arts:
        draw = ImageDraw.Draw(canvas)
        font = ImageFont.load_default(size=max(20, height // 20))
        msg = "Ingen fugler siste 24 timer"
        left, top, right, bottom = draw.textbbox((0, 0), msg, font=font)
        draw.text(
            ((width - (right - left)) / 2, (height - (bottom - top)) / 2),
            msg, font=font, fill=_INK,
        )
        return canvas.convert("RGB")

    # Largest bird size that still packs: overshoot, then shrink to the first
    # fit so the cluster fills the canvas and gaps stay small.
    max_dim = min(int(math.sqrt(width * height * 1.4 / len(arts))), int(min(width, height) * 0.7))
    placed = None
    for _ in range(20):
        sprites = [_scaled_sprite(img, max_dim) for _, img in arts]
        sprites.sort(key=lambda s: -int(s[1].sum()))  # largest silhouette first
        placed = _pack(sprites, width, height)
        if placed is not None:
            break
        max_dim = int(max_dim * 0.9)

    if placed:
        for img, x, y in _center(placed, width, height):
            canvas.alpha_composite(img, (x, y))

    if show_names:
        _draw_names(canvas, [(name, img) for name, img in arts], placed)

    return canvas.convert("RGB")


def _draw_names(canvas, arts, placed):
    if not placed:
        return
    draw = ImageDraw.Draw(canvas)
    font = ImageFont.load_default(size=16)
    for (name, _), (img, x, y) in zip(arts, placed):
        draw.text((x, y + img.height - 4), name, font=font, fill=_INK)


def gather_entries(db: Database, images_dir: Path, rng: random.Random) -> list[tuple[str, Path | None]]:
    """Last-24h species paired with a (random) artwork path, or None if absent."""
    return [(name, image_for(name, images_dir, rng)) for name, _count in db.species_last_24h()]


_cache: tuple[tuple, bytes] | None = None


def collage_png_bytes(
    db: Database,
    images_dir: Path,
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    show_names: bool = False,
) -> bytes:
    """Render the current collage to PNG bytes for the HTTP endpoint.

    The output is a pure function of the species set (the layout is seeded from
    it), so it is cached and only re-packed when the set of birds changes -
    packing is a couple of seconds and the kiosk refreshes every 60s.
    """
    global _cache
    species = tuple(name for name, _ in db.species_last_24h())
    key = (species, resolution, show_names)
    if _cache is not None and _cache[0] == key:
        return _cache[1]

    rng = random.Random(hash(species))
    entries = gather_entries(db, images_dir, rng)
    image = render_collage(entries, resolution, show_names, rng)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    _cache = (key, buffer.getvalue())
    return _cache[1]
