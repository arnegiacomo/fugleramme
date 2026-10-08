"""The docs' species list covers every bird label and every shipped plate."""

import importlib.util
import json
import re
from pathlib import Path

from fugleramme.names import BIRDS, SUFFIXES, normalize

REPO = Path(__file__).resolve().parents[1]
ARTWORK = REPO / "assets" / "artwork"

spec = importlib.util.spec_from_file_location("species", REPO / "hooks" / "species.py")
assert spec and spec.loader
species = importlib.util.module_from_spec(spec)
spec.loader.exec_module(species)


def _shipped() -> set[str]:
    stems = {
        re.sub(r"-\d+$", "", path.stem)
        for style in ARTWORK.iterdir()
        if (style / BIRDS).is_dir()
        for suffix in SUFFIXES
        for path in (style / BIRDS).glob(f"*{suffix}")
    }
    return {stem for stem in stems if "-x-" not in stem}


def test_every_shipped_plate_is_counted_once():
    rows = species.rows()
    by_key = {normalize(str(row["name"])): row for row in rows}
    assert len(by_key) == len(rows)
    for stem in _shipped():
        assert by_key[stem]["plates"], stem
    assert sum(len(row["plates"]) for row in rows) == sum(
        1
        for style in ARTWORK.iterdir()
        if (style / BIRDS).is_dir()
        for suffix in SUFFIXES
        for path in (style / BIRDS).glob(f"*{suffix}")
        if "-x-" not in path.stem
    )


def test_reclassified_bird_is_one_row_with_both_names():
    rows = {row["name"]: row for row in species.rows()}
    assert "Corvus monedula" not in rows
    assert rows["Coloeus monedula"]["label"] == "Corvus monedula"


def test_art_without_a_label_is_marked_undetectable():
    rows = {row["name"]: row for row in species.rows()}
    assert rows["Alle alle"]["detectable"] is False
    assert "detectable" not in rows["Turdus merula"]


def test_badge_species_count_matches_the_page():
    spec = importlib.util.spec_from_file_location("badges", REPO / "hooks" / "badges.py")
    assert spec and spec.loader
    badges = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(badges)
    with_art = sum(1 for row in species.rows() if row["plates"])
    assert badges.counts()["species"] == str(with_art)


def test_every_country_on_the_map_is_one_gbif_files_records_under():
    svg = (REPO / "docs" / "assets" / "world.svg").read_text()
    drawn = set(re.findall(r'data-iso="([^"]+)"', svg))
    assert drawn <= set(json.loads(species.SNAPSHOT.read_text())["countries"])


def test_coverage_counts_art_from_the_tree_against_the_snapshot():
    listed = species.rows()
    norway = species.coverage(listed)["countries"]["NO"]
    records = json.loads(species.SNAPSHOT.read_text())["countries"]["NO"]["records"]
    rows = {str(row["name"]): row for row in listed}
    assert records["Turdus merula"] and rows["Turdus merula"]["plates"]
    assert 0 < norway["art"] <= norway["species"]
    assert 0 < norway["drawn"] <= norway["records"]
