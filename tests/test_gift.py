"""Gift mode (#355): what the form checks, what wrapping changes, and that it all comes back."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from fugleramme import gift
from fugleramme.config import REPO_ROOT
from fugleramme.names import drawable_keys
from fugleramme.render.gift import overflow, splash
from fugleramme.render.page import Edges
from fugleramme.source import Species, Unavailable

TEMPLATE = (REPO_ROOT / "detector" / "config" / "config.yaml.template").read_text()
DRAWABLE = drawable_keys(REPO_ROOT / "assets" / "artwork", "classic")
TODAY = date(2026, 11, 5)


@pytest.mark.parametrize(
    ("day", "week"),
    [
        (date(2027, 1, 1), 1),
        (date(2027, 1, 31), 4),
        (date(2027, 5, 12), 18),
        (date(2027, 12, 31), 48),
    ],
)
def test_the_week_is_birdnets_48_week_year(day, week):
    assert gift.week(day) == week


@pytest.mark.parametrize(
    ("typed", "problem"),
    [
        ("2027-05-12", ""),
        ("20270512", "Use YYYY-MM-DD, like 2026-11-05."),  # date.fromisoformat would take it
        ("2027-02-30", "There is no such day."),
        ("2026-11-04", "That day has passed."),
        ("2026-11-05", ""),
    ],
)
def test_the_arrival_is_a_day_from_today_on(typed, problem):
    assert gift.arrival(typed, TODAY)[1] == problem


def test_wifi_is_checked_for_shape_only():
    assert gift.ssid_problem("x" * 32) == "" and gift.ssid_problem("x" * 33)
    assert gift.ssid_problem("æ" * 17)  # bytes, not characters
    assert gift.password_problem("") == ""  # open
    assert gift.password_problem("short").endswith("this is 5.")
    assert gift.password_problem("x" * 63) == "" and gift.password_problem("x" * 64)


def test_a_typed_position_needs_no_search():
    def refuse(_text):
        raise AssertionError("asked Photon")

    assert gift.find_place("39.96, -82.99", refuse) == gift.Place("39.96, -82.99", 39.96, -82.99)
    assert gift.find_place("95, 0", refuse) is None


def test_a_place_takes_photons_first_answer():
    answer = {
        "features": [
            {
                "geometry": {"coordinates": [-82.99, 39.96]},
                "properties": {"name": "Columbus", "state": "Ohio", "country": "United States"},
            }
        ]
    }
    place = gift.find_place("columbus", lambda _text: answer)
    assert place == gift.Place("Columbus, Ohio, United States", 39.96, -82.99)
    assert gift.find_place("nowhere", lambda _text: {"features": []}) is None


def test_favourites_lead_and_birds_without_a_plate_are_left_out():
    scores = [("Turdus migratorius", 0.9), ("Not avis", 0.8), ("Cardinalis cardinalis", 0.7)]
    birds = gift.splash_birds(scores, ["Cyanocitta stelleri"], DRAWABLE)
    assert birds[:3] == ("Cyanocitta stelleri", "Turdus migratorius", "Cardinalis cardinalis")


def test_the_splash_holds_at_most_its_share():
    scores = [(f"{key.replace('-', ' ').capitalize()}", 0.5) for key in sorted(DRAWABLE)]
    assert len(gift.splash_birds(scores, [], DRAWABLE)) == gift.SPLASH_BIRDS


@pytest.fixture(scope="module")
def names():
    return gift.Names.of(Path("/nonexistent"), "sci")


@pytest.mark.parametrize(
    ("typed", "found", "guess"),
    [
        ("Steller's Jay", "Cyanocitta stelleri", ""),
        ("stellers jay", "Cyanocitta stelleri", ""),
        ("cyanocitta stelleri", "Cyanocitta stelleri", ""),
        ("stellar jay", None, "Steller's Jay"),
        ("cardnal", None, "Northern Cardinal"),
        ("robin", None, "American Robin"),  # the likeliest robin where it goes
        ("zzzz", None, ""),
    ],
)
def test_a_favourite_is_matched_or_a_likely_one_suggested(names, typed, found, guess):
    scores = {"Turdus migratorius": 0.9, "Cardinalis cardinalis": 0.8}
    match = gift.favourite(typed, names, DRAWABLE, scores)
    assert (match.name, match.guess) == (found, guess)
    assert bool(match.problem) == (found is None)


def test_a_favourite_without_a_plate_says_so(names):
    match = gift.favourite("Steller's Jay", names, set(), {})
    assert match == gift.Favourite(None, "There is no picture of Steller's Jay in this style.")


def test_the_place_is_written_into_birdnets_section_alone():
    text = "realtime:\n  latitude: 1\n" + TEMPLATE
    new, lat, lon = gift.located(text, "39.9600", "-82.9900")
    assert (lat, lon) == ("60.39", "5.32")
    assert "  latitude: 39.9600\n  longitude: -82.9900\n" in new
    assert new.startswith("realtime:\n  latitude: 1\n")  # another section's is left alone
    assert new.replace("39.9600", "60.39").replace("-82.9900", "5.32") == text


def test_a_config_without_the_place_is_refused():
    with pytest.raises(ValueError):
        gift.located("logging:\n  default_level: info\n", "0", "0")


@pytest.fixture
def calls(monkeypatch) -> list[tuple[str, ...]]:
    """docker, recorded rather than run; the container was restarting unless stopped."""
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args)
        return "unless-stopped" if args[0] == "inspect" else ""

    monkeypatch.setattr(gift, "docker", docker)
    return calls


@pytest.fixture
def frame(tmp_path, calls) -> gift.Paths:
    """An appliance's files, its undo record in a folder of its own."""
    paths = gift.Paths(
        data=tmp_path / "data", detector=tmp_path / "detector", undo=tmp_path / "shm" / "undo"
    )
    paths.data.mkdir()
    paths.undo.parent.mkdir()
    paths.birdnet_config.parent.mkdir(parents=True)
    paths.birdnet_config.write_text(TEMPLATE)
    paths.env.write_text("")
    for name in ("birdnet.db", "birdnet.db-wal", "birdnet.db.bak"):  # .bak: an update's
        (paths.data / name).write_bytes(b"detections")
    (paths.data / "clips").mkdir()
    (paths.data / "clips" / "merula.mp3").write_bytes(b"song")
    (paths.data / "settings.json").write_text("{}")
    return paths


