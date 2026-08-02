"""Frame service main loop.

One collage, two outputs (issue #1 "render once, fan out"): the web/kiosk view
serves it full-color on request; the Inky panel gets the same collage dithered
to 6 colors. The loop re-renders the panel image only when its inputs change -
the species in the lookback window, the rotation, the artwork sources - a
natural debounce for the slow e-ink refresh. The web view renders fresh per
request, at its own resolution setting.

Panel-absent is not a special case: init_panel returns None and we skip the
push, the same path as the Mac preview.
"""

from __future__ import annotations

import faulthandler
import logging
import signal
import threading
import time

from . import __version__, updates
from .collage import gather_entries, render_collage, render_rng
from .config import BIRDNET_PORT, FALLBACK_PANEL_RESOLUTION, Config
from .db import Database
from .names import resolve
from .panel import init_panel
from .render import dither
from .server import serve
from .settings import SettingsStore
from .status import Status

log = logging.getLogger(__name__)

_POLL_SECONDS = 5  # one query per tick; re-renders only on change, so e-ink stays the bottleneck


def _update(status: Status, auto: bool) -> bool:
    """Refresh the release check and install if asked. True once the tag is checked out."""
    status.update_available = updates.available()
    if auto and status.update_available and not status.update_error:
        status.update_requested = status.update_available
    if not status.update_requested:
        return False
    # updating first: the admin poll must never see a gap between the two flags.
    status.updating = True
    tag, status.update_requested = status.update_requested, None
    try:
        updates.apply(tag)
        log.info("Updated to %s, exiting for systemd to restart", tag)
        return True
    except Exception as exc:
        log.exception("Update to %s failed", tag)
        status.update_error = str(exc)
        status.updating = False
        return False


def run(config: Config) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # `kill -USR1 <pid>` dumps every thread's stack to the journal - for when it wedges.
    faulthandler.register(signal.SIGUSR1, all_threads=True)

    log.info("Fugleramme v%s", __version__)

    panel = init_panel()
    store = SettingsStore(config.config_path)
    status = Status()

    server_thread = threading.Thread(
        target=serve,
        args=(config.db_path, config.images_dir, config.host, config.port, store, panel, status),
        daemon=True,
    )
    server_thread.start()
    log.info("Serving kiosk on http://%s:%s", config.host, config.port)
    log.info("Kiosk admin on http://%s:%s/admin", config.host, config.port)
    log.info("BirdNET-Go UI on http://%s:%s", config.host, BIRDNET_PORT)

    db = Database(config.db_path)
    last_key: tuple | None = None
    pending = None  # rendered but not yet on the glass; survives a failed push
    while True:
        settings = store.get()
        if _update(status, settings.auto_update):
            return  # new code is checked out; systemd restarts us into it
        species = db.species_since(settings.lookback_hours)
        sources = resolve(settings.sources, config.images_dir)
        size = settings.oriented(panel.resolution if panel else FALLBACK_PANEL_RESOLUTION)
        key = (
            tuple(species), size, tuple(sources), settings.rotation,
            settings.show_names, settings.label_font, settings.label_size,
        )
        if key != last_key:
            rng = render_rng([name for name, _ in species])
            entries = gather_entries(db, config.images_dir, sources, rng, settings.lookback_hours)
            collage = render_collage(
                entries, size, settings.show_names, rng,
                textured=False, font_key=settings.label_font,
                label_size=settings.label_size,
            )
            panel_image = dither(collage)
            panel_image.save(config.output_path)
            log.info("Rendered panel collage: %d species at %dx%d", len(species), *size)
            status.rendered()
            last_key = key
            pending = (panel_image, settings.rotation) if panel is not None else None
        if pending is not None:
            try:
                panel.push(*pending)
                pending = None
                status.push_error = None
            except Exception as exc:
                # Retry next tick from the same image rather than re-rendering.
                log.exception("Panel push failed")
                status.push_error = str(exc) or type(exc).__name__
        time.sleep(_POLL_SECONDS)
