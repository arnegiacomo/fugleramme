"""Publish the species list as `species.json` beside the docs.

The species page's search box reads it: one row per bird BirdNET v2.4 can
report, with the plate count the artwork tree holds for it, so the list is
built from the repo at build time rather than kept by hand. Rows are keyed
through `normalize`, so a reclassified bird is one row under its current name
with the label's spelling beside it. Plates for a bird v2.4 has no label for
are listed too, marked undetectable, and hybrids are left out since BirdNET
never emits one.

`coverage.json` beside it holds the world map's numbers: per country, how many
of the birds GBIF regularly records have art, and their share of the records.
The birds come from `tools/species_map.py`'s snapshot and the art from the
tree, so a new plate needs no refetch.
"""

import json
import re
from pathlib import Path

from fugleramme.names import BIRDS, artwork_in, canonical, normalize
from fugleramme.taxa import LABELS, is_bird

REPO = Path(__file__).resolve().parents[1]
ARTWORK = REPO / "assets" / "artwork"
OUT = "species.json"
SNAPSHOT = Path(__file__).with_name("species_by_country.json")


def _plates() -> dict[str, list[str]]:
    """Species key -> shipped plates across every style, as paths under
    `assets/artwork/` so the page can link each file."""
    plates: dict[str, list[str]] = {}
    for style in ARTWORK.iterdir():
        for path in artwork_in(style / BIRDS):
            key = re.sub(r"-\d+$", "", path.stem)
            if "-x-" not in key:
                plates.setdefault(key, []).append(path.relative_to(ARTWORK).as_posix())
    # "<key>.webp" first, then -2, -3: a path sort would put the variants before it
    return {key: sorted(files, key=len) for key, files in plates.items()}


def _labels() -> list[tuple[str, str]]:
    """(scientific, common) for every bird label."""
    rows = (line.split("_", 1) for line in LABELS.read_text().splitlines() if "_" in line)
    return [(sci, common) for sci, common in rows if is_bird(sci)]


def rows() -> list[dict[str, object]]:
    plates = _plates()
    listed: dict[str, dict[str, object]] = {}
    for sci, common in _labels():
        key = normalize(sci)
        row = listed.setdefault(
            key, {"name": canonical(sci), "common": common, "plates": plates.pop(key, [])}
        )
        if sci == row["name"]:
            row["common"] = common  # the label under the current name wins
        else:  # an older spelling, or a second label since lumped into this one
            row["label"] = f"{row['label']}, {sci}" if "label" in row else sci
    for key, files in plates.items():  # art for a bird no label names
        name = key.replace("-", " ").capitalize()
        listed[key] = {"name": name, "common": "", "plates": files, "detectable": False}
    return sorted(listed.values(), key=lambda row: str(row["name"]))


def coverage(listed: list[dict[str, object]]) -> dict[str, object]:
    """Joined by name and label spellings, detectable rows only, as species.js
    joins a country, so the map and the page's summary line agree."""
    by_key: dict[str, dict[str, object]] = {}
    for row in listed:
        if row.get("detectable") is False:
            continue
        for name in [str(row["name"]), *filter(None, str(row.get("label", "")).split(", "))]:
            by_key[name.lower()] = row
    snapshot = json.loads(SNAPSHOT.read_text())
    countries = {}
    for code, country in snapshot["countries"].items():
        here: dict[str, int] = {}
        for binomial, count in country["records"].items():
            match = by_key.get(binomial.lower())
            if match:
                here[str(match["name"])] = here.get(str(match["name"]), 0) + count
        drawn = [name for name in here if by_key[name.lower()]["plates"]]
        countries[code] = {
            "name": country["name"],
            "species": len(here),
            "art": len(drawn),
            "records": sum(here.values()),
            "drawn": sum(here[name] for name in drawn),
        }
    return {"fetched": snapshot["fetched"], "years": snapshot["years"], "countries": countries}


def on_post_build(config, **_) -> None:
    listed = rows()
    site = Path(config["site_dir"])
    (site / OUT).write_text(json.dumps(listed, ensure_ascii=False))
    (site / "coverage.json").write_text(json.dumps(coverage(listed), ensure_ascii=False))
