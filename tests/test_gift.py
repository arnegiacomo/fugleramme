"""Gift mode (#355): what the questions check, and what wrapping changes."""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from fugleramme import gift
from fugleramme.config import PANEL_SIZES, REPO_ROOT
from fugleramme.names import drawable_keys
from fugleramme.render.gift import TITLE, note_font, overflow, smallest_title, splash, title_font
from fugleramme.render.page import Edges
from fugleramme.source import Unavailable

TEMPLATE = (REPO_ROOT / "detector" / "config" / "config.yaml.template").read_text()
DRAWABLE = drawable_keys(REPO_ROOT / "assets" / "artwork", "classic")
COLUMBUS = gift.Place("Columbus, Ohio", 39.96, -82.99)


def test_a_typed_position_needs_no_search():
    def refuse(_url):
        raise AssertionError("asked Photon")

    assert gift.find_place("39.96, -82.99", refuse) == gift.Place("39.96, -82.99", 39.96, -82.99)
    assert gift.find_place("95, 0", refuse) is None


def test_a_place_takes_photons_first_answer():
    answer = {
        "features": [
            {
                "geometry": {"coordinates": [-82.99, 39.96]},
                "properties": {
                    "name": "Columbus",
                    "state": "Ohio",
                    "country": "United States",
                    "countrycode": "US",
                },
            }
        ]
    }
    place = gift.find_place("columbus", lambda _url: answer)
    assert place == gift.Place("Columbus, Ohio, United States", 39.96, -82.99, "US")
    assert gift.find_place("nowhere", lambda _url: {"features": []}) is None


def test_the_timezone_is_the_lookups_or_none():
    def offline(_url):
        raise OSError("down")

    assert gift.zone_at(COLUMBUS, lambda _url: {"timezone": "America/New_York"}) == (
        "America/New_York"
    )
    assert gift.zone_at(COLUMBUS, lambda _url: {"timezone": "Mars/Olympus"}) == ""
    assert gift.zone_at(COLUMBUS, lambda _url: {}) == ""
    assert gift.zone_at(COLUMBUS, offline) == ""


GBIF = {
    "facets": [
        {
            "counts": [
                {"name": "Cardinalis cardinalis (Linnaeus, 1758)", "count": 900},
                {"name": "Turdus migratorius Linnaeus, 1766", "count": 500},
                {"name": "Anas platyrhynchos x rubripes", "count": 450},  # a hybrid
                {"name": "Turdus migratorius migratorius", "count": 450},  # a subspecies
                {"name": "Aves", "count": 400},
            ]
        }
    ]
}


def test_the_birds_recorded_near_a_place_are_asked_of_gbif_for_this_month():
    asked = []

    def fetch(url):
        asked.append(url)
        return GBIF

    names = gift.recorded(COLUMBUS, date(2026, 12, 24), fetch)
    assert names == ["Turdus migratorius", "Cardinalis cardinalis"]  # 950 with its subspecies
    assert "geoDistance=39.96%2C-82.99%2C50km" in asked[0]
    assert "month=12" in asked[0] and "year=2017%2C2026" in asked[0]


def test_a_country_has_its_birds_in_the_snapshot_most_recorded_first():
    norway = gift.recorded_in("NO")
    assert norway[0] == "Parus major" and len(norway) > 100
    assert gift.recorded_in("") == [] and gift.recorded_in("XX") == []


def test_the_country_stands_in_when_gbif_does_not_answer_or_knows_nothing():
    def offline(_url):
        raise OSError("down")

    norway = gift.Place("Bergen", 60.39, 5.32, "NO")
    today = date(2026, 12, 24)
    assert gift.likely(norway, today, lambda _url: GBIF)[0] == "Turdus migratorius"
    assert gift.likely(norway, today, offline)[0] == "Parus major"
    assert gift.likely(norway, today, lambda _url: {"facets": []})[0] == "Parus major"
    assert gift.likely(COLUMBUS, today, offline) == []  # a typed position has no country


