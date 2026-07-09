"""Kiosk collage: full-color composite of the species seen in the last 24h.

This is the web/kiosk view, deliberately different from the Inky panel. It uses
the source PNGs at full color (no 6-color dither, so no grain) and leans on
their transparency to overlap birds into a collage. Names are drawn by default;
that will become an admin toggle (see the admin-interface issue).

Layout is a jittered grid with slight rotation and random layering, seeded from
the species set so it stays put between refreshes and only reshuffles when the
set of birds changes.
"""

from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .db import Database
from .names import image_for

DEFAULT_RESOLUTION = (1280, 800)
_BG = (250, 249, 246)  # warm off-white
_INK = (30, 30, 30)
_MAX_BIRDS = 40  # cap clutter on busy days


def _layout(count: int, width: int, height: int) -> tuple[int, int, float, float]:
    """Grid geometry: (cols, rows, cell_w, cell_h)."""
    cols = max(1, round(math.sqrt(count * width / height)))
    rows = math.ceil(count / cols)
    return cols, rows, width / cols, height / rows


def _draw_label(
    draw: ImageDraw.ImageDraw,
    name: str,
    cx: float,
    top_y: int,
    font: ImageFont.FreeTypeFont,
) -> None:
    left, top, right, bottom = draw.textbbox((0, 0), name, font=font)
    w, h = right - left, bottom - top
    tx = int(cx - w / 2)
    draw.rounded_rectangle(
        (tx - 6, top_y - 3, tx + w + 6, top_y + h + 5), radius=6, fill=(255, 255, 255, 220)
    )
    draw.text((tx, top_y), name, font=font, fill=_INK)


def render_collage(
    entries: list[tuple[str, Path | None]],
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    show_names: bool = True,
    rng: random.Random | None = None,
) -> Image.Image:
    """Composite the given (name, image) entries into a collage."""
    width, height = resolution
    canvas = Image.new("RGBA", (width, height), (*_BG, 255))
    draw = ImageDraw.Draw(canvas)

    if not entries:
        font = ImageFont.load_default(size=max(20, height // 20))
        msg = "Ingen fugler siste 24 timer"
        left, top, right, bottom = draw.textbbox((0, 0), msg, font=font)
        draw.text(
            ((width - (right - left)) / 2, (height - (bottom - top)) / 2),
            msg, font=font, fill=_INK,
        )
        return canvas.convert("RGB")

    rng = rng or random.Random()
    entries = entries[:_MAX_BIRDS]
    cols, rows, cell_w, cell_h = _layout(len(entries), width, height)
    box = min(cell_w, cell_h) * 1.5  # >1 cell so neighbours overlap
    name_font = ImageFont.load_default(size=max(13, int(min(cell_w, cell_h) / 9)))
    # inset the grid so edge birds overhang into a margin instead of clipping
    margin = min(width, height) * 0.07

    order = list(range(len(entries)))
    rng.shuffle(order)  # random layering of overlaps
    labels: list[tuple[str, float, int]] = []  # (name, cx, top_y), drawn last
    for idx in order:
        col, row = idx % cols, idx // cols
        cx = margin + (col + 0.5) / cols * (width - 2 * margin) + rng.uniform(-cell_w, cell_w) * 0.1
        cy = margin + (row + 0.5) / rows * (height - 2 * margin) + rng.uniform(-cell_h, cell_h) * 0.1
        name, art = entries[idx]
        caption_y = int(cy)
        if art is not None:
            bird = Image.open(art).convert("RGBA")
            bird.thumbnail((box, box), Image.LANCZOS)
            bird = bird.rotate(rng.uniform(-7, 7), expand=True, resample=Image.BICUBIC)
            canvas.alpha_composite(
                bird, (int(cx - bird.width / 2), int(cy - bird.height / 2))
            )
            caption_y = int(cy + bird.height / 2) - 4
        labels.append((name, cx, caption_y))

    if show_names:
        for name, cx, top_y in labels:
            _draw_label(draw, name, cx, top_y, name_font)

    return canvas.convert("RGB")


def gather_entries(db: Database, images_dir: Path, rng: random.Random) -> list[tuple[str, Path | None]]:
    """Last-24h species paired with a (random) artwork path, or None if absent."""
    return [
        (name, image_for(name, images_dir, rng))
        for name, _count in db.species_last_24h()
    ]


def collage_png_bytes(
    db: Database,
    images_dir: Path,
    resolution: tuple[int, int] = DEFAULT_RESOLUTION,
    show_names: bool = True,
) -> bytes:
    """Render the current collage to PNG bytes for the HTTP endpoint.

    Seeded from the species set so the layout is stable across refreshes and
    only changes when the set of birds does.
    """
    import io

    species = [name for name, _ in db.species_last_24h()]
    rng = random.Random(hash(tuple(species)))
    entries = gather_entries(db, images_dir, rng)
    image = render_collage(entries, resolution, show_names, rng)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
