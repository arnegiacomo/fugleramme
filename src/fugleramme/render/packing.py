"""Where the birds go: the packers the collage can be laid out with.

The spiral walks candidate positions one at a time and takes the first that does
not collide. Simple, and the reason its page comes out as a round blob with bare
corners. Voids asks the question the other way round: get every legal position
for a sprite at once, then pick the one on the emptiest paper.

Both halves of that are cross-correlations, which one FFT pass answers for every
offset at once. Legal positions are the offsets where the sprite's mask and the
occupied page share no cell; scoring is the same operation against a field (how
empty the paper is, what the sprite would touch), so an aesthetic rule costs no
more than a collision test.

Voids packs on a grid of K pack-pixels per cell. Max-pooling both the page and
the sprite onto it can only over-report a collision, never miss one: a
fine-pixel overlap always lands in a cell both of them claim.

`settings.layout` picks one; `LAYOUTS` is what the admin offers (#47).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Sequence
from functools import partial
from typing import NamedTuple, Protocol

import numpy as np


class Sprite(Protocol):
    """What a packer needs of collage._Sprite: the footprint to keep clear."""

    @property
    def mask(self) -> np.ndarray: ...


Placed = list[tuple[Sprite, int, int]]
Packer = Callable[[Sequence[Sprite], int, int], Placed | None]
Cost = Callable[["Board", np.ndarray], np.ndarray]

_STEP = 6  # spiral: pixels between candidate positions
_PROBE_BANDS = 3
K = 6  # voids: pack pixels per cell, matching the spiral's step
_SIGMA = 8.0  # cells the emptiness field is measured over
_PAD = int(3 * _SIGMA) + 1  # solid border the page is blurred inside


def _ring(cx: float, cy: float, max_r: float) -> Iterator[tuple[float, float]]:
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


def spiral(sprites: Sequence[Sprite], width: int, height: int) -> Placed | None:
    """Place every sprite with no opaque overlap and fully on-screen, or return
    None if one does not fit. Sprites should be pre-sorted largest-first."""
    occ = np.zeros((height, width), dtype=bool)
    placed: Placed = []
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
        if self._blur is None:
            h, w = self.H + 2 * _PAD, self.W + 2 * _PAD
            yy, xx = np.fft.fftfreq(h)[:, None], np.fft.rfftfreq(w)[None, :]
            gauss = np.exp(-2 * (np.pi * _SIGMA) ** 2 * (yy**2 + xx**2))
            page = self._smooth(np.pad(np.ones((self.H, self.W)), _PAD), gauss)
            self._blur = (gauss, np.maximum(page, 1e-6))
        gauss, page_share = self._blur
        return self._smooth(np.pad((~self.occ).astype(float), _PAD), gauss) / page_share

    def _smooth(self, field: np.ndarray, gauss: np.ndarray) -> np.ndarray:
        blurred = np.fft.irfft2(np.fft.rfft2(field) * gauss, s=field.shape)
        return blurred[_PAD : _PAD + self.H, _PAD : _PAD + self.W]


def scored(sprites: Sequence[Sprite], width: int, height: int, cost: Cost) -> Placed | None:
    """Place each sprite at the cheapest legal offset, largest first as `spiral`
    takes them. None if one does not fit."""
    board = Board(width, height)
    placed: Placed = []
    for sprite in sprites:
        h, w = sprite.mask.shape
        mask = _pool(sprite.mask)
        ok = board.legal(mask, w, h)
        if not ok.any():
            return None
        y, x = np.unravel_index(np.argmin(np.where(ok, cost(board, mask), np.inf)), ok.shape)
        board.take(mask, int(y), int(x))
        placed.append((sprite, int(x) * K, int(y) * K))
    return placed


def _voids(board: Board, mask: np.ndarray, cling: float = 0.8, pull: float = 0.02) -> np.ndarray:
    """Put each bird on the emptiest paper it fits on, nestled against what is
    already there. The big birds spread over the whole sheet and the small ones
    fill what is left, corners included. `cling` weighs touching a neighbour,
    `pull` a slight preference for the middle."""
    area = max(1.0, float(mask.sum()))
    empty = board.against(board.emptiness(), mask) / area
    touch = board.against(board.halo(), mask) / area**0.5
    return -empty - cling * touch + pull * board.centres(mask)


class Layout(NamedTuple):
    label: str  # what the admin radio reads
    blurb: str  # its line in the admin hint
    pack: Packer
    # Bisection steps the size search may spend after its first fit. A spiral
    # pack costs ~3x a voids pack, so it keeps its first fit.
    refine: int


LAYOUTS = {
    "spiral": Layout("Spiral", "grows out from the middle", spiral, 0),
    "voids": Layout("Voids", "fills the emptiest spot first", partial(scored, cost=_voids), 3),
}

DEFAULT_LAYOUT = "spiral"


def layout_of(name: str) -> Layout:
    """The named layout, or the default."""
    return LAYOUTS.get(name, LAYOUTS[DEFAULT_LAYOUT])
