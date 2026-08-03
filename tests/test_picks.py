"""A bird holds its artwork for as long as it is in the window: the churn this
replaced re-rolled every bird whenever the species set shifted or the service
restarted."""

from __future__ import annotations

import json

import pytest

from fugleramme.picks import Picks


@pytest.fixture
def variants(tmp_path):
    folder = tmp_path / "classic"
    folder.mkdir()
    paths = []
    for n in range(1, 6):
        path = folder / (f"turdus-merula-{n}.png" if n > 1 else "turdus-merula.png")
        path.write_bytes(b"x")
        paths.append(path)
    return paths


def test_a_pick_is_held_across_calls(tmp_path, variants):
    picks = Picks(tmp_path / "artwork.json")
    first = picks.choose("Turdus merula", variants)
    assert all(picks.choose("Turdus merula", variants) == first for _ in range(20))


def test_a_pick_survives_a_restart(tmp_path, variants):
    path = tmp_path / "artwork.json"
    first = Picks(path).choose("Turdus merula", variants)
    assert Picks(path).choose("Turdus merula", variants) == first
    assert json.loads(path.read_text()) == {"Turdus merula": first.name}


def test_leaving_the_window_rolls_again(tmp_path, variants):
    picks = Picks(tmp_path / "artwork.json")
    seen = set()
    for _ in range(60):
        seen.add(picks.choose("Turdus merula", variants).name)
        picks.retain(["Corvus corax"])  # our bird is gone, so its pick is forgotten
    assert len(seen) > 1  # 1 in 5**60 says otherwise


def test_retain_keeps_the_species_still_present(tmp_path, variants):
    picks = Picks(tmp_path / "artwork.json")
    first = picks.choose("Turdus merula", variants)
    picks.retain(["Turdus merula", "Corvus corax"])
    assert picks.choose("Turdus merula", variants) == first


def test_a_pick_that_is_no_longer_on_disk_rolls_again(tmp_path, variants):
    # Re-curation drops a variant, or the style is switched out from under it.
    picks = Picks(tmp_path / "artwork.json")
    picks.choose("Turdus merula", variants)
    only = [variants[-1]]
    assert picks.choose("Turdus merula", only) == only[0]


def test_no_artwork_is_not_a_pick(tmp_path):
    picks = Picks(tmp_path / "artwork.json")
    assert picks.choose("Turdus merula", []) is None
    assert not (tmp_path / "artwork.json").exists()


def test_a_corrupt_file_is_not_fatal(tmp_path, variants):
    path = tmp_path / "artwork.json"
    path.write_text("{not json")
    assert Picks(path).choose("Turdus merula", variants) in variants
