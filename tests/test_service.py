"""The render loop's one hard promise: whatever happens to the detector, the
page already on the glass stays there. A frame that blanks itself while
BirdNET-Go restarts is worse than one that is a few minutes stale."""

from __future__ import annotations

import logging
import re
import signal
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from fugleramme import api, modes, service
from fugleramme.config import Config
from fugleramme.settings import Settings, SettingsStore
from fugleramme.status import Status


class _Stop(Exception):
    """Breaks the otherwise endless loop from inside its own sleep."""


@pytest.fixture
def images(tmp_path):
    style = tmp_path / "images" / "classic"
    (style / "birds").mkdir(parents=True)
    for key in ("turdus-merula", "parus-major"):
        Image.new("RGBA", (120, 90), (40, 40, 40, 255)).save(style / "birds" / f"{key}.png")
    (style / "perches").mkdir()
    Image.new("RGBA", (80, 60), (20, 20, 20, 255)).save(style / "perches" / "twig.png")
    return tmp_path / "images"


def test_the_loop_holds_its_last_page_when_the_detector_goes_away(
    tmp_path, images, detector, monkeypatch, caplog
):
    url, httpd = detector(count=40, seed=0)
    monkeypatch.setattr(api, "_TTL", 0)  # no cached answers to hide the outage behind
    monkeypatch.setattr(api, "_HOLD", 0)
    config = Config(
        images_dir=images,
        detector_url=url,
        output_path=tmp_path / "frame.png",
        host="127.0.0.1",
        port=0,
        config_path=tmp_path / "settings.json",
    )
    ticks: list[bytes] = []

    def sleep(_seconds):
        ticks.append(config.output_path.read_bytes())
        if len(ticks) == 1:
            httpd.shutdown()  # BirdNET-Go goes down between two ticks
            httpd.server_close()
        if len(ticks) == 3:
            raise _Stop

    with (
        patch.object(service.updates, "available", return_value=None),
        patch.object(service.modes, "render", side_effect=modes.render) as render,
        patch.object(service.time, "sleep", sleep),
        pytest.raises(_Stop),
    ):
        service.run(config)

    assert "Detector unavailable" in caplog.text  # the blind ticks did see the outage
    assert render.call_count == 1  # and did not draw an empty page over it
    assert len(set(ticks)) == 1  # and the file they would have written it to is untouched
    assert np.asarray(Image.open(config.output_path)).std() > 0.5  # birds, not bare paper


def test_a_render_error_holds_the_page_instead_of_ending_the_service(
    tmp_path, images, detector, monkeypatch, caplog
):
    """An unreadable plate raises from deep in the render. Ending the process would
    have systemd restart it into the same file every few seconds."""
    url, _httpd = detector(count=40, seed=0)
    monkeypatch.setattr(api, "_TTL", 0)
    monkeypatch.setattr(api, "_HOLD", 0)
    config = Config(
        images_dir=images,
        detector_url=url,
        output_path=tmp_path / "frame.png",
        host="127.0.0.1",
        port=0,
        config_path=tmp_path / "settings.json",
    )
    caplog.set_level(logging.INFO, logger="fugleramme.service")
    # Renders 2-4 fail, 1 and 5 are real. The rotation turns once, after the first page,
    # to give render 2 a reason; renders 3 and 4 happen only because a failed render
    # leaves last_key stale, which is the behaviour under test.
    failing = {2: OSError("truncated plate"), 3: OSError("truncated plate"), 4: OSError("no font")}
    real_render = modes.render  # patched below, so the wrapper must not look it up again
    renders = 0
    ticks = 0
    on_glass: list[bytes] = []

    def render(ctx):
        nonlocal renders
        renders += 1
        if renders in failing:
            raise failing[renders]
        return real_render(ctx)

    def sleep(_seconds):
        nonlocal ticks
        ticks += 1
        on_glass.append(config.output_path.read_bytes())
        if ticks == 5:
            raise _Stop
        if ticks == 1:
            # The detector's address rides in as the default, as the loop's own store has it:
            # saved without it, the file would send the loop to the built-in address.
            SettingsStore(config.config_path, Settings(detector_url=url)).update(rotation=90)

    with (
        patch.object(service.updates, "available", return_value=None),
        patch.object(service.modes, "render", render),
        patch.object(service.time, "sleep", sleep),
        pytest.raises(_Stop),
    ):
        service.run(config)

    assert renders == 5  # every failing tick tried again, and the service never ended
    assert len(set(on_glass[:4])) == 1  # the first page stayed through all three failures
    assert on_glass[4] != on_glass[0]  # and the fifth tick drew a new one
    messages = [r.getMessage() for r in caplog.records]
    failed = [r for r in caplog.records if r.getMessage().startswith("Render failed")]
    # Named by its cause, once per cause: the repeat is quiet, the new one is not.
    assert len(failed) == 2
    head = r"Render failed for collage at \d+x\d+, holding the current page \("
    assert re.match(head, failed[0].getMessage())  # which mode and how big, for any error
    assert failed[0].getMessage().endswith("(OSError: truncated plate)")
    assert failed[1].getMessage().endswith("(OSError: no font)")
    assert "Rendering recovered" in messages


