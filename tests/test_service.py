"""The render loop's one hard promise: whatever happens to the detector, the
page already on the glass stays there. A frame that blanks itself while
BirdNET-Go restarts is worse than one that is a few minutes stale."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image

from fugleramme import api, modes, service
from fugleramme.config import Config
from fugleramme.settings import Settings, SettingsStore


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
    assert np.asarray(Image.open(config.output_path)).std() > 1  # birds, not bare paper


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
