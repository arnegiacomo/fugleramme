"""Make the birds look printed on one continuous sheet of aged paper.

The von Wright cut-outs keep a ring of the original scan paper around each
subject (a "halo"), and the scans vary in tone. Rather than fight that, we lean
into it: normalise every halo to one shared paper tone, render the page as a
subtly textured paper of that same tone, and feather each halo's edge so the
patch melts into the page. Done at render time so tone/texture/feather stay
tunable (a future admin panel can expose them); the source assets are untouched.
"""

from __future__ import annotations

import functools

import numpy as np
from PIL import Image, ImageFilter

TARGET_PAPER = (242, 237, 226)
# The panel has one white and no warm neutral, so a paper this close to its white
# quantises flat - and so does any bird brighter than it. Toned off the palette
# white, the dither stipples the page and leaves white plumage bare. See #138.
PANEL_PAPER = (233, 225, 202)
FEATHER = 5  # gaussian blur sigma (px)
PAD = 16  # transparent margin for the feather to bleed into
TILE = 512  # px, repeated by kiosk.html too
STRENGTH = 1.6  # levels
BETA = 2.0  # higher is cloudier
LARGEST = 96  # px, largest cloud
HALO_REACH = 24  # px from the cut
HALO_BLOCK = 4  # px, resolution of the local tone
HALO_SMOOTH = 1  # blocks either side
HALO_SHIFT = 6  # levels, cap
HALO_FADE = 8  # steps, ramp to nothing
HALO_NEAR = 12  # levels from the halo's tone that count toward its local tone


@functools.cache
def _noise() -> np.ndarray:
    # shaped in frequency space, so it wraps and the tile repeats seamlessly
    rng = np.random.default_rng(0)
    freq = np.hypot(*np.meshgrid(np.fft.fftfreq(TILE), np.fft.fftfreq(TILE)))
    gain = np.maximum(freq, 1 / LARGEST) ** (-BETA / 2)
    shaped = np.fft.ifft2(np.fft.fft2(rng.normal(size=(TILE, TILE))) * gain).real
    return np.rint(shaped * (STRENGTH / shaped.std())).astype(np.int8)


def _tile() -> np.ndarray:
    tex = np.array(TARGET_PAPER)[None, None, :] + _noise()[..., None]
    return np.clip(tex, 0, 255).astype(np.uint8)


def paper_tile() -> Image.Image:
    return Image.fromarray(_tile(), "RGB")


