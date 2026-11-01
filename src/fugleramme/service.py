"""Frame service main loop.

One page, two outputs (issue #1 "render once, fan out"): the web/kiosk view
serves it full-color on request; the Inky panel gets the same page dithered to 6
colors. The loop re-renders the panel image only when the mode's own key changes
- see modes.py - a natural debounce for the slow e-ink refresh. The web view
renders fresh per request, at its own size - the panel's shape while locked to it.

Panel-absent is not a special case: init_panel returns None and we skip the
push, the same path as the preview.
"""

from __future__ import annotations

import faulthandler
import logging
import os
import signal
import threading
import time
from dataclasses import replace

from . import __version__, buttons, languages, modes, taxa, updates, wifi
from .api import Configured
from .config import Config
from .languages import namer
from .panel import Panel, external_resolution, init_panel, resolution_of
from .render.dither import dither, monochrome
from .render.fonts import FONTS, FONTS_DIR
from .render.setup import setup_page
from .settings import Settings, SettingsStore, from_env
from .source import Unavailable
from .status import Frame, Status
from .web.server import serve

log = logging.getLogger(__name__)

_POLL_SECONDS = 5  # one query per tick; re-renders only on change, so e-ink stays the bottleneck


def detector(config: Config) -> tuple[SettingsStore, Configured]:
    """The settings store and the detector they name. settings.json wins over
    both of the seeds below whenever it carries the key itself."""
    defaults = from_env()
    if config.detector_url:
        defaults = replace(defaults, detector_url=config.detector_url)  # --detector beats the env
    store = SettingsStore(config.config_path, defaults)
    source = Configured(store)
    languages.use(source)
    return store, source


def _due(minutes: int, last: float | None) -> bool:
    """Whether the birds may change the page again yet. 0 minutes is no floor."""
    return last is None or time.monotonic() - last >= minutes * 60


def _paced(settings: Settings) -> Settings:
    """Settings as the refresh floor sees them: signing in or out rotates the
    session secret, which changes nothing on the page and must not skip the floor."""
    return replace(settings, session_secret="")


def _update(status: Status, auto: bool) -> bool:
    """Refresh the release check and install if asked. True once the tag is checked out."""
    status.update_available = updates.available()
    if updates.in_container():
        return False  # the release check is still worth having; the install is the host's
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


def _wifi_setup(
    panel: Panel | None, port: int, store: SettingsStore, status: Status
) -> wifi.Setup | None:
    """The Wi-Fi setup's thread, on the Pi's own service with an Inky on it alone: the setup
    screen is the panel's, and only that service may touch the network, as with the reboot."""
    if panel is None or not updates.can_reboot():
        return None

    def publish(state: wifi.State) -> None:
        status.wifi = state

    setup = wifi.Setup(
        wifi.Nmcli(port),
        enabled=lambda: store.get().wifi_setup,
        password=lambda: store.get().hotspot_password,
        publish=publish,
    )
    threading.Thread(target=setup.run, daemon=True).start()
    return setup


def _setup_key(state: wifi.State, settings: Settings, size: tuple[int, int]) -> tuple:
    """What the setup screen is a function of."""
    margins = settings.margins(True)
    return ("wifi", state.name, state.password, state.error, size, margins, settings.rotation)


def _setup_screen(state: wifi.State, settings: Settings, size: tuple[int, int]) -> Frame:
    """The setup screen for the panel."""
    top, right, bottom, left = settings.margins(True)
    page = setup_page(
        size,
        (top / 100, right / 100, bottom / 100, left / 100),
        state.name,
        state.password,
        f"http://{wifi.ADDRESS}",
        state.error,
        str(FONTS_DIR / FONTS["cormorant"][1]),  # the plates' engraved display italic
    )
    return monochrome(page), settings.rotation


def _push(panel: Panel, frame: Frame, status: Status) -> bool:
    """Whether the frame reached the glass. A failure is retried next tick from the same image
    rather than re-rendered."""
    try:
        panel.push(*frame)
    except Exception as exc:
        log.exception("Panel push failed")
        status.push_error = str(exc) or type(exc).__name__
        return False
    status.push_error = None
    return True


def _both_names(ctx: modes.Context, scientific: str) -> str:
    """`Common (Scientific)`, so a missing plate reads from the journal without a
    lookup. The admin's language, falling back to the label's English."""
    common = ctx.namer.parts(scientific)[0]
    if common == scientific:
        common = taxa.common_of(scientific)
    return f"{common} ({scientific})" if common else scientific


def _log_artless(ctx: modes.Context, last: list[str] | None) -> list[str]:
    """Name the window's species this style cannot draw, so a missing plate is
    readable from the journal. Logged on change, not on every poll."""
    artless = modes.artless(ctx)
    if artless == last:
        return artless
    if artless:
        named = ", ".join(_both_names(ctx, name) for name in artless)
        log.info("No artwork for %d species: %s", len(artless), named)
    else:
        log.info("Artwork found for every species in the window")
    return artless


