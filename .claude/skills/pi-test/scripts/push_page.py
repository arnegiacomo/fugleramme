"""Push one saved panel page to the Inky through the frame's own driver wrapper.

Run on the Pi, in the checkout, with the frame stopped:

    uv run python push_page.py page.png

The page is a PNG at the panel's resolution. A mode "P" page in the frame's own
palette (what `render.dither.dither` returns, and what `frame.png` is) goes to
the glass pixel for pixel; anything else the driver re-dithers.
"""

import sys

from PIL import Image

from fugleramme.panel import init_panel

panel = init_panel()
if panel is None:
    sys.exit("no panel")
page = Image.open(sys.argv[1])
print("pushing", page.mode, page.size, "to", panel.driver, panel.resolution, flush=True)
panel.push(page, rotation=0)
print("done")
