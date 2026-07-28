"""Normalise a source's cut-outs in place so it sits on the same page as the others.

    uv run --with scipy python scripts/normalize_cutouts.py gould

Fades the paper halo and pulls the black point down to match von Wright. The
halo is a uniform dilation of the subject (`wikimedia-scrape/common/background.py`),
so its width is measurable and the fade is pure geometry - no tone test touches
the subject, which matters because on these plates a white swan and the paper
are the same colour. The black point is the real difference between the sources:
same chroma, but Gould's darkest 5% sits at 66 against von Wright's 21.

NOT idempotent - run once against committed assets (`git checkout` to redo).
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter
from scipy import ndimage

ASSETS = Path(__file__).resolve().parents[1] / "assets" / "birds"

INK = 165          # gray level that is unambiguously printed content, as background.py
EDGE_FLOOR = 0.10  # fraction of the halo band left fully transparent at the outer edge
BLACK_TARGET = 21.0
DARK_PCT = 5.0     # percentile of ink taken as the plate's black point


def _paper_tone(rgb, opaque):
    """The scan-paper tone, sampled from the opaque ring next to the cut edge."""
    near = np.asarray(
        Image.fromarray(((~opaque) * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(9))
    ) > 0
    ring = near & opaque
    return np.median(rgb[ring], axis=0) if ring.sum() > 50 else np.array([242.0, 237.0, 226.0])


def fade_halo(img: Image.Image) -> Image.Image:
    arr = np.asarray(img.convert("RGBA")).astype(np.float32)
    alpha, gray = arr[..., 3], arr[..., :3].mean(2)
    solid = alpha > 127
    dist = ndimage.distance_transform_edt(solid).astype(np.float32)

    ink = solid & (gray < INK)
    # the shallowest ink is the halo's width; percentile, not min, to shrug off
    # a stray dark speck the keying left in the ring
    band = float(np.percentile(dist[ink], 1.0)) if ink.sum() >= 200 \
        else float(np.percentile(dist[solid], 60))
    if band < 2:
        return img

    lo = EDGE_FLOOR * band
    keep = np.clip((dist - lo) / max(band - lo, 1e-6), 0, 1)
    keep = keep * keep * (3 - 2 * keep)             # smoothstep, no banding at the ends

    out = arr.copy()
    out[..., 3] = alpha * keep
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def stretch(img: Image.Image, black_target: float = BLACK_TARGET) -> Image.Image:
    arr = np.asarray(img.convert("RGBA")).astype(np.float32)
    alpha, rgb = arr[..., 3], arr[..., :3]
    opaque = alpha > 127
    if opaque.sum() < 1000:
        return img

    white = float(_paper_tone(rgb, opaque).mean())
    lum = rgb.mean(2)
    ink = opaque & (lum < white - 30)
    if ink.sum() < 1000:
        return img

    # one scalar black point and gain for all three channels: a per-channel
    # stretch pulls the channels apart by different amounts and shifts hue
    lo = float(np.percentile(lum[ink], DARK_PCT))
    if lo >= white - 40 or lo <= black_target:      # already contrasty, leave it
        return img
    gain = (white - black_target) / (white - lo)

    out = arr.copy()
    out[..., :3] = np.clip(black_target + (rgb - lo) * gain, 0, 255)
    return Image.fromarray(out.astype(np.uint8), "RGBA")


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python scripts/normalize_cutouts.py <source>")
    folder = ASSETS / sys.argv[1]
    if not folder.is_dir():
        sys.exit(f"no such source folder: {folder}")

    files = sorted(folder.glob("*.png"))
    print(f"normalising {len(files)} cut-outs in {folder}")
    for i, path in enumerate(files, 1):
        stretch(fade_halo(Image.open(path))).save(path)
        if i % 25 == 0 or i == len(files):
            print(f"\r  {i}/{len(files)}", end="", flush=True)
    print("\ndone")


if __name__ == "__main__":
    main()
