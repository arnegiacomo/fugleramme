"""Map a detector's scientific name to a bird artwork file.

The detector emits scientific names capitalized and space-separated
("Turdus merula"); artwork files are lowercase and hyphenated
("turdus-merula.webp"). BirdNET's label taxonomy is frozen at the model's
training set while BirdNET-Go reports the current name, so one bird reaches the
frame as "Corvus monedula" and as "Coloeus monedula" both. `normalize` folds
the pair to the current name through the vendored OpenFauna alias map, and
shipped artwork is filed under that one spelling - the same key the label
table, the body masses and the picks all use. Names with no artwork resolve to
None and the collage omits them.

The shipped styles are WebP. It stores alpha losslessly, so a cut-out survives
exactly, and the tree is a sixth of what the same plates cost as PNG. PNG is
read too, and on purpose: a `custom/` folder should draw whatever you drop in
it, and PNG is what an editor exports by default. Ship WebP, read either.

Artwork is grouped by *style* into subfolders of `images_dir` ("classic", a
user's "custom", ...), one active at a time: `available_styles` lists what is
present and `resolve` turns a saved selection into the folder to actually draw
from. A style is curated by hand (`scripts/curate.py`) and may keep more than
one image for a bird, numbered "<key>-2.webp", "<key>-3.webp"; which of them a
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

from .config import REPO_ROOT
from .picks import Picks

BIRDS = "birds"
PERCHES = "perches"
MANIFEST = "manifest.json"  # a style's record: "<file>.webp" -> {"source", "url"}
ALIASES = REPO_ROOT / "assets" / "birdnet_aliases.json"

# Preference order. Anything added must be a format PIL opens and `dither` can quantize.
SUFFIXES = (".webp", ".png")


def _shape(scientific_name: str) -> str:
    """ "Turdus merula" -> "turdus-merula" (the file-key shape), name as given."""
    return scientific_name.strip().lower().replace(" ", "-")


def _aliases() -> dict[str, str]:
    """The vendored legacy -> current map, read once. Valued with the name as
    written, since `canonical` hands it to the dictionary and to a label."""
    try:
        loaded = json.loads(ALIASES.read_text())
    except (OSError, ValueError):
        return {}
    if not isinstance(loaded, dict):
        return {}
    aliases: dict[str, str] = {}
    for legacy, current in loaded.items():
        if not isinstance(legacy, str) or not isinstance(current, str):
            continue
        if _shape(legacy) != _shape(current):
            aliases[_shape(legacy)] = current.strip()
    return aliases


_CURRENT_NAME = _aliases()
_CURRENT_KEY = {legacy: _shape(name) for legacy, name in _CURRENT_NAME.items()}
# No current name has two legacy ones, so a plain inversion is the whole reverse.
_LEGACY_KEY = {current: legacy for legacy, current in _CURRENT_KEY.items()}


def normalize(scientific_name: str) -> str:
    """ "Turdus merula" -> "turdus-merula" (the file-key shape), under the name
    the detector reports today. Artwork keys, body mass and the species on the
    page all compare through here, so folding a reclassified bird's two names to
    one key is what makes them one bird everywhere above."""
    key = _shape(scientific_name)
    return _CURRENT_KEY.get(key, key)


def canonical(scientific_name: str) -> str:
    """The current name for a species, keeping the "Genus species" shape."""
    return _CURRENT_NAME.get(_shape(scientific_name), scientific_name.strip())


def artwork_keys(scientific_name: str) -> tuple[str, ...]:
    """Filename keys to look for a species' artwork under: the current name, then
    the label BirdNET still uses.

    Shipped plates only ever use the first - `tests/test_artwork_names.py`
    rejects the second, so the two namesets cannot drift apart again. The label's
    spelling is read for the sake of a style curated by hand, which no test of
    ours ever sees: someone who filed a jackdaw as "corvus-monedula.png" should
    not have it silently vanish from the glass on an update.
    """
    key = normalize(scientific_name)
    legacy = _LEGACY_KEY.get(key)
    return (key, legacy) if legacy else (key,)


def _by_stem(folder: Path, pattern: str = "*") -> dict[str, Path]:
    """Matching artwork keyed on stem. One entry per stem: a folder holding both
    formats for a bird would otherwise draw it twice and hold it as two variants."""
    found: dict[str, Path] = {}
    for suffix in reversed(SUFFIXES):  # preferred last: it overwrites the rest
        for path in folder.glob(f"{pattern}{suffix}"):
            found[path.stem] = path
    return found


def _artwork(folder: Path, stem: str) -> Path | None:
    """The one file a stem resolves to, in SUFFIXES order."""
    return next((path for s in SUFFIXES if (path := folder / f"{stem}{s}").exists()), None)


def artwork_in(folder: Path) -> list[Path]:
    """Every drawable file in a folder, one per stem, sorted. The curation tools
    list a style through this so they cannot disagree with the frame."""
    return sorted(_by_stem(folder).values())


def _holds_artwork(folder: Path) -> bool:
    """Whether anything drawable is in here. Short-circuits, since
    `available_styles` runs on every admin load and a shipped style is 800 files."""
    return any(next(folder.glob(f"*{s}"), None) is not None for s in SUFFIXES)


def available_styles(images_dir: Path) -> list[str]:
    """Style folders under `images_dir` that actually hold artwork, sorted.

    A folder with no birds in it is not a style you can pick: an empty `custom/`
    waiting to be filled would otherwise sit in the admin radio and blank the
    frame when selected. Perches alone do not count - there would be no birds.
    """
    try:
        return sorted(
            d.name for d in images_dir.iterdir() if d.is_dir() and _holds_artwork(d / BIRDS)
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
    """Every image the style keeps for a name: "<key>" plus its "<key>-N", under
    each of `artwork_keys` in turn. Shipped artwork answers to the first; the
    second only ever finds a hand-curated file (see `artwork_keys`), and finding
    one must not hide the plates filed under the current name.

    Numbered-only matching keeps a species key (e.g. tetrao-urogallus) from
    picking up a hybrid file (tetrao-urogallus-x-lagopus-lagopus.webp).
    """
    if not style:
        return []
    folder = images_dir / style / BIRDS
    variants: list[Path] = []
    for key in artwork_keys(scientific_name):
        numbered = re.compile(rf"{re.escape(key)}-(\d+)")
        base = [path] if (path := _artwork(folder, key)) else []
        rest = [
            (m, p)
            for stem, p in _by_stem(folder, f"{key}-*").items()
            if (m := numbered.fullmatch(stem))
        ]
        variants += base + [p for _m, p in sorted(rest, key=lambda mp: int(mp[0].group(1)))]
    return variants


_NUMBERED = re.compile(r"-\d+$")


def drawable_keys(images_dir: Path, style: str) -> set[str]:
    """Every species key the style can draw, from one directory listing.

    The plate modes ask this of the whole life list on every poll, and
    variants_for costs a glob per species - a hundred of them several times a
    minute is real work on an SD card.
    """
    if not style:
        return set()
    return {normalize(_NUMBERED.sub("", stem)) for stem in _by_stem(images_dir / style / BIRDS)}


def image_for(scientific_name: str, images_dir: Path, style: str, picks: Picks) -> Path | None:
    """The artwork this species is currently wearing, or None if it has none."""
    return picks.choose(scientific_name, variants_for(scientific_name, images_dir, style))


def perches_for(images_dir: Path, style: str) -> list[Path]:
    """The style's bare branches, drawn when nothing has been heard. Style-scoped
    like the birds: a perch is drawn in the same hand as the birds it stands in
    for, so a style without any draws none rather than borrowing another's."""
    return artwork_in(images_dir / style / PERCHES) if style else []


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
    its path relative to the folder the manifest sits in ("perches/oak.webp").
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
