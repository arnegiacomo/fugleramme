"""Add one hand-edited cut-out to a style: pick the species, name the file, record the source.

The artwork pipeline that scrapes and cuts plates in bulk is workstation-only and
untracked. This is the other half: a bird you cut yourself (`docs/adding-artwork.md`)
that needs a BirdNET-valid filename, the next free variant number, and a line in the
style's manifest - the three things that are easy to get subtly wrong by hand and that
`tests/test_artwork_names.py` and the admin's provenance line both depend on.

Usage:
    uv run python tools/add_bird.py ~/Desktop/turtledove.png
    uv run python tools/add_bird.py bird.png --style custom --species "Turdus merula"
    uv run python tools/add_bird.py bird.png --preview /tmp/check.png --dry-run

Anything not given on the command line is asked for. The species prompt searches
BirdNET's label list by scientific or English name - type a few letters of either.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import NamedTuple

import numpy as np
from PIL import Image

from fugleramme.names import BIRDS, MANIFEST, manifest, normalize
from fugleramme.render.paper import paper_texture, process_sprite

REPO = Path(__file__).resolve().parents[1]
ARTWORK = REPO / "assets" / "artwork"
LABELS = REPO / "assets" / "birdnet_labels_v2.4.txt"
ATTRIBUTION = "ATTRIBUTION.md"

CAP = 1200  # longest side of a shipped plate; nothing ever draws a bird bigger
MATCHES = 12  # choices listed by the fallback search
PREVIEW = 760  # the preview render's square, px
_BIRD = 0.83  # longest side of the bird in it, as a fraction of the canvas
_NEW_SOURCE = "[enter a new artist/source]"
_warned_fzf = False


class Species(NamedTuple):
    key: str  # "streptopelia-decaocto", the filename stem
    sci: str
    common: str


def labels() -> list[Species]:
    """BirdNET v2.4's whole label list. A filename outside it fails the suite."""
    found = []
    for line in LABELS.read_text().splitlines():
        if "_" in line:
            sci, common = line.split("_", 1)
            found.append(Species(normalize(sci), sci.strip(), common.strip()))
    return found


def _ask(prompt: str) -> str:
    try:
        return input(f"{prompt} ").strip()
    except EOFError:
        sys.exit("\ncancelled")


def _fallback_matches(query: str, choices: list[str]) -> list[str]:
    words = query.lower().split()
    direct = [choice for choice in choices if all(word in choice.lower() for word in words)]
    if direct:
        return direct

    compact = "".join(words)
    loose = []
    for choice in choices:
        at = -1
        for char in compact:
            at = choice.lower().find(char, at + 1)
            if at < 0:
                break
        else:
            loose.append((at, choice))
    return [choice for _, choice in sorted(loose, key=lambda item: (item[0], len(item[1])))]


def _fallback_select(prompt: str, choices: list[str], query: str) -> str:
    while True:
        matches = _fallback_matches(query, choices) if query else choices
        if query and len(matches) == 1:
            return matches[0]
        shown = matches[:MATCHES]
        for number, choice in enumerate(shown, start=1):
            print(f"  {number:2}  {choice}")
        if len(matches) > len(shown):
            print(f"      ... and {len(matches) - len(shown)} more")
        if not matches:
            print("  no match")

        answer = _ask(f"\n{prompt} (search, number to pick, blank to cancel):")
        if not answer:
            return ""
        if answer.isdigit() and 1 <= int(answer) <= len(shown):
            return shown[int(answer) - 1]
        query = answer


