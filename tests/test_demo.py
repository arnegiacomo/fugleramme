"""Demo mode: made-up birds from a tile of GBIF checklists (#358)."""

from __future__ import annotations

import gzip
import json
from pathlib import Path

import pytest

from fugleramme import check, demo
from fugleramme.api import Configured
from fugleramme.demo import DemoSource, cell_code, tile_name, tile_path
from fugleramme.settings import Settings, SettingsStore, merged

FOOTHILLS = (43.665, -116.180)
# On every checklist, on a tenth, and on too few to be more than a stray.
COMMON, SOMETIMES, STRAY = "Pica hudsonia", "Junco hyemalis", "Turdus migratorius"


def _tile(data_dir: Path, lat: float, lon: float, cells: dict) -> None:
    names = [COMMON, SOMETIMES, STRAY]
    path = tile_path(data_dir, lat, lon)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(gzip.compress(json.dumps({"names": names, "cells": cells}).encode()))


def _cell(checklists: int, birds: list[tuple[int, int]]) -> dict:
    return {
        "checklists": [checklists] * 12,
        "birds": [[index, [n] * 12] for index, n in birds],
    }


def test_the_cell_code_names_the_quadrant_at_each_level():
    # A north-west, B north-east, C south-west, D south-east, as GBIF's EQDGC.
    assert [cell_code(*FOOTHILLS, level) for level in range(4)] == [
        "W116N43",
        "W116N43B",
        "W116N43BD",
        "W116N43BDA",
    ]
    # Sydney, south and east of zero: 33.87°S is in the southern half of 33-34°S.
    assert cell_code(-33.87, 151.21, 1) == "E151S33C"


def test_the_tile_is_named_by_its_south_west_corner():
    assert tile_name(*FOOTHILLS) == "N40W120"
    assert tile_name(-33.87, 151.21) == "S40E150"


def test_birds_come_from_the_longest_code_the_tile_has(tmp_path):
    _tile(
        tmp_path,
        *FOOTHILLS,
        {
            "W116N43": _cell(1000, [(1, 900)]),
            "W116N43BD": _cell(1000, [(0, 1000), (1, 100), (2, 5)]),
        },
    )
    source = DemoSource(*FOOTHILLS, tmp_path)
    heard = {d.scientific_name for d in source.recent(500)}
    assert heard == {COMMON, SOMETIMES}  # the 1° cell's junco-only list is not read


def test_a_thin_month_reads_the_whole_year(tmp_path):
    cell = _cell(1000, [(0, 500)])
    cell["checklists"][0] = demo.THIN_MONTH - 1
    cell["birds"][0][1][0] = 0
    _tile(tmp_path, *FOOTHILLS, {"W116N43BDA": cell})
    birds, _ = DemoSource(*FOOTHILLS, tmp_path)._by_month[0]
    assert birds == (COMMON,)


def test_the_same_place_and_hour_hear_the_same_birds(tmp_path):
    _tile(tmp_path, *FOOTHILLS, {"W116N43": _cell(1000, [(0, 500), (1, 500)])})
    assert DemoSource(*FOOTHILLS, tmp_path).recent(50) == DemoSource(*FOOTHILLS, tmp_path).recent(
        50
    )


@pytest.mark.parametrize("place", [(None, None), FOOTHILLS])
def test_without_a_location_or_a_tile_any_bird_with_artwork_turns_up(tmp_path, place):
    source = DemoSource(*place, tmp_path)
    heard = source.recent(500)
    assert heard
    assert {d.scientific_name for d in heard} <= set(demo.drawable())


def test_the_life_list_dates_each_bird_to_its_first_detection(tmp_path):
    source = DemoSource(None, None, tmp_path)
    life = source.life_list()
    first = {s.scientific_name: s.first_seen for s in life}
    for d in source._heard():
        assert first[d.scientific_name] <= d.detected_at
    assert [s.first_seen for s in life] == sorted(s.first_seen for s in life)


def test_names_are_english_off_the_labels(tmp_path):
    names = DemoSource(None, None, tmp_path).common_names()
    assert names["en"]["Pica hudsonia"] == "Black-billed Magpie"


def test_the_location_is_kept_only_inside_the_globe():
    settings = merged(Settings(), demo_latitude="43.665", demo_longitude="-116.18")
    assert (settings.demo_latitude, settings.demo_longitude) == (43.665, -116.18)
    off = merged(Settings(), demo_latitude=91, demo_longitude="east")
    assert (off.demo_latitude, off.demo_longitude) == (None, None)


def test_the_check_reads_a_demo_without_reaching_anything(tmp_path, capsys):
    assert check.run_demo(DemoSource(None, None, tmp_path), tmp_path) == 0
    assert "all good" in capsys.readouterr().out


def test_configured_builds_the_demo_from_the_settings(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps({"detector_kind": "demo", "demo_latitude": 43.665, "demo_longitude": -116.18})
    )
    source = Configured(SettingsStore(path)).source
    assert isinstance(source, DemoSource)
    assert source.base_url == "demo:43.665,-116.180"
