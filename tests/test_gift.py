"""Gift mode (#355): what the form checks, what wrapping changes, and that it all comes back."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path

import pytest

from fugleramme import gift
from fugleramme.config import REPO_ROOT
from fugleramme.names import drawable_keys
from fugleramme.render.gift import overflow, splash
from fugleramme.render.page import Edges

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
        ("20270512", "use YYYY-MM-DD"),  # date.fromisoformat would take it
        ("2027-02-30", "not a date"),
        ("2026-11-04", "in the past"),
        ("2026-11-05", ""),
    ],
)
def test_the_arrival_is_a_day_from_today_on(typed, problem):
    assert gift.arrival(typed, TODAY)[1] == problem


def test_wifi_is_checked_for_shape_only():
    assert gift.ssid_problem("x" * 32) == "" and gift.ssid_problem("x" * 33) == "too long"
    assert gift.ssid_problem("æ" * 17) == "too long"  # bytes, not characters
    assert gift.password_problem("") == ""  # open
    assert gift.password_problem("short") == "WPA2 needs 8-63"
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
    ("typed", "found", "problem"),
    [
        ("Steller's Jay", "Cyanocitta stelleri", ""),
        ("stellers jay", "Cyanocitta stelleri", ""),
        ("cyanocitta stelleri", "Cyanocitta stelleri", ""),
        ("stellar jay", None, "no match - Steller's Jay?"),
        ("cardnal", None, "no match - Northern Cardinal?"),
        ("robin", None, "no match - American Robin?"),  # the likeliest robin where it goes
        ("zzzz", None, "no bird called zzzz"),
    ],
)
def test_a_favourite_is_matched_or_a_likely_one_suggested(names, typed, found, problem):
    scores = {"Turdus migratorius": 0.9, "Cardinalis cardinalis": 0.8}
    assert gift.favourite(typed, names, DRAWABLE, scores) == (found, problem)


def test_a_favourite_without_a_plate_says_so(names):
    assert gift.favourite("Steller's Jay", names, set(), {}) == (None, "no plate for Steller's Jay")


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
    """docker compose, recorded rather than run."""
    calls: list[tuple[str, ...]] = []
    monkeypatch.setattr(gift, "compose", lambda _paths, *args: calls.append(args))
    return calls


@pytest.fixture
def frame(tmp_path, calls) -> gift.Paths:
    """An appliance's files."""
    paths = gift.Paths(data=tmp_path / "data", detector=tmp_path / "detector")
    paths.data.mkdir()
    paths.birdnet_config.parent.mkdir(parents=True)
    paths.birdnet_config.write_text(TEMPLATE)
    paths.env.write_text("")
    db = sqlite3.connect(paths.data / "birdnet.db")
    db.execute("create table notes (id integer primary key, scientific_name text)")
    db.execute("insert into notes (scientific_name) values ('Turdus merula')")
    db.commit()
    db.close()
    (paths.data / "clips").mkdir()
    (paths.data / "clips" / "merula.mp3").write_bytes(b"song")
    return paths


WRAPPING = gift.Wrapping(
    place=gift.Place("Columbus, Ohio", 39.96, -82.99),
    month="May",
    notes=("Happy birthday!",),
    birds=("Cyanocitta stelleri", "Turdus migratorius"),
    spotlight="Cyanocitta stelleri",
    ssid="Their home",
    password="their-password",
    clear_admin=True,
)


def test_wrapping_sets_everything_aside_and_unwrapping_puts_it_back(frame, calls):
    before = frame.birdnet_config.read_text()
    forgotten, restored, done = [], [], []
    gift.wrap(frame, WRAPPING, lambda ssid, pw: "uuid-1", lambda: "old-secret", done.append)

    wrapped = gift.read(frame.gift)
    assert wrapped is not None and wrapped.state == gift.WRAPPING
    assert wrapped.restore == gift.Restore("60.39", "5.32", "old-secret", "uuid-1", stopped=True)
    assert not (frame.data / "birdnet.db").exists() and not (frame.data / "clips").exists()
    assert "latitude: 39.9600" in frame.birdnet_config.read_text()
    assert calls == [("stop",)]
    assert len(done) == 5

    gift.unwrap(frame, wrapped, forgotten.append, restored.append)
    assert frame.birdnet_config.read_text() == before
    rows = sqlite3.connect(frame.data / "birdnet.db").execute("select * from notes").fetchall()
    assert rows == [(1, "Turdus merula")]
    assert (frame.data / "clips" / "merula.mp3").read_bytes() == b"song"
    assert (forgotten, restored) == (["uuid-1"], ["old-secret"])
    assert not frame.gift.exists() and not frame.history.exists()
    assert calls == [("stop",), ("start",)]


def test_a_wrap_that_fails_half_way_can_still_be_unwrapped(frame):
    def no_wifi(_ssid, _password):
        raise RuntimeError("nmcli refused")

    with pytest.raises(RuntimeError):
        gift.wrap(frame, WRAPPING, no_wifi, lambda: "old-secret")
    half = gift.read(frame.gift)
    assert half is not None and half.state == gift.PREVIEW
    gift.unwrap(frame, half, lambda _uuid: None, lambda _pw: None)
    assert frame.birdnet_config.read_text() == TEMPLATE
    assert (frame.data / "birdnet.db").exists()


def test_a_gift_opens_on_the_first_boot_after_it_was_wrapped(frame, calls):
    gift.wrap(frame, WRAPPING, lambda ssid, pw: "uuid-1", lambda: "")
    wrapped = gift.read(frame.gift)
    assert wrapped is not None
    boxed = gift.Gift(**{**wrapped.__dict__, "state": gift.WRAPPED, "boot": "boot-1"})
    gift.write(frame.gift, boxed)

    assert not gift.opened(frame, boxed, "boot-1")  # the service restarted, still unplugged
    assert not gift.opened(frame, boxed, "")  # no boot id: never opened by a guess
    assert frame.gift.exists()

    assert gift.opened(frame, boxed, "boot-2")
    assert not frame.gift.exists() and not frame.history.exists()
    assert calls[-1] == ("start",)


def test_a_preview_is_never_opened(frame):
    preview = gift.Gift(gift.PREVIEW, "May", (), (), None)
    assert not gift.opened(frame, preview, "boot-2")


def test_a_broken_gift_file_is_no_gift(tmp_path):
    path = tmp_path / "gift.json"
    path.write_text("{not json")
    assert gift.read(path) is None
    assert gift.read(tmp_path / "missing.json") is None


def test_the_gift_file_is_private(frame):
    gift.write(frame.gift, gift.Gift(gift.PREVIEW, "May", (), (), None))
    assert frame.gift.stat().st_mode & 0o777 == 0o600


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
