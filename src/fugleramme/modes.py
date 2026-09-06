"""What the frame is showing.

A mode is one page in two halves: how it is drawn, and what it is a function of.
Both outputs go through the same pair, so the panel and the kiosk can never
disagree, and the render loop re-renders only when a mode's own key moves - the
species set for the collage, the run the latest bird is on rather than its last
call. The key is what makes a slow e-ink page bearable: a busy feeder must not
spend the day refreshing.

Only the collage reads the lookback window; the rest look at the whole record,
which is why the admin greys the setting out for them.
"""

from __future__ import annotations

import hashlib
import io
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from .languages import Namer
from .names import drawable_keys, image_for, normalize, perches_for, resolve
from .picks import Picks
from .render.collage import gather_entries, render_collage
from .render.packing import DEFAULT_LAYOUT
from .render.page import day_ordinal
from .render.plate import render_plate
from .source import Source, Species

if TYPE_CHECKING:
    from .settings import Settings

# How far back to look for a detection we have artwork for, and for the start of
# the run the holder is on. A species with no plate cannot hold the page, so the
# latest one that can does instead.
_RECENT_SCAN = 500


@dataclass(frozen=True)
class Context:
    """Everything a mode draws from, resolved from the settings by `context`."""

    mode: str
    source: Source
    images_dir: Path
    style: str
    picks: Picks
    namer: Namer
    resolution: tuple[int, int]
    show_names: bool
    lookback_hours: int
    font_key: str
    label_size: str
    layout: str = DEFAULT_LAYOUT
    textured: bool = True

    def perches(self):
        return perches_for(self.images_dir, self.style)

    def drawable(self):
        """Species keys this style can draw. One listing, not a glob per name:
        the plate modes ask it of the whole life list on every poll."""
        return drawable_keys(self.images_dir, self.style)


def context(
    source: Source,
    images_dir: Path,
    picks: Picks,
    settings: Settings,
    namer: Namer,
    resolution: tuple[int, int],
    textured: bool = True,
) -> Context:
    return Context(
        mode=settings.mode,
        source=source,
        images_dir=images_dir,
        style=resolve(settings.style, images_dir),
        picks=picks,
        namer=namer,
        resolution=resolution,
        show_names=settings.show_names,
        lookback_hours=settings.lookback_hours,
        font_key=settings.label_font,
        label_size=settings.label_size,
        layout=settings.layout,
        textured=textured,
    )


@dataclass(frozen=True)
class Mode:
    label: str
    render: Callable[[Context], Image.Image]
    key: Callable[[Context], tuple]
    # The species this page is about, for the admin listing.
    subjects: Callable[[Context], list[str]]
    # Driven by the lookback window: the admin offers the setting, and the loop
    # prunes artwork picks to it.
    windowed: bool = False


def _plate(ctx: Context, name: str | None, note: str = "", art: Path | None = None) -> Image.Image:
    if name and art is None:
        art = image_for(name, ctx.images_dir, ctx.style, ctx.picks)
    return render_plate(
        art,
        ctx.namer.label(name) if name else "",
        note,
        ctx.resolution,
        ctx.show_names,
        ctx.textured,
        ctx.font_key,
        ctx.label_size,
        ctx.perches(),
    )


def _collage_key(ctx: Context) -> tuple:
    # Sorted to keep key constant for the same bird set (avoid re-renders on order change)
    species = tuple(sorted(name for name, _ in ctx.source.species_since(ctx.lookback_hours)))
    return (species, day_ordinal() if not species else None)


def _collage(ctx: Context) -> Image.Image:
    return render_collage(
        gather_entries(ctx.source, ctx.images_dir, ctx.style, ctx.picks, ctx.lookback_hours),
        ctx.resolution,
        ctx.show_names,
        ctx.textured,
        ctx.font_key,
        ctx.label_size,
        ctx.namer.label,
        ctx.perches(),
        ctx.layout,
    )