def paper_texture(width: int, height: int) -> Image.Image:
    """A subtly textured paper background: soft clouds over a faint grain.

    Capped at `LARGEST` on purpose - a strong low-frequency component reads as
    splotches rather than paper.
    """
    tile = _tile()
    reps = (height // TILE + 1, width // TILE + 1, 1)
    return Image.fromarray(np.tile(tile, reps)[:height, :width], "RGB")


def _box_sum(a: np.ndarray, r: int) -> np.ndarray:
    """Sum over a (2r+1)-square window, zero outside the array."""
    pad = [(r + 1, r), (r + 1, r)] + [(0, 0)] * (a.ndim - 2)
    c = np.pad(a, pad).cumsum(0).cumsum(1)
    k = 2 * r + 1
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def _local_tone(rgb: np.ndarray, mask: np.ndarray, at: np.ndarray) -> np.ndarray:
    """Local mean of `rgb` over `mask`, at the pixels of `at`."""
    h, w = mask.shape
    k, r = HALO_BLOCK, HALO_SMOOTH

    def smooth(values: np.ndarray) -> np.ndarray:
        # whole blocks, so they scale back into place
        whole = np.pad(values, ((0, -h % k), (0, -w % k)))
        small = np.asarray(Image.fromarray(whole, "F").reduce(k))
        summed = _box_sum(_box_sum(small, r), r).astype(np.float32)
        up = Image.fromarray(summed, "F").resize(whole.shape[::-1], Image.Resampling.BILINEAR)
        return np.asarray(up)[:h, :w][at]

    # divide after scaling up, so empty blocks never bleed in
    weight = smooth(mask.astype(np.float32))
    sums = np.stack([smooth(rgb[..., c].astype(np.float32) * mask) for c in range(3)], axis=-1)
    return sums / np.maximum(weight, 1e-3)[:, None]


def _reach(seed: np.ndarray, allowed: np.ndarray, steps: int) -> np.ndarray:
    """Steps to grow `seed` through `allowed`, 0 where never reached, 4-connected
    so thin ink stops it. Each step starts from the pixels the last one reached,
    not from the whole array: they are a thin line of it."""
    # Padded with pixels that are never open, so a hop off an edge finds nothing.
    grown = np.pad(seed, 1)
    todo = np.pad(allowed & ~seed, 1)
    width = todo.shape[1]
    near = np.zeros_like(grown)
    near[1:-1, 1:-1] = grown[:-2, 1:-1] | grown[2:, 1:-1] | grown[1:-1, :-2] | grown[1:-1, 2:]
    edge = np.flatnonzero(todo & near)
    todo = todo.ravel()
    todo[edge] = False
    depth = np.zeros(todo.shape, np.int16)
    for step in range(1, steps + 1):
        depth[edge] = step
        reached = []
        for hop in (-width, -1, 1, width):
            there = edge + hop
            there = there[todo[there]]
            todo[there] = False  # closed as it is reached, so no pixel comes twice
            reached.append(there)
        edge = np.concatenate(reached)
    return depth.reshape(grown.shape)[1:-1, 1:-1]


def process_sprite(
    sprite: Image.Image,
    at: tuple[int, int],
    target=None,
    textured: bool = True,
) -> Image.Image:
    """Normalise a scaled RGBA sprite's paper halo to the shared tone and
    feather its edge. Returns a PAD-padded image to paste with its corner at
    `at`. When textured, the halo takes the page's texture under it so its edge
    does not read as an outline; on the flat panel page it stays flat."""
    target = target or (TARGET_PAPER if textured else PANEL_PAPER)
    # one uint8 buffer throughout, padded so the feather has room. `out` is the
    # sprite in its middle and `rgb` the same pixels, so `rgb` follows every write
    # to `out`. uint8 wraps: widen before a sum or difference that can leave 0..255
    h, w = sprite.height, sprite.width
    padded = np.zeros((h + 2 * PAD, w + 2 * PAD, 4), np.uint8)
    padded[..., :3] = target
    out = padded[PAD : PAD + h, PAD : PAD + w]
    out[:] = np.asarray(sprite)
    alpha, rgb = out[..., 3], out[..., :3]
    opaque = alpha > 24

    # sample the halo tone from the opaque ring next to the transparent edge
    near_edge = _box_sum((~opaque).astype(np.int32), 4) > 0
    ring = near_edge & opaque
    sampled = np.median(rgb[ring], axis=0) if ring.sum() > 50 else np.array(target)
    # float32 holds a median of whole numbers exactly, and `dist` below comes out half the size
    paper = sampled.astype(np.float32)

    # shift paper-like pixels to the target tone (tiny shift, so pale birds are safe)
    delta = np.array(target) - paper
    # a channel at a time, here and below: across an axis of three numpy works pixel by pixel
    channels = [rgb[..., c] for c in range(3)]
    dist = np.maximum.reduce(
        [np.abs(one.astype(np.float32) - tone) for one, tone in zip(channels, paper, strict=True)]
    )
    high, low = np.maximum.reduce(channels), np.minimum.reduce(channels)
    paper_px = opaque & (dist < 50) & (high - low < 55) & (high > 160)
    for one, shift in zip(channels, delta, strict=True):
        one[paper_px] = np.clip(one[paper_px] + shift, 0, 255)
    # scans shade across the halo: level paper near the cut, outside-in and capped
    depth = _reach(~opaque, paper_px, HALO_REACH)
    halo = depth > 0
    # tone from the halo's own paper only: a pale outline in the band would rim the bird
    level = np.clip(
        np.rint(np.array(target) - _local_tone(out[..., :3], halo & (dist < HALO_NEAR), halo)),
        -HALO_SHIFT,
        HALO_SHIFT,
    )
    # the band bites into pale plumage, so fade out rather than draw its edge there
    level *= np.clip((HALO_REACH - depth[halo]) / HALO_FADE, 0, 1)[:, None]
    out[halo, :3] = np.clip(
        out[halo, :3].astype(np.int16) + np.rint(level).astype(np.int16), 0, 255
    )
    # the outer ring's bright fringe (bg-removal + resize overshoot) survives the
    # median delta and rims the halo; snap it flat to target. Always halo paper.
    out[ring & paper_px, :3] = target

    # give all transparent pixels the paper tone so the feathered edge reveals
    # paper, not whatever RGB sat under the alpha
    paper_mask = padded[..., 3] <= 24
    for c in range(3):
        np.putmask(padded[..., c], paper_mask, target[c])

    if textured:
        paper_mask[PAD : PAD + h, PAD : PAD + w] |= paper_px
        rows = (np.arange(padded.shape[0]) + at[1]) % TILE
        cols = (np.arange(padded.shape[1]) + at[0]) % TILE
        # nothing off the paper, so the whole sprite takes it in one sum
        texture = (_noise()[np.ix_(rows, cols)] * paper_mask).astype(np.int16)
        for c in range(3):
            padded[..., c] = np.clip(padded[..., c] + texture, 0, 255)

    feathered = np.asarray(
        Image.fromarray(padded[..., 3]).filter(ImageFilter.GaussianBlur(FEATHER))
    )
    padded[..., 3] = feathered
    return Image.fromarray(padded, "RGBA")