def _select(prompt: str, choices: list[str], query: str = "") -> str:
    global _warned_fzf

    executable = shutil.which("fzf")
    if not executable:
        if not _warned_fzf:
            print("warning: fzf not found; using the Enter-based search fallback", file=sys.stderr)
            _warned_fzf = True
        return _fallback_select(prompt, choices, query)
    result = subprocess.run(
        [
            executable,
            "--height=40%",
            "--layout=reverse",
            "--border",
            f"--prompt={prompt}> ",
            f"--query={query}",
        ],
        input="\n".join(choices),
        text=True,
        stdout=subprocess.PIPE,
        check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def choose_species(species: list[Species], query: str) -> Species:
    """Pick a label by live fuzzy search over its scientific and common names."""
    choices = {f"{item.sci}  -  {item.common}": item for item in species}
    selected = _select("species", list(choices), query)
    if not selected:
        sys.exit("cancelled")
    return choices[selected]


def styles() -> list[str]:
    """Every style folder, including one still empty - an empty custom/ is exactly
    what you are filling. `names.available_styles` answers a different question."""
    return sorted(d.name for d in ARTWORK.iterdir() if d.is_dir())


def choose_style(requested: str) -> Path:
    if requested:
        return ARTWORK / requested
    present = styles()
    for number, name in enumerate(present, start=1):
        count = len(list((ARTWORK / name / BIRDS).glob("*.png")))
        print(f"  {number:2}  {name}  ({count} birds)")
    answer = _ask("\nstyle (number, or a name to start a new one):")
    if not answer:
        sys.exit("cancelled")
    if answer.isdigit() and 1 <= int(answer) <= len(present):
        return ARTWORK / present[int(answer) - 1]
    return ARTWORK / answer


def next_name(key: str, birds: Path) -> str:
    """The species' next free filename: "<key>.png", then "-2", "-3", ...

    Numbering has no gaps - `names.variants_for` walks them in order and the
    curation sheet renumbers a species whole - so the first free number is the one.
    """
    if not (birds / f"{key}.png").exists():
        return f"{key}.png"
    number = 2
    while (birds / f"{key}-{number}.png").exists():
        number += 1
    return f"{key}-{number}.png"


def _bbox(alpha: np.ndarray) -> tuple[int, int, int, int]:
    rows, cols = np.any(alpha > 0, axis=1), np.any(alpha > 0, axis=0)
    return (
        int(np.argmax(cols)),
        int(np.argmax(rows)),
        int(len(cols) - np.argmax(cols[::-1])),
        int(len(rows) - np.argmax(rows[::-1])),
    )


def _resize(img: Image.Image, cap: int) -> Image.Image:
    """Lanczos down to `cap` on premultiplied alpha. The pixels under a soft edge
    are whatever the cut-out left there; resampling straight RGBA drags them into
    the halo as a dark fringe, which prints."""
    scale = cap / max(img.size)
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))

    arr = np.asarray(img, dtype=np.float64)
    alpha = arr[..., 3:4] / 255.0
    premul = np.concatenate([arr[..., :3] * alpha, arr[..., 3:4]], axis=-1)
    out = np.asarray(
        Image.fromarray(premul.round().astype(np.uint8), "RGBA").resize(
            size, Image.Resampling.LANCZOS
        ),
        dtype=np.float64,
    )
    straight = np.clip(out[..., 3:4], 0, 255) / 255.0
    rgb = np.divide(out[..., :3], straight, out=np.zeros_like(out[..., :3]), where=straight > 1e-4)
    return Image.fromarray(
        np.clip(np.concatenate([rgb, straight * 255], axis=-1), 0, 255).astype(np.uint8), "RGBA"
    )


def prepare(path: Path, cap: int = CAP) -> Image.Image:
    """The file as the style ships it: cropped to its alpha and capped."""
    try:
        with Image.open(path) as opened:
            img = opened.convert("RGBA")
    except OSError as failure:
        sys.exit(f"cannot read {path}: {failure}")

    alpha = np.asarray(img)[..., 3]
    if not alpha.any():
        sys.exit(f"{path.name} is fully transparent")
    if alpha.min() == 255:
        print(f"  ! {path.name} has no transparent pixel - it will print as a rectangle")

    img = img.crop(_bbox(alpha))
    if max(img.size) > cap:
        img = _resize(img, cap)
        # Lanczos ringing can zero an edge row; re-crop so a second pass is a no-op.
        img = img.crop(_bbox(np.asarray(img)[..., 3]))
    return img


