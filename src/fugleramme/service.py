"""Frame service main loop.

One page, two outputs (issue #1 "render once, fan out"): the web/kiosk view
serves it full-color on request; the Inky panel gets the same page dithered to 6
colors. The loop re-renders the panel image only when the mode's own key changes
- see modes.py - a natural debounce for the slow e-ink refresh. The web view
renders fresh per request, at the panel's shape and its own pixel count.

Panel-absent is not a special case: init_panel returns None and we skip the
push, the same path as the preview.
"""

from __future__ import annotations

import faulthandler
import logging
import signal
import threading
import time

from . import __version__, buttons, modes, updates
from .config import BIRDNET_PORT, Config
from .db import Database
from .languages import namer
from .panel import init_panel, resolution_of
from .picks import FILENAME as PICKS_FILE, Picks
from .render.dither import dither
from .settings import SettingsStore
from .status import Status
from .web.server import serve

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

    def progress(phase: str, percent: int | None) -> None:
        status.update_phase, status.update_percent = phase, percent

    try:
        updates.apply(tag, progress)
        log.info("Updated to %s, exiting for systemd to restart", tag)
        return True
    except Exception as exc:
        log.exception("Update to %s failed", tag)
        status.update_error = str(exc)
        status.updating = False
        status.update_phase = status.update_percent = None
        return False


def run(config: Config) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # `kill -USR1 <pid>` dumps every thread's stack to the journal - for when it wedges.
    faulthandler.register(signal.SIGUSR1, all_threads=True)

    log.info("Fugleramme v%s", __version__)

    panel = init_panel()
    store = SettingsStore(config.config_path)
    picks = Picks(config.config_path.parent / PICKS_FILE)
    status = Status()

    server_thread = threading.Thread(
        target=serve,
        args=(
            config.db_path,
            config.images_dir,
            config.host,
            config.port,
            store,
            picks,
            panel,
            status,
        ),
        daemon=True,
    )
    server_thread.start()
    if panel is not None:  # the buttons are on the panel board
        threading.Thread(
            target=buttons.watch,
            args=(panel.driver, store, config.images_dir),
            daemon=True,
        ).start()
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
        size = settings.oriented(resolution_of(panel))
        name_of = namer(
            settings.primary_language, settings.secondary_language, config.config_path.parent
        )
        ctx = modes.context(
            db,
            config.images_dir,
            picks,
            settings,
            name_of,
            size,
            textured=False,
        )
        key = (modes.state_key(ctx), settings.rotation)
        if key != last_key:
            if modes.mode_of(ctx.mode).windowed:
                # The loop owns the window, so it is the only caller that may forget
                # a departed bird's artwork - the kiosk may be previewing another one.
                picks.retain(name for name, _ in db.species_since(settings.lookback_hours))
            panel_image = dither(modes.render(ctx))
            panel_image.save(config.output_path)
            log.info("Rendered %s page at %dx%d", ctx.mode, *size)
            status.rendered()
            last_key = key
            pending = (panel_image, settings.rotation) if panel is not None else None
        if panel is not None and pending is not None:
            try:
                panel.push(*pending)
                pending = None
                status.push_error = None
            except Exception as exc:
                # Retry next tick from the same image rather than re-rendering.
                log.exception("Panel push failed")
                status.push_error = str(exc) or type(exc).__name__
        time.sleep(_POLL_SECONDS)
