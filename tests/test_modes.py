"""Mode invariants. The keys matter more than the pixels: a key that moves on
every detection would spend the day refreshing e-ink, and a key that never moves
would freeze the frame."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

import numpy as np
import pytest
from PIL import Image, features

from fugleramme import fake, modes
from fugleramme.api import ApiSource
from fugleramme.languages import NONE, STATION, Namer, namer, numeric
from fugleramme.names import normalize
from fugleramme.picks import Picks
from fugleramme.render.collage import KEY_LIMIT, NO_LIMIT
from fugleramme.render.page import NEW
from fugleramme.render.paper import PANEL_PAPER
from fugleramme.render.plate import effective_margin
from fugleramme.settings import MARGIN_CEILING, Settings

NOW = datetime.now().astimezone()
BLACKBIRD, TIT = "Turdus merula", "Parus major"
ROBIN = "Erithacus rubecula"


def _row(id_: int, name: str, ago_hours: float) -> fake.Detection:
    return fake.Detection(id_, NOW - timedelta(hours=ago_hours), name, 0.9, False)


def _heard(source: ApiSource, rows: list, row: fake.Detection) -> None:
    """A new detection reaches a running fake, and the source is asked again
    rather than answering from its few seconds of memory."""
    rows.insert(0, row)
    source._cache.clear()


@pytest.fixture
def images(tmp_path):
    """Two species with artwork, in a style of their own."""
    style = tmp_path / "classic"
    (style / "birds").mkdir(parents=True)
    for key in ("turdus-merula", "parus-major"):
        Image.new("RGBA", (120, 90), (40, 40, 40, 255)).save(style / "birds" / f"{key}.png")
    (style / "perches").mkdir()
    Image.new("RGBA", (80, 60), (20, 20, 20, 255)).save(style / "perches" / "twig.png")
    return tmp_path


def _draw(images, name: str) -> None:
    """Give a species a plate, so it can hold a place on the page."""
    Image.new("RGBA", (120, 90), (40, 40, 40, 255)).save(
        images / "classic" / "birds" / f"{normalize(name)}.png"
    )


def _ctx(source, images, tmp_path, mode, panel=False, **overrides):
    settings = Settings(mode=mode, **overrides)
    return modes.context(
        source,
        images,
        Picks(tmp_path / "artwork.json"),
        settings,
        namer("sci", "", tmp_path),
        (400, 300),
        textured=False,
        panel=panel,
    )


def test_every_mode_is_offered_and_the_default_is_the_collage():
    assert modes.DEFAULT_MODE == "collage"
    assert list(modes.MODES) == ["collage", "latest", "arrival"]
    assert [k for k, m in modes.MODES.items() if m.windowed] == ["collage"]
    assert modes.mode_of("gone") is modes.MODES["collage"]


@pytest.mark.parametrize("mode", list(modes.MODES))
def test_every_mode_draws_something(tmp_path, images, source, mode):
    detections = source(rows=[_row(2, TIT, 2), _row(1, BLACKBIRD, 1)])
    page = modes.render(_ctx(detections, images, tmp_path, mode))
    assert np.asarray(page).std() > 1


@pytest.mark.parametrize("mode", list(modes.MODES))
def test_an_empty_record_falls_back_to_the_perch(tmp_path, images, source, mode):
    page = modes.render(_ctx(source(rows=[]), images, tmp_path, mode))
    assert np.asarray(page).std() > 1  # the branch, not bare paper


def test_the_latest_bird_holds_the_page_while_the_same_bird_calls(tmp_path, images, detector):
    rows = [_row(1, BLACKBIRD, 2)]
    url, _httpd = detector(rows=rows)
    detections = ApiSource(url)
    before = modes.state_key(_ctx(detections, images, tmp_path, "latest"))

    _heard(detections, rows, _row(2, BLACKBIRD, 1))
    assert modes.state_key(_ctx(detections, images, tmp_path, "latest")) == before


def test_the_latest_bird_changes_the_page_when_the_species_changes(tmp_path, images, detector):
    rows = [_row(1, BLACKBIRD, 2)]
    url, _httpd = detector(rows=rows)
    detections = ApiSource(url)
    before = modes.state_key(_ctx(detections, images, tmp_path, "latest"))

    _heard(detections, rows, _row(2, TIT, 1))
    assert modes.state_key(_ctx(detections, images, tmp_path, "latest")) != before


def test_the_latest_bird_skips_a_species_it_cannot_draw(tmp_path, images, source):
    (images / "classic" / "birds" / "parus-major.png").unlink()
    detections = source(rows=[_row(2, TIT, 1), _row(1, BLACKBIRD, 2)])
    assert modes.state_key(_ctx(detections, images, tmp_path, "latest"))[-1][0] == BLACKBIRD


def test_the_collage_holds_the_page_when_a_bird_already_on_it_calls_again(
    tmp_path, images, detector
):
    """species_since ranks by count, so re-hearing a bird can overtake another
    and reorder the window. The set is the same, so the page must be too."""
    rows = [_row(3, BLACKBIRD, 1), _row(2, TIT, 2), _row(1, TIT, 2)]
    url, _httpd = detector(rows=rows)
    detections = ApiSource(url)
    before = modes.state_key(_ctx(detections, images, tmp_path, "collage"))

    for id_ in (4, 5):
        _heard(detections, rows, _row(id_, BLACKBIRD, 0))

    assert detections.species_since()[0][0] == BLACKBIRD  # the ranking did flip
    assert modes.state_key(_ctx(detections, images, tmp_path, "collage")) == before


def test_a_limit_keeps_the_most_heard_and_the_ranking_takes_the_other_end(tmp_path, images, source):
    detections = source(rows=[_row(3, TIT, 1), _row(2, BLACKBIRD, 1), _row(1, BLACKBIRD, 2)])
    for ranking, expected in (("heard", BLACKBIRD), ("rarest", TIT)):
        ctx = _ctx(detections, images, tmp_path, "collage", species_limit=1, ranking=ranking)
        assert modes._selected(ctx) == [expected]


def test_a_bird_crossing_the_limit_repaints_although_the_window_never_moved(
    tmp_path, images, detector
):
    """Under a limit two birds can trade places across the page while the set of
    species heard sits perfectly still - and the picture changes."""
    rows = [_row(3, TIT, 1), _row(2, BLACKBIRD, 1), _row(1, BLACKBIRD, 2)]
    url, _httpd = detector(rows=rows)
    detections = ApiSource(url)

    def ctx():
        return _ctx(detections, images, tmp_path, "collage", species_limit=1)

    window = {name for name, _ in detections.species_since()}
    before = modes.state_key(ctx())
    assert modes._selected(ctx()) == [BLACKBIRD]

    for id_ in range(4, 9):
        _heard(detections, rows, _row(id_, TIT, 0))

    assert {name for name, _ in detections.species_since()} == window  # same birds heard
    assert modes._selected(ctx()) == [TIT]  # different bird on the page
    assert modes.state_key(ctx()) != before  # so the panel is told about it


def test_the_admin_lists_a_bird_with_no_plate_but_not_one_the_limit_left_out(
    tmp_path, images, source
):
    (images / "classic" / "birds" / "parus-major.png").unlink()  # counted, cannot be drawn
    _draw(images, ROBIN)
    rows = [_row(4, TIT, 1), _row(3, ROBIN, 1), _row(2, BLACKBIRD, 1), _row(1, BLACKBIRD, 2)]
    detections = source(rows=rows)

    every = modes.subjects(_ctx(detections, images, tmp_path, "collage"))
    assert every == sorted([BLACKBIRD, ROBIN, TIT])

    # One place, and the blackbird is the most heard, so the robin loses it.
    limited = modes.subjects(_ctx(detections, images, tmp_path, "collage", species_limit=1))
    assert limited == sorted([BLACKBIRD, TIT])  # the tit for having no plate, not for losing


def test_the_newest_arrival_is_the_latest_first_ever(tmp_path, images, source):
    detections = source(rows=[_row(3, BLACKBIRD, 1), _row(2, TIT, 100), _row(1, BLACKBIRD, 200)])
    assert modes.state_key(_ctx(detections, images, tmp_path, "arrival"))[-1][0] == TIT


def test_only_the_collage_reads_the_lookback_window(tmp_path, images, source):
    detections = source(rows=[_row(2, BLACKBIRD, 1), _row(1, TIT, 400)])
    for mode, sensitive in (("collage", True), ("latest", False), ("arrival", False)):
        short = modes.state_key(_ctx(detections, images, tmp_path, mode, lookback_hours=24))
        long = modes.state_key(_ctx(detections, images, tmp_path, mode, lookback_hours=720))
        assert (short != long) is sensitive


@pytest.mark.parametrize("mode", ["latest", "arrival"])
def test_the_margin_reaches_the_plate_modes(tmp_path, images, source, mode):
    detections = source(rows=[_row(1, BLACKBIRD, 1)])
    tight = modes.render(_ctx(detections, images, tmp_path, mode, margin=0))
    wide = modes.render(_ctx(detections, images, tmp_path, mode, margin=MARGIN_CEILING))
    assert tight.tobytes() != wide.tobytes()


def test_a_margin_under_the_plates_own_does_not_change_its_key(tmp_path, images, source):
    detections = source(rows=[_row(1, BLACKBIRD, 1)])
    keys = [modes.state_key(_ctx(detections, images, tmp_path, "latest", margin=m)) for m in (0, 7)]
    assert keys[0] == keys[1]
    keys = [
        modes.state_key(_ctx(detections, images, tmp_path, "collage", margin=m)) for m in (0, 7)
    ]
    assert keys[0] != keys[1]


def test_a_plate_keeps_to_its_window_and_its_own_floor_on_each_edge(tmp_path, images, source):
    detections = source(rows=[_row(1, BLACKBIRD, 1)])
    edges = {"margin_lock": False, "margin_top": MARGIN_CEILING, "margin_right": 0}
    ctx = _ctx(detections, images, tmp_path, "latest", panel=True, margin=0, **edges)
    page = np.asarray(modes.render(ctx)).copy()
    x0, y0, x1, y1 = effective_margin(ctx.margin).window((400, 300))
    assert (x0, y0, x1, y1) == (24, 75, 376, 276)
    page[y0:y1, x0:x1] = PANEL_PAPER
    assert (page == PANEL_PAPER).all()


def test_the_key_carries_what_the_page_is_drawn_from(tmp_path, images, source):
    detections = source(rows=[_row(1, BLACKBIRD, 1)])
    base = _ctx(detections, images, tmp_path, "latest")
    for change in ({"show_names": False}, {"label_font": "bitter"}, {"label_size": "large"}):
        assert modes.state_key(
            _ctx(detections, images, tmp_path, "latest", **change)
        ) != modes.state_key(base)


def test_switching_mode_changes_the_page(tmp_path, images, source):
    detections = source(rows=[_row(2, TIT, 2), _row(1, BLACKBIRD, 1)])
    keys = {modes.state_key(_ctx(detections, images, tmp_path, m)) for m in modes.MODES}
    assert len(keys) == len(modes.MODES)


def test_a_render_is_cached_until_its_key_moves(tmp_path, images, source):
    detections = source(rows=[_row(1, BLACKBIRD, 1)])
    ctx = _ctx(detections, images, tmp_path, "latest")
    assert modes.png_bytes(ctx) is modes.png_bytes(ctx)
    assert modes.png_bytes(_ctx(detections, images, tmp_path, "arrival")) != modes.png_bytes(ctx)


def test_a_numbered_key_caps_the_page(tmp_path, images, source):
    detections = source(rows=[_row(1, BLACKBIRD, 1)])
    limit = lambda **s: _ctx(detections, images, tmp_path, "collage", **s).species_limit
    assert limit(name_key=True, species_limit=NO_LIMIT) == KEY_LIMIT
    assert limit(name_key=True, species_limit=12) == 12
    assert limit(name_key=True, show_names=False, species_limit=NO_LIMIT) == NO_LIMIT


def test_the_numbered_key_moves_only_the_collage(tmp_path, images, source):
    detections = source(rows=[_row(1, BLACKBIRD, 1)])
    for mode, moves in (("collage", True), ("latest", False)):
        keys = [
            modes.state_key(_ctx(detections, images, tmp_path, mode, name_key=on))
            for on in (False, True)
        ]
        assert (keys[0] != keys[1]) is moves


def test_the_spotlight_puts_the_latest_bird_on_a_limited_page(tmp_path, images, source):
    detections = source(rows=[_row(3, TIT, 0), _row(2, BLACKBIRD, 1), _row(1, BLACKBIRD, 2)])
    for on, expected in ((False, BLACKBIRD), (True, TIT)):
        ctx = _ctx(detections, images, tmp_path, "collage", species_limit=1, spotlight=on)
        assert modes._selected(ctx) == [expected]


def test_the_spotlight_moves_only_when_a_different_species_calls(tmp_path, images, detector):
    rows = [_row(2, TIT, 1), _row(1, BLACKBIRD, 2)]
    url, _httpd = detector(rows=rows)
    detections = ApiSource(url)

    def key():
        return modes.state_key(_ctx(detections, images, tmp_path, "collage", spotlight=True))

    before = key()
    _heard(detections, rows, _row(3, TIT, 0))
    assert key() == before
    _heard(detections, rows, _row(4, BLACKBIRD, 0))
    assert key() != before  # the same two birds, a different one in the middle


def test_a_bird_first_heard_today_is_marked_on_every_page(tmp_path, images, source):
    detections = source(rows=[_row(2, TIT, 1), _row(1, BLACKBIRD, 30)])
    for mode in modes.MODES:
        ctx = _ctx(detections, images, tmp_path, mode)
        label = modes._labeller(ctx)
        assert label(TIT).endswith(NEW) and not label(BLACKBIRD).endswith(NEW)
        assert modes.state_key(ctx) != modes.state_key(
            _ctx(detections, images, tmp_path, mode, show_names=False)
        )


def test_a_new_bird_with_no_artwork_leaves_the_page_alone(tmp_path, images, detector):
    rows = [_row(1, BLACKBIRD, 30)]
    url, _httpd = detector(rows=rows)
    detections = ApiSource(url)
    before = {m: modes.state_key(_ctx(detections, images, tmp_path, m)) for m in modes.MODES}

    _heard(detections, rows, _row(2, ROBIN, 0))

    for mode in modes.MODES:
        assert modes.state_key(_ctx(detections, images, tmp_path, mode)) == before[mode]


def test_no_mark_without_names(tmp_path, images, source):
    detections = source(rows=[_row(1, TIT, 1)])
    ctx = _ctx(detections, images, tmp_path, "collage", show_names=False)
    assert not modes._labeller(ctx)(TIT).endswith(NEW)


def test_a_name_no_face_here_can_draw_reads_as_the_scientific_one(
    tmp_path, images, source, monkeypatch, caplog
):
    """Arabic is unreadable without raqm. Decided in the label string, so the
    collage's cache key carries it."""
    check = features.check
    monkeypatch.setattr(features, "check", lambda name: name != "raqm" and check(name))
    monkeypatch.setattr(modes, "station_locale", lambda: "ar")
    modes._cannot_draw.cache_clear()
    arabic = fake.LABELS["ar"][TIT]
    ctx = replace(
        _ctx(source(rows=[]), images, tmp_path, "collage"),
        namer=Namer(STATION, NONE, {STATION: {TIT: arabic}}, (), "ar"),
    )

    assert modes._labeller(ctx)(TIT) == TIT
    assert ctx.namer.date(NOW, modes._drawable(ctx)) == numeric(NOW, clock=False)
    assert "Arabic can't be drawn here" in caplog.text

    monkeypatch.setattr(features, "check", lambda name: name == "raqm" or check(name))
    assert modes._labeller(ctx)(TIT) == arabic