def preview(img: Image.Image, out: Path, size: int = PREVIEW) -> None:
    """The bird on the frame's own paper, at the frame's own halo treatment - the
    only honest look at whether the cut-out sits on the page."""
    scale = size * _BIRD / max(img.size)
    scaled = img.resize(
        (max(1, round(img.width * scale)), max(1, round(img.height * scale))),
        Image.Resampling.LANCZOS,
    )
    canvas = paper_texture(size, size)
    sprite = process_sprite(scaled)  # PAD-padded, so centring it centres the bird
    canvas.paste(sprite, ((size - sprite.width) // 2, (size - sprite.height) // 2), sprite)
    out.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out, format="PNG")


def known_sources(listed: dict[str, dict[str, str]]) -> list[str]:
    return sorted({entry["source"] for entry in listed.values() if entry.get("source")})


def choose_source(listed: dict[str, dict[str, str]]) -> dict[str, str]:
    """Ask for the required manifest entry for the new file."""
    selected = _select("artist/source", [*known_sources(listed), _NEW_SOURCE])
    if not selected:
        sys.exit("cancelled")
    source = _ask("artist/source name:") if selected == _NEW_SOURCE else selected
    if not source:
        sys.exit("cancelled")
    url = _ask("link to the plate (blank for none):")
    return {"source": source, "url": url} if url else {"source": source}


def check_attribution(style: Path, source: str) -> None:
    """ATTRIBUTION.md is prose about terms, so it is written by hand - but a source
    key naming no section there shows the reader nothing, so say when that happens."""
    path = style / ATTRIBUTION
    text = path.read_text().lower() if path.exists() else ""
    if source.lower() not in text:
        print(f"  ! {source} is not named in {style.name}/{ATTRIBUTION} - add its terms by hand")


def record(style: Path, filename: str, entry: dict[str, str]) -> None:
    """Add one line to the style's manifest, rewritten whole through a temp file so
    a crash never leaves half a record."""
    listed = {**manifest(style), f"{BIRDS}/{filename}": entry}
    path = style / MANIFEST
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(listed, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("image", type=Path, help="the cut-out to add, a transparent PNG")
    parser.add_argument("--style", default="", help="style folder to add to; asked for if omitted")
    parser.add_argument("--species", default="", help="scientific or English name, or a search")
    parser.add_argument(
        "--key", default="", help="filename stem outright, for a hybrid or an exception"
    )
    parser.add_argument("--source", default="", help="manifest source key; asked for if omitted")
    parser.add_argument("--url", default="", help="manifest link to the plate")
    parser.add_argument("--preview", type=Path, help="also write the bird on paper, to this path")
    parser.add_argument("--cap", type=int, default=CAP, help=f"longest side, px (default {CAP})")
    parser.add_argument(
        "--dry-run", action="store_true", help="say what would happen, leave the style alone"
    )
    args = parser.parse_args()

    if not args.image.exists():
        sys.exit(f"no such file: {args.image}")
    source = args.source.strip()
    if args.url and not source:
        sys.exit("--url needs a --source: a link with no work to name records nothing")

    style = choose_style(args.style)
    key = args.key or choose_species(labels(), args.species).key
    birds = style / BIRDS
    filename = next_name(key, birds) if birds.is_dir() else f"{key}.png"
    if source:
        entry = {"source": source, "url": args.url} if args.url else {"source": source}
    else:
        entry = choose_source(manifest(style))

    img = prepare(args.image, args.cap)
    dest = birds / filename
    print(f"\n  {args.image} -> {dest.relative_to(REPO)}  ({img.width}x{img.height})")
    print(f"  manifest: {BIRDS}/{filename} -> {json.dumps(entry, sort_keys=True)}")
    check_attribution(style, entry["source"])
    # Written on a dry run too: the point of the preview is deciding whether to
    # keep the cut-out, and it lands wherever you point it, not in the style.
    if args.preview:
        preview(img, args.preview)
        print(f"  preview: {args.preview}")

    if args.dry_run:
        print("\ndry run, the style is untouched")
        return

    birds.mkdir(parents=True, exist_ok=True)
    img.save(dest, "PNG")
    record(style, filename, entry)
    print("\nwritten")


if __name__ == "__main__":
    main()
