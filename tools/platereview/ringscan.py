"""Share of drawn soft-edge pixels (alpha 25-254) that are dark, per plate."""

import sys
from pathlib import Path

import numpy as np
from PIL import Image

for path in sys.argv[1:]:
    a = np.asarray(Image.open(path).convert("RGBA")).astype(int)
    edge = (a[..., 3] >= 25) & (a[..., 3] < 255)
    dark = a[..., :3][edge].max(1) < 200
    print(
        f"{Path(path).parent.parent.parent.parent.parent.name:14} {Path(path).name:36} {int(dark.sum()):5} dark of {int(edge.sum()):6}  {dark.mean():6.1%}"
    )
