"""Map a detector's scientific name to a bird artwork file.

The detector emits modern eBird names, capitalized and space-separated
("Turdus merula"); artwork files are lowercase and hyphenated
("turdus-merula.png"). Since the files are named with modern taxonomy, the
lookup is just format normalization plus an exact filename match - no alias
table. Names with no artwork resolve to None and the collage omits them.

Artwork is grouped by *style* into subfolders of `images_dir` ("classic", a
user's "custom", ...), one active at a time: `available_styles` lists what is
present and `resolve` turns a saved selection into the folder to actually draw
from. A style is curated by hand (`scripts/curate.py`) and may keep more than
one image for a bird, numbered "<key>-2.png", "<key>-3.png"; which of them a
species is currently wearing is picks.py's business, not this module's.

Each style folder carries its own ATTRIBUTION.md naming the works it draws on,
and a manifest.json giving each single file the work it was cut from
(`source_of`) and a link to the plate itself (`origin_of`). A style filled by
hand has no manifest and simply has no provenance to show.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .picks import Picks

BIRDS = "birds"
PERCHES = "perches"
MANIFEST = "manifest.json"  # a style's record: "<file>.png" -> {"source", "url"}


def normalize(scientific_name: str) -> str:
    """ "Turdus merula" -> "turdus-merula" (the file-key shape)."""
    return scientific_name.strip().lower().replace(" ", "-")


def available_styles(images_dir: Path) -> list[str]:
    """Style folders under `images_dir` that actually hold artwork, sorted.

    A folder with no birds in it is not a style you can pick: an empty `custom/`
    waiting to be filled would otherwise sit in the admin radio and blank the
    frame when selected. Perches alone do not count - there would be no birds.
    """
    try:
        return sorted(
            d.name for d in images_dir.iterdir() if d.is_dir() and any((d / BIRDS).glob("*.png"))
        )
    except OSError:
        return []


def resolve(requested: str, images_dir: Path) -> str:
    """The style folder to draw from: the requested one if it still exists, else
    the first available (a mis-click or a renamed folder must never blank the
    frame), or "" when there is no artwork at all."""
    available = available_styles(images_dir)
    if requested in available:
        return requested
    return available[0] if available else ""


def variants_for(scientific_name: str, images_dir: Path, style: str) -> list[Path]:
    """Every image the style keeps for a name: "<key>.png" plus its "<key>-N.png".

    Numbered-only matching keeps a species key (e.g. tetrao-urogallus) from
    picking up a hybrid file (tetrao-urogallus-x-lagopus-lagopus.png).
    """
    if not style:
        return []
    key = normalize(scientific_name)
    folder = images_dir / style / BIRDS
    numbered = re.compile(rf"{re.escape(key)}-(\d+)")
    base = [folder / f"{key}.png"] if (folder / f"{key}.png").exists() else []
    rest = [(m, p) for p in folder.glob(f"{key}-*.png") if (m := numbered.fullmatch(p.stem))]
    # By number, not lexically: "-2" sorts before the bare key on a plain sort.
    return base + [p for _m, p in sorted(rest, key=lambda mp: int(mp[0].group(1)))]


_NUMBERED = re.compile(r"-\d+$")


def drawable_keys(images_dir: Path, style: str) -> set[str]:
    """Every species key the style can draw, from one directory listing.

    The plate modes ask this of the whole life list on every poll, and
    variants_for costs a glob per species - a hundred of them several times a
    minute is real work on an SD card.
    """
    if not style:
        return set()
    return {_NUMBERED.sub("", path.stem) for path in (images_dir / style / BIRDS).glob("*.png")}


def image_for(scientific_name: str, images_dir: Path, style: str, picks: Picks) -> Path | None:
    """The artwork this species is currently wearing, or None if it has none."""
    return picks.choose(scientific_name, variants_for(scientific_name, images_dir, style))


def perches_for(images_dir: Path, style: str) -> list[Path]:
    """The style's bare branches, drawn when nothing has been heard. Style-scoped
    like the birds: a perch is drawn in the same hand as the birds it stands in
    for, so a style without any draws none rather than borrowing another's."""
    return sorted((images_dir / style / PERCHES).glob("*.png")) if style else []


_manifests: dict[Path, tuple[float, dict[str, dict[str, str]]]] = {}


def manifest(folder: Path) -> dict[str, dict[str, str]]:
    """A style folder's provenance record, or {} if it keeps none.

    Cached on the file's mtime: the admin page asks for one line of it per
    subject, and re-reading the whole record that often is pointless work.
    """
    path = folder / MANIFEST
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return {}
    cached = _manifests.get(path)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        loaded = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    record = {
        str(key): {str(field): str(text) for field, text in value.items()}
        for key, value in loaded.items()
        if isinstance(value, dict)
    }
    _manifests[path] = (mtime, record)
    return record


def record_of(path: Path) -> dict[str, str]:
    """An image's manifest entry, from the nearest record at or above it.

    A style keeps one manifest, so a file in a subfolder - a perch - is keyed by
    its path relative to the folder the manifest sits in ("perches/oak.png").
    """
    for folder in (path.parent, path.parent.parent):
        listed = manifest(folder)
        if listed:
            return listed.get(path.relative_to(folder).as_posix(), {})
    return {}


def source_of(path: Path) -> str:
    """The work an image was cut from ("gould"), or "" if it is unlisted. This is
    the key ATTRIBUTION.md maps to terms, so it is what the admin page shows."""
    return record_of(path).get("source", "")


def origin_of(path: Path) -> str:
    """Where the plate an image was cut from can be seen - a citation URL, or ""
    when the manifest has none. Not every plate has one: a scan with no page to
    point at, or a file added by hand, keeps its work without a link."""
    return record_of(path).get("url", "")