SPLASH = gift.Splash("May", ("Happy birthday!",), ("Cyanocitta stelleri",), "Cyanocitta stelleri")
WRAPPING = gift.Wrapping(
    place=gift.Place("Columbus, Ohio", 39.96, -82.99),
    splash=SPLASH,
    ssid="Their home",
    password="their-password",
    clear_admin=True,
)


def _plain(calls):
    """The docker calls without compose's file arguments."""
    return [args if args[0] != "compose" else ("compose", args[-1]) for args in calls]


def test_wrapping_readies_the_frame_and_unwrapping_puts_it_back(frame, calls):
    drawn, forgotten, restored, done = [], [], [], []
    gift.wrap(
        frame, WRAPPING, lambda ssid, pw: "uuid-1", lambda: "old-secret", drawn.append, done.append
    )

    assert gift.read_undo(frame.undo) == gift.Restore(
        "unless-stopped", "60.39", "5.32", "uuid-1", "old-secret"
    )
    assert not list(frame.data.glob("birdnet.db*")) and not (frame.data / "clips").exists()
    assert "latitude: 39.9600" in frame.birdnet_config.read_text()
    assert drawn == [SPLASH] and len(done) == 6
    # Stopped by hand, it comes back at the first boot only if it restarts always.
    assert _plain(calls)[1:] == [
        ("update", "--restart", "always", "birdnet-go"),
        ("compose", "stop"),
    ]

    assert gift.unwrap(frame, forgotten.append, restored.append)
    assert frame.birdnet_config.read_text() == TEMPLATE
    assert (forgotten, restored) == (["uuid-1"], ["old-secret"])
    assert _plain(calls)[3:] == [
        ("update", "--restart", "unless-stopped", "birdnet-go"),
        ("compose", "start"),
    ]
    assert not frame.undo.exists()
    assert not gift.unwrap(frame, forgotten.append, restored.append)  # nothing left to undo


