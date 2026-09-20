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


@functools.cache
def _noise() -> np.ndarray:
    # shaped in frequency space, so it wraps and the tile repeats seamlessly
    rng = np.random.default_rng(0)
    freq = np.hypot(*np.meshgrid(np.fft.fftfreq(TILE), np.fft.fftfreq(TILE)))
    gain = np.maximum(freq, 1 / LARGEST) ** (-BETA / 2)
    shaped = np.fft.ifft2(np.fft.fft2(rng.normal(size=(TILE, TILE))) * gain).real
    return np.rint(shaped * (STRENGTH / shaped.std()))


@functools.cache
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


def _local_tone(rgb: np.ndarray, mask: np.ndarray) -> np.ndarray:
    """Local mean of `rgb` over `mask`, at the mask's pixels."""
    h, w = mask.shape
    k, r = HALO_BLOCK, HALO_SMOOTH

    def smooth(values: np.ndarray) -> np.ndarray:
        # whole blocks, so they scale back into place
        whole = np.pad(values, ((0, -h % k), (0, -w % k)))
        small = np.asarray(Image.fromarray(whole, "F").reduce(k))
        summed = _box_sum(_box_sum(small, r), r).astype(np.float32)
        up = Image.fromarray(summed, "F").resize(whole.shape[::-1], Image.Resampling.BILINEAR)
        return np.asarray(up)[:h, :w][mask]

    # divide after scaling up, so empty blocks never bleed in
    weight = smooth(mask.astype(np.float32))
    sums = np.stack([smooth(rgb[..., c].astype(np.float32) * mask) for c in range(3)], axis=-1)
    return sums / np.maximum(weight, 1e-3)[:, None]


def _reach(seed: np.ndarray, allowed: np.ndarray, steps: int) -> np.ndarray:
    """Steps to grow `seed` through `allowed`, 0 where never reached, 4-connected
    so thin ink stops it."""
    grown = seed
    depth = np.zeros(seed.shape, np.int16)
    for step in range(1, steps + 1):
        p = np.pad(grown, 1)
        near = p[1:-1, 1:-1] | p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
        nxt = seed | (near & allowed)
        depth[nxt & ~grown & allowed] = step
        grown = nxt
    return depth


def process_sprite(
    sprite: Image.Image,
    at: tuple[int, int],
    target=TARGET_PAPER,
    textured: bool = True,
) -> Image.Image:
    """Normalise a scaled RGBA sprite's paper halo to the shared tone and
    feather its edge. Returns a PAD-padded image to paste with its corner at
    `at`. When textured, the halo takes the page's texture under it so its edge
    does not read as an outline; on the flat panel page it stays flat."""
    arr = np.asarray(sprite).astype(np.int16)
    alpha, rgb = arr[..., 3], arr[..., :3]
    opaque = alpha > 24

    # sample the halo tone from the opaque ring next to the transparent edge
    near_edge = _box_sum((~opaque).astype(np.int32), 4) > 0
    ring = near_edge & opaque
    paper = np.median(rgb[ring], axis=0) if ring.sum() > 50 else np.array(target)

    # shift paper-like pixels to the target tone (tiny shift, so pale birds are safe)
    delta = np.array(target) - paper
    dist = np.abs(rgb - paper).max(2)
    sat = rgb.max(2) - rgb.min(2)
    paper_px = opaque & (dist < 50) & (sat < 55) & (rgb.max(2) > 160)
    out = arr.copy()
    out[paper_px, :3] = np.clip(rgb[paper_px] + delta, 0, 255)
    # scans shade across the halo: level paper near the cut, outside-in and capped
    depth = _reach(~opaque, paper_px, HALO_REACH)
    halo = depth > 0
    level = np.clip(
        np.rint(np.array(target) - _local_tone(out[..., :3], halo)), -HALO_SHIFT, HALO_SHIFT
    )
    # the band bites into pale plumage, so fade out rather than draw its edge there
    level *= np.clip((HALO_REACH - depth[halo]) / HALO_FADE, 0, 1)[:, None]
    out[halo, :3] = np.clip(out[halo, :3] + np.rint(level).astype(np.int16), 0, 255)
    # the outer ring's bright fringe (bg-removal + resize overshoot) survives the
    # median delta and rims the halo; snap it flat to target. Always halo paper.
    out[ring & paper_px, :3] = target

    # pad so the feather has room; give all transparent pixels the paper tone so
    # the feathered edge reveals paper, not whatever RGB sat under the alpha
    h, w = alpha.shape
    padded = np.zeros((h + 2 * PAD, w + 2 * PAD, 4), np.int16)
    padded[..., :3] = target
    padded[PAD : PAD + h, PAD : PAD + w] = out
    padded[padded[..., 3] <= 24, :3] = target

    if textured:
        paper_mask = padded[..., 3] <= 24
        paper_mask[PAD : PAD + h, PAD : PAD + w] |= paper_px
        rows = (np.arange(padded.shape[0]) + at[1]) % TILE
        cols = (np.arange(padded.shape[1]) + at[0]) % TILE
        texture = _noise()[np.ix_(rows, cols)].astype(np.int16)
        padded[paper_mask, :3] = np.clip(padded[paper_mask, :3] + texture[paper_mask, None], 0, 255)

    feathered = np.asarray(
        Image.fromarray(padded[..., 3].astype(np.uint8)).filter(ImageFilter.GaussianBlur(FEATHER))
    )
    padded[..., 3] = feathered
    return Image.fromarray(padded.astype(np.uint8), "RGBA")