def run(config: Config) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Ours only: PIL's debug level is a line per PNG chunk.
    logging.getLogger("fugleramme").setLevel(os.environ.get("FUGLERAMME_LOG_LEVEL", "INFO"))
    # `kill -USR1 <pid>` dumps every thread's stack to the journal - for when it wedges.
    faulthandler.register(signal.SIGUSR1, all_threads=True)

    log.info("Fugleramme v%s", __version__)

    panel = init_panel()
    store, source = detector(config)
    # Per-bird picks, unread since the pick went by day (#302). Remove after 2027-01-21.
    (config.config_path.parent / "artwork.json").unlink(missing_ok=True)
    status = Status()

    setup = _wifi_setup(panel, config.port, store, status)
    server = serve(
        source,
        config.images_dir,
        config.host,
        config.port,
        store,
        panel,
        status,
        setup,
    )

    def _shutdown(signum: int, frame: object) -> None:
        log.info("Signal %s, shutting down", signum)
        server.shutdown()
        server.server_close()
        raise SystemExit(0)

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)

    if panel is not None:  # the buttons are on the panel board
        threading.Thread(
            target=buttons.watch,
            args=(panel.driver, store, config.images_dir, setup.toggle if setup else None),
            daemon=True,
        ).start()
    log.info("Serving kiosk on http://%s:%s", config.host, config.port)
    log.info("Kiosk admin on http://%s:%s/admin", config.host, config.port)
    log.info("Reading detections from %s", source.base_url)

    last_key: tuple | None = None
    last_settings: Settings | None = None
    last_render: float | None = None
    last_artless: list[str] | None = None
    pending = None  # rendered but not yet on the glass; survives a failed push
    unreachable = False
    render_error: str | None = None
    while True:
        settings = store.get()
        if _update(status, settings.auto_update):
            return  # new code is checked out; systemd restarts us into it
        size = settings.oriented(resolution_of(panel, settings.external_panel_size))
        hotspot = status.wifi
        if panel is not None and hotspot is not None and hotspot.up:
            # The setup screen stands in for the birds while the hotspot is up, and they come
            # back the moment it goes, whatever the refresh floor says.
            key = _setup_key(hotspot, settings, size)
            if key != last_key:
                log.info("Showing the Wi-Fi setup screen at %dx%d", *size)
                pending = _setup_screen(hotspot, settings, size)
                last_key, last_render = key, None
            if pending is not None and _push(panel, pending, status):
                pending = None
            time.sleep(_POLL_SECONDS)
            continue
        # The external panel's own page, rendered apart only when this frame's Inky
        # is another size.
        outside = (
            settings.oriented(external_resolution(panel, settings.external_panel_size))
            if settings.external_panel
            else size
        )
        name_of = namer(
            settings.primary_language, settings.secondary_language, config.config_path.parent
        )
        ctx = modes.context(
            source,
            config.images_dir,
            settings,
            name_of,
            size,
            textured=False,
            panel=panel is not None or settings.external_panel,
        )
        try:
            last_artless = _log_artless(ctx, last_artless)
            key = (modes.state_key(ctx), outside, settings.rotation)
            # The floor paces the birds alone; a saved setting goes straight through.
            if key != last_key and (
                _paced(settings) != last_settings or _due(settings.refresh_minutes, last_render)
            ):
                panel_image = dither(modes.render(ctx))
                panel_image.save(config.output_path)
                log.info("Rendered %s for the panel at %dx%d", ctx.mode, *size)
                frame = (panel_image, settings.rotation)
                external = frame
                if outside != size:
                    external = (dither(modes.render(replace(ctx, resolution=outside))), frame[1])
                    log.info("Rendered %s for the external panel at %dx%d", ctx.mode, *outside)
                status.rendered(external)
                last_key, last_settings, last_render = key, _paced(settings), time.monotonic()
                pending = frame if panel is not None else None
            if unreachable:
                log.info("Detector reachable again")
                unreachable = False
            if render_error:
                log.info("Rendering recovered")
                render_error = None
        except Unavailable as exc:
            # last_key is left alone, so the page stays on the glass: a detector
            # slow to return after its own update must never blank the frame.
            if not unreachable:
                log.warning("Detector unavailable, holding the current page (%s)", exc)
                unreachable = True
        except Exception as exc:
            # A bad plate or font would otherwise end the process, and systemd would
            # restart it into the same error every 5s. Same hold as above, retried each
            # tick and logged again only when the cause changes.
            cause = f"{type(exc).__name__}: {exc}"
            if cause != render_error:
                log.exception(
                    "Render failed for %s at %dx%d, holding the current page (%s)",
                    ctx.mode,
                    *size,
                    cause,
                )
                render_error = cause
        if panel is not None and pending is not None and _push(panel, pending, status):
            pending = None
        time.sleep(_POLL_SECONDS)