def _holder(ctx: Context) -> tuple[str, datetime] | None:
    """The species holding the page, and when it took it - the oldest detection
    of its unbroken run. A species with no artwork cannot hold the page, so it
    does not break someone else's run either."""
    keys = ctx.drawable()
    name: str | None = None
    since: datetime | None = None
    for detection in ctx.source.recent(_RECENT_SCAN):  # newest first
        if normalize(detection.scientific_name) not in keys:
            continue
        if name is None:
            name = detection.scientific_name
        elif detection.scientific_name != name:
            break
        since = detection.detected_at
    return (name, since) if name and since else None


def _latest_key(ctx: Context) -> tuple:
    # When the run began, not when the bird last called: the caption shows a
    # clock time, so a key that moved on every call would re-push the panel all
    # day, and one that ignored the time would let the two outputs disagree.
    return _holder(ctx) or (None, day_ordinal())


def _latest_page(ctx: Context) -> Image.Image:
    holder = _holder(ctx)
    if holder is None:
        return _plate(ctx, None)
    name, since = holder
    return _plate(ctx, name, ctx.namer.moment(since))


def _arrival(ctx: Context) -> Species | None:
    """The most recent first-ever species, which may be weeks old - that it has
    been a while is itself worth reading."""
    keys = ctx.drawable()
    return next(
        (s for s in reversed(ctx.source.life_list()) if normalize(s.scientific_name) in keys), None
    )


def _arrival_key(ctx: Context) -> tuple:
    species = _arrival(ctx)
    if species is None:
        return (None, day_ordinal())
    return (species.scientific_name, species.first_seen.astimezone().date())


def _arrival_page(ctx: Context) -> Image.Image:
    species = _arrival(ctx)
    if species is None:
        return _plate(ctx, None)
    # The year stands in for "first heard": only names get translated, and this
    # one can be months old.
    return _plate(ctx, species.scientific_name, ctx.namer.date(species.first_seen))


def _one(species) -> list[str]:
    return [species.scientific_name] if species else []


def _collage_subjects(ctx: Context) -> list[str]:
    # The whole window, art-less species included: the admin marks those as
    # counted but not drawn.
    return [name for name, _ in ctx.source.species_since(ctx.lookback_hours)]


# Insertion order is the order button A walks.
MODES: dict[str, Mode] = {
    "collage": Mode("Collage (default)", _collage, _collage_key, _collage_subjects, windowed=True),
    "latest": Mode(
        "Latest bird",
        _latest_page,
        _latest_key,
        lambda ctx: [h[0]] if (h := _holder(ctx)) else [],
    ),
    "arrival": Mode("Newest arrival", _arrival_page, _arrival_key, lambda ctx: _one(_arrival(ctx))),
}

DEFAULT_MODE = "collage"


def mode_of(key: str) -> Mode:
    return MODES.get(key, MODES[DEFAULT_MODE])


def state_key(ctx: Context) -> tuple:
    """Everything the page is a function of: the render cache key, and what the
    kiosk polls to know the picture changed."""
    mode = mode_of(ctx.mode)
    return (
        ctx.mode,
        ctx.style,
        ctx.resolution,
        ctx.show_names,
        ctx.font_key,
        ctx.label_size,
        ctx.layout if mode.windowed else None,
        ctx.namer.key,
        mode.key(ctx),
    )


def token(key: tuple) -> str:
    """Short digest of a state key. blake2b, not hash(): hash() is salted per
    process and would fire a spurious swap on every restart."""
    return hashlib.blake2b(repr(key).encode(), digest_size=8).hexdigest()


def render(ctx: Context) -> Image.Image:
    return mode_of(ctx.mode).render(ctx)


def subjects(ctx: Context) -> list[str]:
    """The species the current page is about."""
    return mode_of(ctx.mode).subjects(ctx)


_cache: tuple[tuple, bytes] | None = None
_cache_lock = threading.Lock()


def png_bytes(ctx: Context) -> bytes:
    """The current page as PNG, for the HTTP endpoints. The lock is held across
    the render so concurrent kiosk requests wait for one render instead of each
    doing their own."""
    global _cache
    with _cache_lock:
        key = state_key(ctx)
        if _cache is not None and _cache[0] == key:
            return _cache[1]
        buffer = io.BytesIO()
        render(ctx).save(buffer, format="PNG")
        _cache = (key, buffer.getvalue())
        return _cache[1]
