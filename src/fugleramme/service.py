"""Frame service main loop.

One collage, two outputs (issue #1 "render once, fan out"): the web/kiosk view
serves it full-color on request; the Inky panel gets the same collage dithered
to 6 colors. The loop re-renders the panel image only when the set of species
seen in the last 24h changes - a natural debounce for the slow e-ink refresh.
The web view is always rendered fresh per request, so it needs no loop.

Panel-absent is not a special case: init_panel returns None and we skip the
push, the same path as the Mac preview.
"""

from __future__ import annotations

import logging
import random
import threading
import time

from .collage import gather_entries, render_collage
from .config import Config
from .db import Database
from .panel import init_panel
from .render import dither
from .server import serve

log = logging.getLogger(__name__)

_POLL_SECONDS = 30
SHOW_NAMES = False  # will become an admin toggle


def run(config: Config) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    panel = init_panel()

    server_thread = threading.Thread(
        target=serve,
        args=(config.db_path, config.images_dir, config.host, config.port),
        kwargs={"show_names": SHOW_NAMES},
        daemon=True,
    )
    server_thread.start()
    log.info("Serving kiosk on http://%s:%s", config.host, config.port)

    db = Database(config.db_path)
    last_key: tuple | None = None
    while True:
        species = db.species_last_24h()
        key = tuple(species)
        if key != last_key:
            rng = random.Random(hash(tuple(name for name, _ in species)))
            entries = gather_entries(db, config.images_dir, rng)
            collage = render_collage(entries, config.resolution, SHOW_NAMES, rng)
            panel_image = dither(collage)
            panel_image.save(config.output_path)
            log.info("Rendered panel collage: %d species", len(species))
            if panel is not None:
                panel.push(panel_image)
            last_key = key
        time.sleep(_POLL_SECONDS)
