"""A gridded close-up of the scan with the traced outline drawn on it:
overlay.py spec.json x0,y0,x1,y1 name [step]"""

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

spec_path = Path(sys.argv[1])
spec, out = json.loads(spec_path.read_text()), spec_path.parent
x0, y0, x1, y1 = (int(v) for v in sys.argv[2].split(","))
step = int(sys.argv[4]) if len(sys.argv) > 4 else 10
z = 1500 / (x1 - x0)
view = Image.open(out / "crop.png").convert("RGB").crop((x0, y0, x1, y1))
view = view.resize((1500, round((y1 - y0) * z)), Image.Resampling.LANCZOS)
draw = ImageDraw.Draw(view)
for gx in range((x0 // step + 1) * step, x1, step):
    major = gx % (step * 5) == 0
    draw.line(
        [((gx - x0) * z, 0), ((gx - x0) * z, view.height)],
        fill=(0, 120, 255) if major else (150, 200, 255),
    )
    if major:
        draw.text(((gx - x0) * z + 2, 2), str(gx), fill=(0, 0, 200))
for gy in range((y0 // step + 1) * step, y1, step):
    major = gy % (step * 5) == 0
    draw.line(
        [(0, (gy - y0) * z), (view.width, (gy - y0) * z)],
        fill=(0, 120, 255) if major else (150, 200, 255),
    )
    if major:
        draw.text((2, (gy - y0) * z + 2), str(gy), fill=(0, 0, 200))
pts = [((x - x0) * z, (y - y0) * z) for x, y in spec["outline"]]
draw.line(pts + pts[:1], fill=(255, 0, 255), width=2)
for p in pts:
    draw.ellipse((p[0] - 3, p[1] - 3, p[0] + 3, p[1] + 3), outline=(255, 0, 255))
view.save(out / f"over-{sys.argv[3]}.jpg", quality=90)
print(view.size)
