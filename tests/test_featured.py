"""The bird of the day walks the life list rather than rolling it: no bird gets
a second page before every bird has had one, and only the render loop advances
the walk."""

from __future__ import annotations

import json

from fugleramme.featured import Featured

BIRDS = ["Turdus merula", "Parus major", "Pica pica"]


def test_the_walk_visits_every_bird_before_repeating(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    seen = [walk.choose(day, BIRDS, commit=True) for day in range(len(BIRDS))]
    assert sorted(seen) == sorted(BIRDS)
    assert walk.choose(len(BIRDS), BIRDS, commit=True) == seen[0]  # round two, same order


def test_the_first_pass_follows_life_list_order(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    assert walk.choose(1, BIRDS, commit=True) == BIRDS[0]
    assert walk.choose(2, BIRDS, commit=True) == BIRDS[1]


def test_a_new_species_jumps_the_queue(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    for day, _ in enumerate(BIRDS):
        walk.choose(day, BIRDS, commit=True)
    assert walk.choose(99, BIRDS + ["Erithacus rubecula"], commit=True) == "Erithacus rubecula"


def test_the_pick_holds_all_day(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    first = walk.choose(1, BIRDS, commit=True)
    assert walk.choose(1, BIRDS, commit=True) == first


def test_a_peek_agrees_with_the_commit_but_does_not_advance(tmp_path):
    path = tmp_path / "featured.json"
    walk = Featured(path)
    assert walk.choose(1, BIRDS) == walk.choose(1, BIRDS, commit=True)
    assert not (tmp_path / "nothing").exists()

    # The kiosk peeking at tomorrow must not consume tomorrow's bird.
    peeked = Featured(path)
    assert peeked.choose(2, BIRDS) == Featured(path).choose(2, BIRDS, commit=True)
    assert json.loads(path.read_text())["day"] == 2


def test_the_walk_survives_a_restart(tmp_path):
    path = tmp_path / "featured.json"
    Featured(path).choose(1, BIRDS, commit=True)
    assert Featured(path).choose(1, BIRDS) == Featured(path).choose(1, BIRDS)


def test_a_pick_that_lost_its_artwork_is_replaced(tmp_path):
    walk = Featured(tmp_path / "featured.json")
    held = walk.choose(1, BIRDS, commit=True)
    rest = [b for b in BIRDS if b != held]
    assert walk.choose(1, rest, commit=True) in rest


def test_nothing_to_choose_from(tmp_path):
    assert Featured(tmp_path / "featured.json").choose(1, []) is None


def test_a_corrupt_file_starts_the_walk_over(tmp_path):
    path = tmp_path / "featured.json"
    path.write_text("{not json")
    assert Featured(path).choose(1, BIRDS, commit=True) == BIRDS[0]
