"""The fake BirdNET-Go, as a fixture: the tests reach it over the same /api/v2
a real detector serves. Plus the shipped artwork, decoded once for the guards
that read the whole library."""

from __future__ import annotations

import signal
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import NamedTuple

import numpy as np
import pytest
from PIL import Image

from fugleramme import fake, languages
from fugleramme.api import ApiSource
from fugleramme.names import SUFFIXES
from fugleramme.render import collage

ARTWORK = Path(__file__).resolve().parents[1] / "assets" / "artwork"

# The grids the duplicate guard compares on; its thresholds are tuned to this size.
GRID = 64


class Plate(NamedTuple):
    """One decode of a shipped cut-out, holding what every guard reads off it.

    `size` is the alpha-trimmed crop, which is what a bird box is fractions of;
    `outline` is the silhouette as a flat bool grid and `ink` its grey levels.
    """

    size: tuple[int, int]
    outline: np.ndarray
    ink: np.ndarray


def _decode(path: Path) -> Plate:
    image = Image.open(path).convert("RGBA")
    alpha = image.getchannel("A")
    bbox = alpha.getbbox()  # trim by alpha, not by RGB, exactly as `page.trim` does
    paper = Image.new("RGBA", image.size, (255, 255, 255, 255))
    grey = Image.alpha_composite(paper, image).convert("L").resize((GRID, GRID), Image.BILINEAR)
    return Plate(
        (bbox[2] - bbox[0], bbox[3] - bbox[1]) if bbox else image.size,
        np.asarray(alpha.resize((GRID, GRID), Image.BILINEAR), dtype=np.uint8).flatten() > 127,
        np.asarray(grey, dtype=np.float32).flatten(),
    )


@pytest.fixture(scope="session")
def library() -> dict[Path, Plate]:
    """Every shipped plate, decoded once.

    Two guards walk the whole library and decoding it is nearly all of both, so
    they share one pass rather than paying for it twice. Pillow drops the GIL to
    decode, which is what makes the pool worth having.
    """
    paths = sorted(path for suffix in SUFFIXES for path in ARTWORK.rglob(f"*{suffix}"))
    with ThreadPoolExecutor(max_workers=8) as pool:
        return dict(zip(paths, pool.map(_decode, paths), strict=True))


@pytest.fixture(autouse=True)
def _clean_language_caches(monkeypatch):
    """Module globals, so one test's detector must not leak into the next."""
    monkeypatch.setattr(languages, "_source", None)
    monkeypatch.setattr(languages, "_catalog", None)
    monkeypatch.setattr(languages, "_dicts", {})


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    """`service.run` installs its own, so one test must not leave pytest's own bound."""
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    yield
    for sig, handler in handlers.items():
        signal.signal(sig, handler)


@pytest.fixture(autouse=True)
def _no_cached_layouts():
    """A module global, so one test's packing must not answer for the next."""
    collage._layouts.clear()


@pytest.fixture
def crowded(tmp_path):
    """A page of `count` species, all drawn from one artwork file."""
    art = tmp_path / "bird.png"
    Image.new("RGBA", (200, 150), (40, 40, 40, 255)).save(art)
    return lambda count=40: [(f"Genus species{n}", art) for n in range(count)]


@pytest.fixture
def detector():
    """Start a fake on an OS-assigned port; `rows` replaces the generated ones.
    Returns (base URL, server) - the row list is live, so appending to it is
    what a new detection looks like."""
    servers = []

    def start(rows=None, count: int = 40, seed: int = 1, **kwargs):
        httpd = fake.serve(
            fake.generate(count, seed) if rows is None else rows, "127.0.0.1", 0, **kwargs
        )
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}", httpd

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def source(detector):
    """An ApiSource over a fresh fake."""

    def start(**kwargs) -> ApiSource:
        url, _httpd = detector(**kwargs)
        return ApiSource(url)

    return start
