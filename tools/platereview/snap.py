"""Snap a hand-traced outline onto the inked edge it was following.

    snap.py spec.json ymin [reach]

The trace is resampled every 2 px. At each sample the scan is read along the normal, from
`reach` px outside to `reach` px inside, and the edge is put where the tone first drops
well below what lies outside - the bird's ink line against the painted ground. Shifts are
median-smoothed along the contour, so one bad reading cannot kink the edge, and samples
with no clear drop keep the traced position. Only samples below ymin are moved. The
original trace is kept in the spec as outline_traced.
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

spec_path = Path(sys.argv[1])
ymin, reach = int(sys.argv[2]), int(sys.argv[3]) if len(sys.argv) > 3 else 6
spec = json.loads(spec_path.read_text())
traced = np.array(spec.get("outline_traced", spec["outline"]), dtype=float)
lum = np.asarray(Image.open(spec_path.parent / "crop.png").convert("L")).astype(float)
h, w = lum.shape

# resample the closed polygon every 2 px
closed = np.vstack([traced, traced[:1]])
seg = np.hypot(*np.diff(closed, axis=0).T)
dist = np.concatenate([[0], np.cumsum(seg)])
at = np.arange(0, dist[-1], 2.0)
pts = np.column_stack([np.interp(at, dist, closed[:, 0]), np.interp(at, dist, closed[:, 1])])

# inward normals: the polygon's signed area gives its winding
area = 0.5 * np.sum(closed[:-1, 0] * closed[1:, 1] - closed[1:, 0] * closed[:-1, 1])
tangent = np.roll(pts, -3, axis=0) - np.roll(pts, 3, axis=0)
tangent /= np.maximum(np.hypot(*tangent.T), 1e-9)[:, None]
inward = np.column_stack([-tangent[:, 1], tangent[:, 0]]) * (1 if area > 0 else -1)

offsets = np.arange(-reach, reach + 1)
shift = np.zeros(len(pts))
found = np.zeros(len(pts), bool)
for i, (p, n) in enumerate(zip(pts, inward, strict=True)):
    if p[1] < ymin:
        continue
    xs = np.clip(np.rint(p[0] + n[0] * offsets).astype(int), 0, w - 1)
    ys = np.clip(np.rint(p[1] + n[1] * offsets).astype(int), 0, h - 1)
    profile = lum[ys, xs]
    outside = np.median(profile[:3])
    if outside < 150:  # against painted shadow the ink does not stand out: keep the trace
        continue
    drop = np.flatnonzero(profile < min(outside - 45, outside * 0.62))
    if len(drop):
        shift[i] = offsets[drop[0]] - 1.0  # one px outside the first ink pixel
        found[i] = True

# smooth along the contour; unfound samples borrow from their neighbours
smooth = shift.copy()
win = 7
for point in map(int, np.flatnonzero(pts[:, 1] >= ymin)):
    idx = np.arange(point - win, point + win + 1) % len(pts)
    near = idx[found[idx]]
    smooth[point] = np.median(shift[near]) if len(near) >= 3 else 0.0
snapped = pts + inward * smooth[:, None]

spec["outline_traced"] = traced.tolist()
spec["outline"] = [[round(float(x), 1), round(float(y), 1)] for x, y in snapped]
spec_path.write_text(json.dumps(spec))
moved = pts[:, 1] >= ymin
print(
    f"{len(pts)} samples, {int(moved.sum())} in range, {int(found.sum())} snapped, "
    f"median |shift| {np.median(np.abs(smooth[moved])):.1f} px, max {np.abs(smooth[moved]).max():.1f} px"
)