def test_a_wrap_that_fails_half_way_can_still_be_unwrapped(frame, calls):
    def no_wifi(_ssid, _password):
        raise RuntimeError("nmcli refused")

    with pytest.raises(RuntimeError):
        gift.wrap(frame, WRAPPING, no_wifi, lambda: "old-secret", lambda _s: None)
    assert (frame.data / "birdnet.db").exists()  # deleted last, so still here
    assert gift.unwrap(frame, lambda _uuid: None, lambda _pw: None)
    assert frame.birdnet_config.read_text() == TEMPLATE
    assert _plain(calls)[-1] == ("compose", "start")


def test_a_config_it_cannot_read_stops_the_wrap_before_anything_changes(frame, calls):
    frame.birdnet_config.write_text("logging:\n  default_level: info\n")
    with pytest.raises(ValueError):
        gift.wrap(frame, WRAPPING, lambda *_a: "uuid", lambda: "", lambda _s: None)
    assert calls == [] and not frame.undo.exists() and (frame.data / "birdnet.db").exists()


def test_what_wrapping_deletes_is_counted_first(frame):
    class Source:
        def stats(self):
            return {"total": 2847, "species": 61}

        def life_list(self):
            return [Species("Turdus merula", datetime(2026, 9, 14, 6, tzinfo=UTC))]

    assert gift.heard(frame, Source()) == gift.Heard(2847, 61, date(2026, 9, 14), 1, 4)


def test_a_detector_that_does_not_answer_still_counts_the_clips(frame):
    class Down:
        def stats(self):
            raise Unavailable("down")

    assert gift.heard(frame, Down()) == gift.Heard(None, None, None, 1, 4)


def test_the_undo_record_is_private(frame):
    gift.write_undo(frame.undo, gift.Restore("unless-stopped"))
    assert frame.undo.stat().st_mode & 0o777 == 0o600


_GOOD = gift.Restore("unless-stopped", "60.39", "5.32", "uuid-1", "secret")


def _broken(text: str):
    return lambda raw: text


def _with(**changes):
    return lambda raw: json.dumps({**raw, **changes})


@pytest.mark.parametrize(
    "spoil",
    [
        _broken(""),
        _broken("{not json"),
        _broken("[]"),
        _broken("null"),
        _with(restart=None),
        _with(latitude="north"),
        _with(longitude=5.32),
        _with(wifi=["uuid-1"]),
        _with(admin_password=1),
        _with(extra="key"),
        lambda raw: json.dumps({k: v for k, v in raw.items() if k != "wifi"}),
    ],
)
def test_an_undo_record_with_anything_wrong_is_deleted_and_logged(tmp_path, caplog, spoil):
    path = tmp_path / "undo.json"
    gift.write_undo(path, _GOOD)
    assert gift.read_undo(path) == _GOOD
    path.write_text(spoil(json.loads(path.read_text())))
    assert gift.read_undo(path) is None
    assert not path.exists()
    assert gift.read_undo(path) is None
    warned = [r for r in caplog.records if r.getMessage().startswith("Deleting")]
    assert len(warned) == 1


def test_a_note_line_too_wide_for_the_panel_says_by_how_much():
    small = (800, 480)
    assert overflow("Happy birthday!", "gentium", small, Edges.even(0.04)) == 0
    assert overflow("Happy birthday! " * 8, "gentium", small, Edges.even(0.04)) > 0
    # The 13.3" sets the same line at the same share of its width.
    assert overflow("Happy birthday! " * 8, "gentium", (1600, 1200), Edges.even(0.04)) > 0


def test_the_splash_fills_the_panel():
    birds = REPO_ROOT / "assets" / "artwork" / "classic" / "birds"
    entries = [("Cyanocitta stelleri", birds / "cyanocitta-stelleri.webp")]
    page = splash(entries, "Cyanocitta stelleri", "May", ("Hi",), (800, 480), Edges.even(0.04))
    assert page.size == (800, 480)
