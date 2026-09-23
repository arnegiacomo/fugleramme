"""Finish a cut-out for add_bird.py: finish.py cut.png out.png

add_bird's own downscale premultiplies into 8 bits, which corrupts the colour of
low-alpha pixels; the frame draws anything over alpha 24, so they print as a dotted
ring at the halo's outer edge. A plate handed over at or under the cap skips that
step, so: crop to the alpha, downscale here in floating point, and set every pixel
that is not fully opaque to the exact halo tone - the outer edge is halo by
construction, so nothing of the bird is touched.
"""

import sys

import numpy as np
from PIL import Image

CAP = 1200
PAPER = (0xF0, 0xEC, 0xE5)

img = Image.open(sys.argv[1]).convert("RGBA")
arr = np.asarray(img).astype(np.float32)
alpha = arr[..., 3]
rows, cols = np.flatnonzero(alpha.any(1)), np.flatnonzero(alpha.any(0))
arr = arr[rows[0] : rows[-1] + 1, cols[0] : cols[-1] + 1]
h, w = arr.shape[:2]
scale = min(1.0, CAP / max(w, h))
size = (max(1, round(w * scale)), max(1, round(h * scale)))

a = arr[..., 3] / 255.0
planes = [arr[..., c] * a for c in range(3)] + [arr[..., 3]]
small = [np.asarray(Image.fromarray(p, "F").resize(size, Image.Resampling.LANCZOS)) for p in planes]
out_a = np.clip(small[3], 0, 255)
safe = np.maximum(out_a / 255.0, 1e-6)
rgb = np.stack([np.clip(small[c] / safe, 0, 255) for c in range(3)], axis=-1)
out_a = out_a.round()
rgb[out_a < 255] = PAPER
out = np.concatenate([rgb.round(), out_a[..., None]], axis=-1).astype(np.uint8)
Image.fromarray(out, "RGBA").save(sys.argv[2])
print(sys.argv[2], size)