def test_the_configured_detector_is_rebuilt_only_when_the_settings_name_another(tmp_path, detector):
    """service.detector builds the ApiSource once, so a saved URL that did not
    reach the running instance would look like it worked and do nothing."""
    first, _one = detector(count=4, seed=0)
    second, _two = detector(count=4, seed=1)
    store = SettingsStore(tmp_path / "s.json", Settings(detector_url=first))
    source = api.Configured(store)

    built = source.source
    assert built.base_url == first
    assert source.source is built  # nothing changed, so nothing was rebuilt

    store.update(lookback_hours=12)
    assert source.source is built  # a setting the connection does not touch

    store.update(detector_url=second)
    assert source.source.base_url == second

    store.update(detector_password="hunter2")
    assert source.source is not built


def test_the_frame_reads_through_the_wrapper_not_a_captured_source(tmp_path, detector):
    """Everything holds the wrapper, so a swap reaches the loop, the server and
    the names at once - including the Source calls it never declares itself."""
    first, _one = detector(rows=[])
    second, _two = detector(count=4, seed=0)
    store = SettingsStore(tmp_path / "s.json", Settings(detector_url=first))
    source = api.Configured(store)

    assert source.species_since(0) == []  # answered, and genuinely no birds
    store.update(detector_url=second)
    assert source.species_since(0)


def test_the_loop_names_the_species_it_has_no_artwork_for(
    tmp_path, images, detector, monkeypatch, caplog
):
    """The admin marks a missing plate only while you are looking at it; the
    journal keeps it, one line per change rather than per poll."""
    caplog.set_level(logging.INFO, logger="fugleramme.service")
    url, _httpd = detector(count=40, seed=0)
    monkeypatch.setattr(api, "_TTL", 0)
    monkeypatch.setattr(api, "_HOLD", 0)
    config = Config(
        images_dir=images,
        detector_url=url,
        output_path=tmp_path / "frame.png",
        host="127.0.0.1",
        port=0,
        config_path=tmp_path / "settings.json",
    )
    ticks = 0

    def sleep(_seconds):
        nonlocal ticks
        ticks += 1
        if ticks == 3:
            raise _Stop

    with (
        patch.object(service.updates, "available", return_value=None),
        patch.object(service.time, "sleep", sleep),
        pytest.raises(_Stop),
    ):
        service.run(config)

    lines = [m for r in caplog.records if (m := r.getMessage()).startswith("No artwork")]
    assert len(lines) == 1  # three ticks, one unchanged list
    assert "Pica pica" in lines[0]  # counted by the window, undrawable by the style
    assert "Turdus merula" not in lines[0]


def test_the_refresh_floor_paces_the_birds_but_never_a_saved_setting(
    tmp_path, images, detector, monkeypatch
):
    """The panel holds its page until the floor lets go (#64), but a saved setting
    is not birds and must reach the glass on the next tick regardless."""
    url, _httpd = detector(count=4, seed=0)
    config = Config(
        images_dir=images,
        detector_url=url,
        output_path=tmp_path / "frame.png",
        host="127.0.0.1",
        port=0,
        config_path=tmp_path / "settings.json",
    )
    store = SettingsStore(config.config_path, Settings(detector_url=url))
    store.update(refresh_minutes=10, show_names=True)
    # The page's species, tick by tick: two birds trading places at the cutoff.
    pages = iter([("a",), ("b",), ("b",), ("b",)])
    collage = modes.MODES["collage"]
    monkeypatch.setitem(modes.MODES, "collage", replace(collage, key=lambda _ctx: next(pages)))
    ticks = 0

    def sleep(_seconds):
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            store.update(show_names=False)
        if ticks == 3:
            raise _Stop

    with (
        patch.object(service.updates, "available", return_value=None),
        patch.object(service.modes, "render", side_effect=modes.render) as render,
        patch.object(service.time, "sleep", sleep),
        pytest.raises(_Stop),
    ):
        service.run(config)

    # The first page, then a held trade, then the saved setting.
    assert render.call_count == 2


