"""The bird of the day walks the life list rather than rolling it: no bird gets
a second page before every bird has had one, only the render loop advances the
walk, and a bird's lap counts how many times round it has been - which is what
lets a species with several plates wear a different one each visit."""

from __future__ import annotations

import json

from fugleramme.featured import Featured

BIRDS = ["Turdus merula", "Parus major", "Pica pica"]


def _name(result):
    return result[0] if result else None


def test_the_walk_visits_every_bird_before_repeating(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    seen = [_name(walk.choose(day, BIRDS, commit=True)) for day in range(len(BIRDS))]
    assert sorted(seen) == sorted(BIRDS)
    assert _name(walk.choose(len(BIRDS), BIRDS, commit=True)) == seen[0]  # round two, same order


def test_the_first_pass_follows_life_list_order(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    assert _name(walk.choose(1, BIRDS, commit=True)) == BIRDS[0]
    assert _name(walk.choose(2, BIRDS, commit=True)) == BIRDS[1]


def test_a_new_species_jumps_the_queue(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    for day, _ in enumerate(BIRDS):
        walk.choose(day, BIRDS, commit=True)
    assert _name(walk.choose(99, BIRDS + ["Erithacus rubecula"], commit=True)) == "Erithacus rubecula"


def test_the_pick_holds_all_day(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    first = walk.choose(1, BIRDS, commit=True)
    assert walk.choose(1, BIRDS, commit=True) == first


def test_a_peek_agrees_with_the_commit_but_does_not_advance(tmp_path):
    path = tmp_path / "featured.json"
    walk = Featured(path)
    assert walk.choose(1, BIRDS) == walk.choose(1, BIRDS, commit=True)

    # The kiosk peeking at tomorrow must not consume tomorrow's bird.
    assert Featured(path).choose(2, BIRDS) == Featured(path).choose(2, BIRDS, commit=True)
    assert json.loads(path.read_text())["day"] == 2


def test_the_walk_survives_a_restart(tmp_path):
    path = tmp_path / "featured.json"
    Featured(path).choose(1, BIRDS, commit=True)
    assert Featured(path).choose(1, BIRDS) == Featured(path).choose(1, BIRDS)


def test_a_pick_that_lost_its_artwork_is_replaced(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    held = _name(walk.choose(1, BIRDS, commit=True))
    rest = [b for b in BIRDS if b != held]
    assert _name(walk.choose(1, rest, commit=True)) in rest


def test_nothing_to_choose_from(tmp_path):
    assert Featured(tmp_path / "featured.json").choose(1, []) is None


def test_a_corrupt_file_starts_the_walk_over(tmp_path):
    path = tmp_path / "featured.json"
    path.write_text("{not json")
    assert _name(Featured(path).choose(1, BIRDS, commit=True)) == BIRDS[0]


def test_the_lap_counts_visits_not_days(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    laps = []
    for day in range(len(BIRDS) * 3):
        name, lap = walk.choose(day, BIRDS, commit=True)
        if name == BIRDS[0]:
            laps.append(lap)
    assert laps == [0, 1, 2]


def test_todays_lap_is_stable_once_committed(tmp_path):
    """The counter has moved on by the time the kiosk asks, so today's lap is
    stored with today's bird rather than re-derived from it."""
    path = tmp_path / "featured.json"
    walk = Featured(path)
    peeked = walk.choose(1, BIRDS)
    assert walk.choose(1, BIRDS, commit=True) == peeked
    assert walk.choose(1, BIRDS) == peeked
    assert Featured(path).choose(1, BIRDS) == peeked  # and across a restart


def test_a_second_lap_starts_where_the_first_left_off(tmp_path):
    path = tmp_path / "featured.json"
    for day in range(len(BIRDS)):
        Featured(path).choose(day, BIRDS, commit=True)
    name, lap = Featured(path).choose(len(BIRDS), BIRDS, commit=True)
    assert (name, lap) == (BIRDS[0], 1)
