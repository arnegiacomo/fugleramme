"""What the frame is showing.

A mode is one page in two halves: how it is drawn, and what it is a function of.
Both outputs go through the same pair, so the panel and the kiosk can never
disagree, and the render loop re-renders only when a mode's own key moves - the
species set for the collage, the species alone for the latest bird, the date for
the bird of the day. The key is what makes a slow e-ink page bearable: a busy
feeder must not spend the day refreshing.

Only the collage reads the lookback window; the rest look at the whole record,
which is why the admin greys the setting out for them.
"""

from __future__ import annotations

import hashlib
import io
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, time
from pathlib import Path
from typing import TYPE_CHECKING

from PIL import Image

from .collage import gather_entries, render_collage
from .db import Database, Species
from .featured import Featured
from .languages import Namer
from .names import drawable_keys, image_for, normalize, perches_for, resolve, variants_for
from .page import day_ordinal
from .picks import Picks
from .plate import render_plate

if TYPE_CHECKING:
    from .settings import Settings

# How far back to look for a detection we have artwork for. A species with no
# plate cannot hold the page, so the latest one that can does instead.
_RECENT_SCAN = 60


@dataclass(frozen=True)
class Context:
    """Everything a mode draws from, resolved from the settings by `context`."""

    mode: str
    db: Database
    images_dir: Path
    style: str
    picks: Picks
    featured: Featured
    namer: Namer
    resolution: tuple[int, int]
    show_names: bool
    lookback_hours: int
    font_key: str
    label_size: str
    textured: bool = True
    # Only the render loop may advance the bird of the day; everyone else peeks.
    commit: bool = False

    def perches(self):
        return perches_for(self.images_dir, self.style)

    def drawable(self):
        """Species keys this style can draw. One listing, not a glob per name:
        the plate modes ask it of the whole life list on every poll."""
        return drawable_keys(self.images_dir, self.style)


def context(
    db: Database,
    images_dir: Path,
    picks: Picks,
    featured: Featured,
    settings: Settings,
    namer: Namer,
    resolution: tuple[int, int],
    textured: bool = True,
    commit: bool = False,
) -> Context:
    return Context(
        mode=settings.mode,
        db=db,
        images_dir=images_dir,
        style=resolve(settings.style, images_dir),
        picks=picks,
        featured=featured,
        namer=namer,
        resolution=resolution,
        show_names=settings.show_names,
        lookback_hours=settings.lookback_hours,
        font_key=settings.label_font,
        label_size=settings.label_size,
        textured=textured,
        commit=commit,
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


def _plate(
    ctx: Context, name: str | None, note: str = "", art: Path | None = None
) -> Image.Image:
    if name and art is None:
        art = image_for(name, ctx.images_dir, ctx.style, ctx.picks)
    return render_plate(
        art, ctx.namer.label(name) if name else "", note, ctx.resolution,
        ctx.show_names, ctx.textured, ctx.font_key, ctx.label_size, ctx.perches(),
    )


def _date(moment: datetime) -> str:
    local = moment.astimezone()
    return f"{local.day} {local.strftime('%B')}"


def _midnight() -> int:
    return int(datetime.combine(date.today(), time.min).timestamp())


def _collage_key(ctx: Context) -> tuple:
    # Sorted to keep key constant for the same bird set (avoid re-renders on order change)
    species = tuple(sorted(name for name, _ in ctx.db.species_since(ctx.lookback_hours)))
    return (species, day_ordinal() if not species else None)


def _collage(ctx: Context) -> Image.Image:
    return render_collage(
        gather_entries(ctx.db, ctx.images_dir, ctx.style, ctx.picks, ctx.lookback_hours),
        ctx.resolution, ctx.show_names, ctx.textured, ctx.font_key, ctx.label_size,
        ctx.namer.label, ctx.perches(),
    )


def _latest(ctx: Context):
    keys = ctx.drawable()
    return next(
        (d for d in ctx.db.recent(_RECENT_SCAN) if normalize(d.scientific_name) in keys), None
    )


def _latest_key(ctx: Context) -> tuple:
    latest = _latest(ctx)
    if latest is None:
        return (None, day_ordinal())
    # The species, not the detection: the same bird calling again holds the page.
    return (latest.scientific_name, latest.detected_at.astimezone().date())


def _latest_page(ctx: Context) -> Image.Image:
    latest = _latest(ctx)
    if latest is None:
        return _plate(ctx, None)
    return _plate(ctx, latest.scientific_name, _date(latest.detected_at))


def _of_the_day(ctx: Context) -> tuple[Species, int] | None:
    """Today's bird and its lap of the walk, drawn from the record as it stood at
    midnight so its tally is fixed for the day."""
    keys = ctx.drawable()
    entries = [s for s in ctx.db.life_list(until=_midnight()) if normalize(s.scientific_name) in keys]
    chosen = ctx.featured.choose(
        day_ordinal(), [s.scientific_name for s in entries], commit=ctx.commit
    )
    if chosen is None:
        return None
    name, lap = chosen
    species = next((s for s in entries if s.scientific_name == name), None)
    return (species, lap) if species else None


def _daily_key(ctx: Context) -> tuple:
    today = _of_the_day(ctx)
    return (day_ordinal(), today[0].scientific_name if today else None)


def _daily_page(ctx: Context) -> Image.Image:
    today = _of_the_day(ctx)
    if today is None:
        return _plate(ctx, None)
    species, lap = today
    # By lap, not picks.choose: a bird the walk never forgets would otherwise
    # wear the plate it first rolled every time round.
    variants = variants_for(species.scientific_name, ctx.images_dir, ctx.style)
    heard = "Heard once" if species.count == 1 else f"Heard {species.count} times"
    return _plate(
        ctx, species.scientific_name, f"{heard} · first {_date(species.first_seen)}",
        art=variants[lap % len(variants)],
    )


def _arrival(ctx: Context) -> Species | None:
    """The most recent first-ever species, which may be weeks old - that it has
    been a while is itself worth reading."""
    keys = ctx.drawable()
    return next(
        (s for s in reversed(ctx.db.life_list()) if normalize(s.scientific_name) in keys), None
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
    return _plate(ctx, species.scientific_name, f"First heard {_date(species.first_seen)}")


def _one(species) -> list[str]:
    return [species.scientific_name] if species else []


def _collage_subjects(ctx: Context) -> list[str]:
    # The whole window, art-less species included: the admin marks those as
    # counted but not drawn.
    return [name for name, _ in ctx.db.species_since(ctx.lookback_hours)]


# Insertion order is the order button A walks.
MODES: dict[str, Mode] = {
    "collage": Mode("Collage (default)", _collage, _collage_key, _collage_subjects, windowed=True),
    "latest": Mode(
        "Latest bird", _latest_page, _latest_key,
        lambda ctx: [d.scientific_name] if (d := _latest(ctx)) else [],
    ),
    "daily": Mode(
        "Bird of the day", _daily_page, _daily_key,
        lambda ctx: _one(today[0] if (today := _of_the_day(ctx)) else None),
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
        ctx.mode, ctx.style, ctx.resolution, ctx.show_names, ctx.font_key,
        ctx.label_size, ctx.namer.key, mode.key(ctx),
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
