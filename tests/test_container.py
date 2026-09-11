"""What the container image ships, read back out of the Dockerfile.

Nothing else checks the per-letter COPY ranges: a plate outside them is missing
from the image and from nowhere else, and the frame would simply draw fewer
birds. So these hold the globs to the artwork on disk.
"""

from __future__ import annotations

import fnmatch
import re
import string
from pathlib import Path

import pytest

from fugleramme.names import SUFFIXES

REPO = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO / "Dockerfile"
BIRDS = "assets/artwork/classic/birds/"
EXAMPLE = REPO / "examples" / "docker-compose.yml"
DETECTOR = REPO / "detector" / "docker-compose.yml"


def _pinned(compose: Path) -> str:
    """The BirdNET-Go image the compose file names, tag included."""
    return re.search(r"image:\s*(ghcr\.io/tphakala/birdnet-go:\S+)", compose.read_text()).group(1)


def test_the_example_pins_the_detector_the_pi_ships():
    """The pin only moves after it is tested on the Pi, and two compose files
    name it. One drifting behind hands a new reader a version nobody runs."""
    assert _pinned(EXAMPLE) == _pinned(DETECTOR)


def _sources() -> list[str]:
    """Every context path the image copies in. The last token of a COPY is its
    destination, and a `--from` stage copies out of the build, not the repo."""
    sources = []
    for line in DOCKERFILE.read_text().splitlines():
        if not line.startswith("COPY ") or "--from=" in line:
            continue
        tokens = [t for t in line.split()[1:] if not t.startswith("--")]
        sources += tokens[:-1]
    return sources


def _matched(pattern: str) -> list[Path]:
    """The files a COPY source pulls in, a directory's whole tree included."""
    files = []
    for path in REPO.glob(pattern):
        files += [p for p in path.rglob("*") if p.is_file()] if path.is_dir() else [path]
    return files


def _plates() -> list[Path]:
    """Every image the frame would draw. Off names.SUFFIXES like the rest of the
    artwork guards, so a format the frame learns to read is one the image ships."""
    artwork = REPO / "assets" / "artwork"
    return sorted(p for suffix in SUFFIXES for p in artwork.rglob(f"*{suffix}"))


def test_every_shipped_plate_lands_in_the_image():
    copied = {p for source in _sources() for p in _matched(source)}
    missing = [p.relative_to(REPO) for p in _plates() if p not in copied]
    assert not missing, f"artwork no COPY line reaches: {missing}"


@pytest.mark.parametrize("letter", string.ascii_lowercase)
def test_the_letter_ranges_leave_no_gap(letter):
    """No plate starts with k, q, w or y today. A range that skipped them would
    only be noticed the day BirdNET reports one of those species."""
    globs = [source[len(BIRDS) :] for source in _sources() if source.startswith(BIRDS)]
    assert any(fnmatch.fnmatchcase(f"{letter}-species.webp", glob) for glob in globs)


@pytest.mark.parametrize("source", [s for s in _sources() if s.startswith(BIRDS)])
def test_every_range_still_holds_a_plate(source):
    """A COPY whose glob matches nothing fails the build, so an emptied range is
    a broken image rather than a smaller one."""
    assert _matched(source), f"{source} matches nothing"