def test_the_top_birds_are_the_first_with_a_plate():
    names = ["Turdus migratorius", "Not avis", "Cardinalis cardinalis", "Turdus migratorius"]
    assert gift.top_birds(names, DRAWABLE) == ("Turdus migratorius", "Cardinalis cardinalis")
    every = [key.replace("-", " ").capitalize() for key in sorted(DRAWABLE)]
    assert len(gift.top_birds(every, DRAWABLE)) == gift.BIRDS == 20
    assert (
        len(gift.top_birds(every, DRAWABLE, 40)) == 40 and gift.top_birds(every, DRAWABLE, 0) == ()
    )


@pytest.fixture(scope="module")
def names():
    return gift.Names.of(Path("/nonexistent"), "sci", DRAWABLE)


@pytest.mark.parametrize(
    ("typed", "found"),
    [
        ("Steller's Jay", "Cyanocitta stelleri"),
        ("stellers jay", "Cyanocitta stelleri"),
        ("cyanocitta stelleri", "Cyanocitta stelleri"),
        ("stellar jay", None),
    ],
)
def test_a_bird_is_picked_by_any_of_its_names(names, typed, found):
    assert names.match(typed) == found


def test_the_search_offers_both_names_of_birds_with_a_plate(names):
    assert "Steller's Jay" in names.shown and "Cyanocitta stelleri" in names.shown
    assert gift.Names.of(Path("/nonexistent"), "sci", set()).shown == ()


def test_the_place_is_written_into_birdnets_section_alone():
    text = "realtime:\n  latitude: 1\n" + TEMPLATE
    new = gift.located(text, "39.9600", "-82.9900")
    assert "  latitude: 39.9600\n  longitude: -82.9900\n" in new
    assert new.startswith("realtime:\n  latitude: 1\n")  # another section's is left alone
    assert new.replace("39.9600", "60.39").replace("-82.9900", "5.32") == text


def test_a_config_without_the_place_is_refused():
    with pytest.raises(ValueError):
        gift.located("logging:\n  default_level: info\n", "0", "0")


def test_the_containers_timezone_is_the_line_run_sh_writes():
    env = "BIRDNET_PORT=8090\nTZ=Europe/Oslo\n"
    assert gift.zoned(env, "America/New_York") == "BIRDNET_PORT=8090\nTZ=America/New_York\n"
    assert gift.zoned("BIRDNET_PORT=8090\n", "America/New_York") == (
        "BIRDNET_PORT=8090\nTZ=America/New_York\n"
    )


@pytest.fixture
def calls(monkeypatch) -> list[tuple[str, ...]]:
    """docker and sudo, recorded rather than run."""
    calls: list[tuple[str, ...]] = []

    def docker(*args: str) -> str:
        calls.append(args[5:] if args[0] == "compose" else args)  # past compose's files
        return ""

    def root(*command: str) -> bool:
        calls.append(("sudo", *command))
        return True

    monkeypatch.setattr(gift, "docker", docker)
    monkeypatch.setattr(gift, "root", root)
    return calls


@pytest.fixture
def frame(tmp_path, calls) -> gift.Paths:
    """An appliance's files."""
    paths = gift.Paths(data=tmp_path / "data", detector=tmp_path / "detector")
    paths.data.mkdir()
    paths.birdnet_config.parent.mkdir(parents=True)
    paths.birdnet_config.write_text(TEMPLATE)
    paths.env.write_text("TZ=Europe/Oslo\n")
    for name in ("birdnet.db", "birdnet.db-wal", "birdnet.db.bak"):  # .bak: an update's
        (paths.data / name).write_bytes(b"detections")
    (paths.data / "clips").mkdir()
    (paths.data / "clips" / "merula.mp3").write_bytes(b"song")
    return paths


def test_wrapping_readies_the_frame_for_its_new_home(frame, calls):
    cleared, done = [], []
    wrapping = gift.Wrapping(COLUMBUS, "America/New_York", delete=True, clear_admin=True)
    gift.wrap(frame, wrapping, lambda: cleared.append(True), done.append)

    assert not list(frame.data.glob("birdnet.db*")) and not (frame.data / "clips").exists()
    assert "latitude: 39.9600" in frame.birdnet_config.read_text()
    assert frame.env.read_text() == "TZ=America/New_York\n"
    assert cleared == [True]
    assert done == [
        "BirdNET-Go stopped",
        "Location set to Columbus, Ohio",
        "Timezone set to America/New_York",
        "Admin password removed",
        "Detections and clips deleted",
        "BirdNET-Go started",
    ]
    # Stopped by hand it would stay stopped at every boot, so it is brought back up.
    assert calls == [
        ("stop",),
        ("sudo", "timedatectl", "set-timezone", "America/New_York"),
        ("up", "-d"),
    ]


