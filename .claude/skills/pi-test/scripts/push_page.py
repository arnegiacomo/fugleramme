"""Push one saved panel page to the Inky through the frame's own driver wrapper.

Run on the Pi, in the checkout, with the frame stopped:

    uv run python push_page.py page.png

The page must be the panel's resolution. A mode "P" page in the frame's own palette
(what `render.dither.dither` returns, and what `frame.png` is) goes to the glass pixel
for pixel; anything else the driver re-dithers. It is pushed at rotation 0 whatever
the admin's rotation setting: a test page is laid out for the glass, not the frame.
"""

import sys

from PIL import Image

from fugleramme.panel import init_panel

panel = init_panel()
if panel is None:
    sys.exit("no panel")
page = Image.open(sys.argv[1])
if page.size != panel.resolution:
    sys.exit(f"page is {page.size}, panel {panel.driver} is {panel.resolution}")
print("pushing", page.mode, page.size, "to", panel.driver, panel.resolution, flush=True)
panel.push(page, rotation=0)
print("done")
