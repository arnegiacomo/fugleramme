"""Make the birds look printed on one continuous sheet of aged paper.

The von Wright cut-outs keep a ring of the original scan paper around each
subject (a "halo"), and the scans vary in tone. Rather than fight that, we lean
into it: normalise every halo to one shared paper tone, render the page as a
subtly textured paper of that same tone, and feather each halo's edge so the
patch melts into the page. Done at render time so tone/texture/feather stay
tunable (a future admin panel can expose them); the source assets are untouched.
"""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageFilter

TARGET_PAPER = (242, 237, 226)
FEATHER = 5                     # gaussian blur sigma (px)
PAD = 16                        # transparent margin for the feather to bleed into


def paper_texture(width: int, height: int, base=TARGET_PAPER, seed: int = 0) -> Image.Image:
    """A subtly textured paper background: fine even grain with a faint mottle.

    Kept high-frequency on purpose - a strong low-frequency component reads as
    splotches rather than paper.
    """
    rng = np.random.default_rng(seed)
    fine = rng.normal(0, 2.6, (height, width))
    fine = np.asarray(
        Image.fromarray((fine + 128).clip(0, 255).astype(np.uint8))
        .filter(ImageFilter.GaussianBlur(0.6))
    ).astype(np.float32) - 128
    mottle = rng.normal(0, 1.4, (height // 16 + 1, width // 16 + 1))
    mottle = np.asarray(
        Image.fromarray((mottle + 128).clip(0, 255).astype(np.uint8))
        .resize((width, height), Image.BICUBIC)
    ).astype(np.float32) - 128
    noise = fine + mottle
    tex = np.clip(np.array(base)[None, None, :] + noise[..., None], 0, 255).astype(np.uint8)
    return Image.fromarray(tex, "RGB")


def process_sprite(sprite: Image.Image, target=TARGET_PAPER) -> Image.Image:
    """Normalise a scaled RGBA sprite's paper halo to the shared tone and
    feather its edge. Returns a PAD-padded image; composite it offset by
    (-PAD, -PAD)."""
    arr = np.asarray(sprite).astype(np.int16)
    alpha, rgb = arr[..., 3], arr[..., :3]
    opaque = alpha > 24

    # sample the halo tone from the opaque ring next to the transparent edge
    near_edge = np.asarray(
        Image.fromarray(((~opaque) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))
    ) > 0
    ring = near_edge & opaque
    paper = np.median(rgb[ring], axis=0) if ring.sum() > 50 else np.array(target)

    # shift paper-like pixels to the target tone (tiny shift, so pale birds are safe)
    delta = np.array(target) - paper
    dist = np.abs(rgb - paper).max(2)
    sat = rgb.max(2) - rgb.min(2)
    paper_px = opaque & (dist < 50) & (sat < 55) & (rgb.max(2) > 160)
    out = arr.copy()
    out[paper_px, :3] = np.clip(rgb[paper_px] + delta, 0, 255)

    # pad so the feather has room; give all transparent pixels the paper tone so
    # the feathered edge reveals paper, not whatever RGB sat under the alpha
    h, w = alpha.shape
    padded = np.zeros((h + 2 * PAD, w + 2 * PAD, 4), np.int16)
    padded[..., :3] = target
    padded[PAD:PAD + h, PAD:PAD + w] = out
    padded[padded[..., 3] <= 24, :3] = target

    feathered = np.asarray(
        Image.fromarray(padded[..., 3].astype(np.uint8)).filter(ImageFilter.GaussianBlur(FEATHER))
    )
    padded[..., 3] = feathered
    return Image.fromarray(padded.astype(np.uint8), "RGBA")