def test_a_wrap_changes_only_what_it_was_asked_to(frame, calls):
    def never():
        raise AssertionError("cleared the admin password")

    gift.wrap(frame, gift.Wrapping(COLUMBUS), never)
    assert (frame.data / "birdnet.db").exists() and (frame.data / "clips").exists()
    assert frame.env.read_text() == "TZ=Europe/Oslo\n"
    assert calls == [("stop",), ("up", "-d")]


def test_a_wrap_that_fails_half_way_still_starts_birdnet_go(frame, calls, monkeypatch):
    monkeypatch.setattr(gift, "root", lambda *_command: False)
    with pytest.raises(RuntimeError, match="timezone"):
        gift.wrap(frame, gift.Wrapping(COLUMBUS, "America/New_York", delete=True), lambda: None)
    assert calls[-1] == ("up", "-d")
    assert (frame.data / "birdnet.db").exists()  # deleted last, so still here


def test_a_frame_without_its_own_birdnet_go_keeps_its_place_and_birds(frame, calls):
    frame.env.unlink()  # reads BirdWeather, or a BirdNET-Go elsewhere
    cleared, done = [], []
    wrapping = gift.Wrapping(None, "America/New_York", clear_admin=True)
    gift.wrap(frame, wrapping, lambda: cleared.append(True), done.append)
    assert frame.birdnet_config.read_text() == TEMPLATE and (frame.data / "birdnet.db").exists()
    assert calls == [("sudo", "timedatectl", "set-timezone", "America/New_York")]  # no docker
    assert cleared == [True]
    assert done == ["Timezone set to America/New_York", "Admin password removed"]
    assert not frame.env.exists()


def test_a_config_it_cannot_read_stops_the_wrap_before_anything_changes(frame, calls):
    frame.birdnet_config.write_text("logging:\n  default_level: info\n")
    with pytest.raises(ValueError):
        gift.wrap(frame, gift.Wrapping(COLUMBUS, delete=True), lambda: None)
    assert calls == [] and (frame.data / "birdnet.db").exists()


def test_what_wrapping_can_delete_is_counted_first():
    class Source:
        def stats(self):
            return {"total": 2847, "species": 61}

    class Down:
        def stats(self):
            raise Unavailable("down")

    assert gift.heard(Source()) == 2847  # type: ignore[arg-type]
    assert gift.heard(Down()) is None  # type: ignore[arg-type]


def test_a_line_too_wide_for_the_panel_says_by_how_much():
    small, margin = (800, 480), Edges.even(0.04)
    font = note_font("gentium", min(small))
    assert overflow("Happy birthday!", font, small, margin) == 0
    assert overflow("", font, small, margin) == 0
    assert overflow("Happy birthday! " * 8, font, small, margin) > 0
    # The 13.3" sets the same line at the same share of its width.
    large = (1600, 1200)
    assert overflow("Happy birthday! " * 8, note_font("gentium", 1200), large, margin) > 0


@pytest.mark.parametrize("panel", PANEL_SIZES.values())
def test_the_title_shrinks_to_fit_a_narrow_panel(panel):
    margin = Edges.even(0.08)
    full = title_font("Birds", panel, margin).size
    for size in (panel, panel[::-1]):
        font = title_font(TITLE, size, margin)
        assert overflow(TITLE, font, size, margin) == 0
        assert smallest_title(min(size)).size < font.size <= full
    assert title_font(TITLE, panel, margin).size == full  # landscape has the room


def test_the_splash_fills_the_panel():
    birds = REPO_ROOT / "assets" / "artwork" / "classic" / "birds"
    entries = [("Cyanocitta stelleri", birds / "cyanocitta-stelleri.webp")]
    page = splash(entries, TITLE, ("Hi",), (800, 480), Edges.even(0.04))
    assert page.size == (800, 480)
