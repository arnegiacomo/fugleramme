"""Where the birds go: every packer the collage can be laid out with.

The spiral walks candidate positions one at a time and takes the first that does
not collide. Simple, and the reason its page comes out as a round blob with bare
corners. The others ask the question the other way round: get every legal
position for a sprite at once, then pick one by whatever the page should look
like.

Both halves of that are one FFT. Legal positions are the offsets where the
sprite's mask and the occupied page share no cell - a cross-correlation, which
the FFT gives for all offsets in a single pass. Scoring is the same operation
against a field (how empty the paper is, what the sprite would touch), so an
aesthetic rule costs no more than a collision test.

Those pack on a grid of K pack-pixels per cell. Max-pooling both the page and
the sprite onto it can only over-report a collision, never miss one: a
fine-pixel overlap always lands in a cell both of them claim.

`settings.layout` picks one; `LAYOUTS` is what the admin offers (#47).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from functools import partial
from typing import NamedTuple, Protocol

import numpy as np


class Sprite(Protocol):
    """What a packer needs of collage._Sprite: the footprint to keep clear.
    Read-only, since the sprite it is matched against is a frozen dataclass."""

    @property
    def mask(self) -> np.ndarray: ...


Packer = Callable[[Sequence[Sprite], int, int], list[tuple[Sprite, int, int]] | None]
Cost = Callable[["Board", np.ndarray, int], np.ndarray]

_STEP = 6  # spiral: pixels between candidate positions
_PROBE_BANDS = 3
K = 6  # grid packers: pack pixels per cell, matching the spiral's step
_JITTER = 0.7  # cells of tie-breaking noise
_SIGMA = 8.0  # cells the emptiness field is measured over


def _ring(cx: float, cy: float, max_r: float):
    yield cx, cy
    r = _STEP
    while r <= max_r:
        count = max(8, int(2 * math.pi * r / _STEP))
        for i in range(count):
            a = 2 * math.pi * i / count
            yield cx + r * math.cos(a), cy + r * math.sin(a)
        r += _STEP


def _probes(mask: np.ndarray) -> list[tuple[int, np.ndarray]]:
    """One row per horizontal band of a sprite, tested before its whole footprint.
    Most candidate positions on a filling page collide, and a row costs a
    hundredth of the box. Banded rather than simply the densest rows, which all
    land in the body and catch the same collisions as each other."""
    density = mask.sum(axis=1)
    probes = []
    for band in np.array_split(np.arange(len(density)), _PROBE_BANDS):
        if band.size and density[band].max():
            row = int(band[int(np.argmax(density[band]))])
            probes.append((row, mask[row]))
    return probes


def spiral(sprites: Sequence[Sprite], width: int, height: int):
    """Place every sprite with no opaque overlap and fully on-screen, or return
    None if one does not fit. Sprites should be pre-sorted largest-first."""
    occ = np.zeros((height, width), dtype=bool)
    placed = []
    max_r = math.hypot(width, height)
    for sprite in sprites:
        h, w = sprite.mask.shape
        probes = _probes(sprite.mask)
        spot = None
        for px, py in _ring(width / 2, height / 2, max_r):
            x, y = int(px - w / 2), int(py - h / 2)
            if x < 0 or y < 0 or x + w > width or y + h > height:
                continue
            # A colliding probe row is a real collision, so this only ever skips
            # the box test for positions it would have rejected anyway.
            if any((occ[y + r, x : x + w] & row).any() for r, row in probes):
                continue
            if not (occ[y : y + h, x : x + w] & sprite.mask).any():
                spot = (x, y)
                break
        if spot is None:
            return None
        x, y = spot
        occ[y : y + h, x : x + w] |= sprite.mask
        placed.append((sprite, x, y))
    return placed


def _pool(mask: np.ndarray) -> np.ndarray:
    ph, pw = -mask.shape[0] % K, -mask.shape[1] % K
    if ph or pw:
        mask = np.pad(mask, ((0, ph), (0, pw)))
    return mask.reshape(mask.shape[0] // K, K, mask.shape[1] // K, K).any(axis=(1, 3))


def _dilate(a: np.ndarray) -> np.ndarray:
    p = np.pad(a, 1, constant_values=False)
    return p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]


class Board:
    """The page as a grid of cells, and the fields a cost scores against."""

    def __init__(self, width: int, height: int) -> None:
        self.W, self.H = -(-width // K), -(-height // K)
        self.width, self.height = width, height
        self.occ = np.zeros((self.H, self.W), dtype=bool)
        yy, xx = np.mgrid[0 : self.H, 0 : self.W]
        self.yy, self.xx = yy.astype(float), xx.astype(float)
        self._blur: tuple[np.ndarray, np.ndarray] | None = None

    def against(self, field: np.ndarray, mask: np.ndarray) -> np.ndarray:
        """What the sprite would cover of `field`, for every offset at once."""
        m = np.zeros((self.H, self.W))
        m[: mask.shape[0], : mask.shape[1]] = mask
        spectrum = np.fft.rfft2(field) * np.conj(np.fft.rfft2(m))
        return np.fft.irfft2(spectrum, s=(self.H, self.W))

    def legal(self, mask: np.ndarray, w: int, h: int) -> np.ndarray:
        """The offsets where the sprite neither overlaps nor runs off the page.

        None at all if the sprite is bigger than the page: a name can widen a
        bird past the paper, and the size search reads that as a size to shrink.
        """
        if mask.shape[0] > self.H or mask.shape[1] > self.W:
            return np.zeros((self.H, self.W), dtype=bool)
        ok = self.against(self.occ.astype(float), mask) < 0.5
        ok[(self.height - h) // K + 1 :, :] = False
        ok[:, (self.width - w) // K + 1 :] = False
        return ok

    def take(self, mask: np.ndarray, y: int, x: int) -> None:
        self.occ[y : y + mask.shape[0], x : x + mask.shape[1]] |= mask

    def centres(self, mask: np.ndarray) -> np.ndarray:
        """Distance from the sprite's centre to the page's, per offset."""
        return np.hypot(
            self.yy + mask.shape[0] / 2 - self.H / 2,
            self.xx + mask.shape[1] / 2 - self.W / 2,
        )

    def halo(self) -> np.ndarray:
        """The free cells touching something solid. The page edge counts too, so
        tucking into a corner scores like nestling against a neighbour."""
        ext = np.pad(self.occ, 1, constant_values=True)
        return (_dilate(ext)[1:-1, 1:-1] & ~self.occ).astype(float)

    def emptiness(self) -> np.ndarray:
        """How empty the paper is around each cell: free cells blurred over a
        neighbourhood, as a fraction of the page inside it.

        Blurred on a padded grid with the outside solid, since a periodic FFT
        would otherwise let the right edge's empty paper make the left edge look
        empty; normalised by the same blur of the page, so a corner does not
        score merely for having less page around it.
        """
        pad = int(3 * _SIGMA) + 1
        if self._blur is None:
            h, w = self.H + 2 * pad, self.W + 2 * pad
            yy, xx = np.fft.fftfreq(h)[:, None], np.fft.rfftfreq(w)[None, :]
            gauss = np.exp(-2 * (np.pi * _SIGMA) ** 2 * (yy**2 + xx**2))
            page = np.zeros((h, w))
            page[pad : pad + self.H, pad : pad + self.W] = 1.0
            self._blur = (gauss, np.maximum(self._smooth(page, gauss, pad), 1e-6))
        gauss, page_share = self._blur
        free = np.zeros((self.H + 2 * pad, self.W + 2 * pad))
        free[pad : pad + self.H, pad : pad + self.W] = ~self.occ
        return self._smooth(free, gauss, pad) / page_share

    def _smooth(self, field: np.ndarray, gauss: np.ndarray, pad: int) -> np.ndarray:
        blurred = np.fft.irfft2(np.fft.rfft2(field) * gauss, s=field.shape)
        return blurred[pad : pad + self.H, pad : pad + self.W]


def _noise(shape: tuple[int, int], n: int) -> np.ndarray:
    """Sub-cell noise, so a spread of equally good positions does not always
    resolve to the same side of the tie. Seeded by placement order: a given set
    of birds lays out the same way every render."""
    return np.random.default_rng(n).random(shape)


def scored(sprites: Sequence[Sprite], width: int, height: int, cost: Cost):
    """Place each sprite at the cheapest legal offset, largest first as `spiral`
    takes them. None if one does not fit."""
    board = Board(width, height)
    placed = []
    for n, sprite in enumerate(sprites):
        h, w = sprite.mask.shape
        mask = _pool(sprite.mask)
        ok = board.legal(mask, w, h)
        if not ok.any():
            return None
        y, x = np.unravel_index(np.argmin(np.where(ok, cost(board, mask, n), np.inf)), ok.shape)
        board.take(mask, int(y), int(x))
        placed.append((sprite, int(x) * K, int(y) * K))
    return placed


def _centre(board: Board, mask: np.ndarray, n: int) -> np.ndarray:
    """The spiral's own rule - nearest the middle - asked of every position at
    once rather than walked outward."""
    return board.centres(mask) + _JITTER * _noise((board.H, board.W), n)


def _voids(
    board: Board, mask: np.ndarray, n: int, cling: float = 0.8, pull: float = 0.02
) -> np.ndarray:
    """Put each bird on the emptiest paper it fits on, nestled against what is
    already there. The big birds spread over the whole sheet and the small ones
    fill what is left, corners included."""
    area = max(1.0, float(mask.sum()))
    empty = board.against(board.emptiness(), mask) / area
    touch = board.against(board.halo(), mask) / area**0.5
    return -empty - cling * touch + pull * board.centres(mask)


class Layout(NamedTuple):
    label: str  # what the admin menu reads
    blurb: str
    pack: Packer
    # Bisection steps the size search may spend after its first fit. Only worth
    # it where a pack is cheap: the spiral's costs three times an FFT pack's.
    refine: int


LAYOUTS = {
    "spiral": Layout("Spiral", "biggest in the middle", spiral, 0),
    "centre": Layout(
        "Spiral (fast)", "the same idea, packed closer", partial(scored, cost=_centre), 3
    ),
    "voids": Layout("Voids", "spread out", partial(scored, cost=_voids), 3),
}

DEFAULT_LAYOUT = "spiral"


def layout_of(name: str) -> Layout:
    """The named layout, or the default for anything settings did not settle."""
    return LAYOUTS.get(name, LAYOUTS[DEFAULT_LAYOUT])
