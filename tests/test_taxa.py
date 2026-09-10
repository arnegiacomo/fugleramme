"""Non-birds reach nothing above the source.

Both endpoints are filtered, so the feed and the summary have to agree that a bat
was never there.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from fugleramme import api, fake, taxa
from fugleramme.taxa import is_bird

BLACKBIRD, TIT = "Turdus merula", "Parus major"
BAT, VOICES = "Myotis daubentonii", "Human vocal"

LABELS = Path(__file__).resolve().parents[1] / "assets" / "birdnet_labels_v2.4.txt"

# BirdNET v2.4's labels that are a sound rather than a species.
NOISE = {
    "Dog",
    "Engine",
    "Environmental",
    "Fireworks",
    "Gun",
    "Human non-vocal",
    "Human vocal",
    "Human whistle",
    "Noise",
    "Power tools",
    "Siren",
}


def test_it_drops_every_non_bird_in_v2_4_and_no_bird_at_all():
    """Both directions, and the only place either can be proved: nothing non-bird
    is left over, and a genus that ate a bird would move the count.

    101 of 6522 - the noise classes, 41 frogs and toads, 41 crickets and katydids,
    a honey bee, and seven mammals from a chipmunk to a howler monkey."""
    labels = {line.split("_")[0] for line in LABELS.read_text().split("\n") if line}
    dropped = {name for name in labels if not is_bird(name)}

    assert len(dropped) == 101
    assert NOISE <= dropped
    assert {"Sciurus carolinensis", "Pseudacris crucifer", "Apis mellifera"} <= dropped
    assert not dropped & {BLACKBIRD, TIT, "Falco rufigularis"}  # the last is a Bat Falcon


@pytest.mark.parametrize("name", [BLACKBIRD, TIT, "Pica pica", " TURDUS MERULA "])
def test_a_v2_4_bird_is_a_bird(name):
    assert is_bird(name)


@pytest.mark.parametrize("name", [VOICES, "Dog", "Power tools", "Sciurus carolinensis"])
def test_a_v2_4_label_that_is_not_a_bird_is_dropped(name):
    assert not is_bird(name)


# The label file carries the old spelling and `api._merged` serves the new one.
# Drop `normalize` and the goshawk goes the way of a bat; drop `hapithus` from the
# genus list and the cricket comes back a bird.
GOSHAWK = ("Accipiter gentilis", "Astur gentilis")
CRICKET = ("Orocharis saltator", "Hapithus saltator")


@pytest.mark.parametrize("name", GOSHAWK)
def test_a_reclassified_bird_is_a_bird_under_either_name(name):
    assert is_bird(name)


@pytest.mark.parametrize("name", CRICKET)
def test_a_reclassified_non_bird_is_dropped_under_either_name(name):
    assert not is_bird(name)


@pytest.mark.parametrize("name", [BAT, "Hipposideros armiger", "Pipistrellus pipistrellus"])
def test_a_label_from_another_model_is_dropped_whatever_its_genus(name):
    # No genus list to be short of: no bat is a v2.4 label.
    assert not is_bird(name)


def test_a_nameless_row_is_not_a_bird():
    # A missing field is a different case: `api` indexes it directly, so a renamed
    # field raises Unavailable rather than quietly emptying the page.
    assert not is_bird("")


def test_no_label_list_leaves_the_genus_check_standing(monkeypatch, tmp_path):
    """A frame that cannot read the file draws the odd frog, where one dropping
    every unknown name would draw nothing at all."""
    monkeypatch.setattr(taxa, "LABELS", tmp_path / "gone.txt")
    taxa._labels.cache_clear()

    assert is_bird(BLACKBIRD)
    assert is_bird(BAT)  # the allowlist caught these, and it is gone
    assert not is_bird(VOICES)  # the genera are compiled in

    taxa._labels.cache_clear()


def _rows(*names: str) -> list[fake.Detection]:
    """Newest first, one a minute back, none a false positive."""
    now = datetime.now().astimezone()
    return [
        fake.Detection(
            id=len(names) - i,
            at=now - timedelta(minutes=i),
            scientific_name=name,
            confidence=0.9,
            false_positive=False,
        )
        for i, name in enumerate(names)
    ]


def test_a_bat_is_on_neither_endpoint(source):
    # The bat is the newest row, so it would hold the "Latest bird" plate.
    detector = source(rows=_rows(BAT, BLACKBIRD, VOICES, BLACKBIRD, TIT))

    assert [d.scientific_name for d in detector.recent(10)] == [BLACKBIRD, BLACKBIRD, TIT]
    assert detector.latest().scientific_name == BLACKBIRD
    assert detector.species_since(6) == [(BLACKBIRD, 2), (TIT, 1)]  # counted off the feed
    assert detector.species_since(24) == [(BLACKBIRD, 2), (TIT, 1)]  # off the summary
    assert [s.scientific_name for s in detector.life_list()] == [TIT, BLACKBIRD]


def test_a_station_that_hears_nothing_else_reads_as_no_birds(source):
    detector = source(rows=_rows(BAT, VOICES))

    assert detector.recent(10) == []
    assert detector.latest() is None
    assert detector.species_since(24) == []
    assert detector.life_list() == []


def test_the_source_names_a_non_bird_once_rather_than_every_poll(source, caplog, monkeypatch):
    """A bird dropped because the alias map is behind the detector is otherwise
    unaccountable: it is simply not on the page and nothing says why."""
    caplog.set_level(logging.INFO, logger="fugleramme.api")
    monkeypatch.setattr(api, "_TTL", 0)  # every call refetches, as a long run would
    detector = source(rows=_rows(BAT, BLACKBIRD, VOICES))

    for _ in range(3):
        detector.species_since(24)
        detector.recent(10)

    named = [r.getMessage() for r in caplog.records if "Not a bird" in r.msg]
    assert sorted(named) == [
        f"Not a bird, ignoring detections of {VOICES}",
        f"Not a bird, ignoring detections of {BAT}",
    ]
