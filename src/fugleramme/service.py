"""Frame service main loop.

Watches SQLite for the latest detection, re-renders frame.png on change, pushes
to the Inky panel if one is present, and serves the frame + dashboard over HTTP.
Panel-absent is not a special case: init_panel returns None and we simply skip
the push - the same path as --preview.
"""

from __future__ import annotations

import logging
import threading
import time

from .config import Config
from .db import Database
from .panel import init_panel
from .render import render_frame
from .server import serve

log = logging.getLogger(__name__)

_POLL_SECONDS = 5


def run(config: Config) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    panel = init_panel()

    server_thread = threading.Thread(
        target=serve,
        args=(config.db_path, config.output_path, config.host, config.port),
        daemon=True,
    )
    server_thread.start()
    log.info("Serving on http://%s:%s", config.host, config.port)

    db = Database(config.db_path)
    last_id: int | None = None
    while True:
        detection = db.latest()
        current_id = detection.id if detection else None
        if current_id != last_id:
            image = render_frame(
                detection, config.images_dir, config.resolution, config.output_path
            )
            name = detection.scientific_name if detection else "(empty)"
            log.info("Rendered frame for %s", name)
            if panel is not None:
                panel.push(image)
            last_id = current_id
        time.sleep(_POLL_SECONDS)