def test_signing_in_does_not_let_the_birds_past_the_refresh_floor(
    tmp_path, images, detector, monkeypatch
):
    """The session secret rides along in Settings and rotates on every sign-in and
    sign-out, which would otherwise read as a saved setting and repaint the panel."""
    url, _httpd = detector(count=4, seed=0)
    config = Config(
        images_dir=images,
        detector_url=url,
        output_path=tmp_path / "frame.png",
        host="127.0.0.1",
        port=0,
        config_path=tmp_path / "settings.json",
    )
    store = SettingsStore(config.config_path, Settings(detector_url=url))
    store.update(refresh_minutes=10)
    pages = iter([("a",), ("b",), ("b",), ("b",)])
    collage = modes.MODES["collage"]
    monkeypatch.setitem(modes.MODES, "collage", replace(collage, key=lambda _ctx: next(pages)))
    ticks = 0

    def sleep(_seconds):
        nonlocal ticks
        ticks += 1
        if ticks == 2:
            store.update(session_secret="a-new-session")
        if ticks == 3:
            raise _Stop

    with (
        patch.object(service.updates, "available", return_value=None),
        patch.object(service.modes, "render", side_effect=modes.render) as render,
        patch.object(service.time, "sleep", sleep),
        pytest.raises(_Stop),
    ):
        service.run(config)

    assert render.call_count == 1  # the first page, and the trade still held


def test_no_floor_is_the_shipped_default(tmp_path):
    """A frame that updates into this keeps the behaviour it had."""
    assert SettingsStore(tmp_path / "s.json").get().refresh_minutes == 0
    assert service._due(0, service.time.monotonic())


@pytest.mark.parametrize(
    ("inky", "external_panel_size", "hung", "renders"),
    [
        (None, "", (1200, 1600), 1),  # nothing picked and no Inky: the 13.3"
        (None, "7.3", (480, 800), 1),
        ((800, 480), "", (480, 800), 1),  # nothing picked: the Inky's page, as before the pick
        ((800, 480), "13.3", (1200, 1600), 2),  # a page of its own, the Inky keeping its own
    ],
)
def test_with_the_e6_page_on_the_loop_hands_over_a_page_at_the_external_panel_s_size(
    tmp_path, images, detector, inky, external_panel_size, hung, renders
):
    """The external e-ink panel takes its own size and edges, and the dithered page
    is left where /frame.e6 packs it from. This frame's Inky still gets its own."""
    url, _httpd = detector(count=40, seed=0)
    config = Config(
        images_dir=images,
        detector_url=url,
        output_path=tmp_path / "frame.png",
        host="127.0.0.1",
        port=0,
        config_path=tmp_path / "settings.json",
    )
    store = SettingsStore(config.config_path, Settings(detector_url=url))
    store.update(
        external_panel=True,
        external_panel_size=external_panel_size,
        rotation=90,
        margin_lock=False,
        margin_top=20,
    )
    statuses: list[Status] = []

    def status() -> Status:
        statuses.append(Status())
        return statuses[-1]

    def sleep(_seconds):
        raise _Stop

    pushed: list[tuple[int, int]] = []
    panel = (
        SimpleNamespace(
            resolution=inky, driver="", push=lambda image, _rotation: pushed.append(image.size)
        )
        if inky
        else None
    )

    with (
        patch.object(service.updates, "available", return_value=None),
        patch.object(service, "init_panel", return_value=panel),
        patch.object(service.buttons, "watch"),
        patch.object(service, "Status", status),
        patch.object(service.modes, "render", side_effect=modes.render) as render,
        patch.object(service.time, "sleep", sleep),
        pytest.raises(_Stop),
    ):
        service.run(config)

    assert render.call_count == renders
    ctx = render.call_args.args[0]
    assert 0.2 in ctx.margin and len(set(ctx.margin)) == 2  # the one edge set on its own
    image, rotation = statuses[0].frame
    assert (image.mode, image.size, rotation) == ("P", hung, 90)
    assert pushed == ([(480, 800)] if inky else [])


@pytest.mark.parametrize("signal_code", [signal.SIGINT, signal.SIGTERM])
def test_signal_runs_the_shutdown_handler(tmp_path, images, detector, signal_code):
    """Signal is registered and triggers the shutdown routine."""
    url, _ = detector(count=40, seed=0)
    config = Config(
        images_dir=images,
        detector_url=url,
        output_path=tmp_path / "frame.png",
        host="127.0.0.1",
        port=0,
        config_path=tmp_path / "settings.json",
    )

    class MockServer:
        shutdown_calls = 0
        server_close_calls = 0

        def shutdown(self):
            self.shutdown_calls += 1

        def server_close(self):
            self.server_close_calls += 1

    mock_server = MockServer()

    def sleep(_seconds):
        signal.raise_signal(signal_code)

    with (
        patch.object(service.updates, "available", return_value=None),
        patch.object(service.time, "sleep", sleep),
        patch.object(service, "serve", return_value=mock_server),
        pytest.raises(SystemExit, match="0"),
    ):
        service.run(config)

    assert mock_server.shutdown_calls == 1
    assert mock_server.server_close_calls == 1
