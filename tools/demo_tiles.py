"""Build demo mode's tiles from two GBIF SQL downloads (#358).

    uv run python tools/demo_tiles.py BIRDS.zip TOTALS.zip --out detector/data/demo

BIRDS has one row per cell, eBird name and month: `cell`, `name` (verbatim
scientific name), `month`, `checklists` (distinct eventIds reporting it).
TOTALS has one row per cell and month: `cell`, `month`, `checklists`. Both are
EQDGC cells at `demo.DEEPEST`, birds only, CC0 and CC BY only.

The cells form a quadtree, since a code's parent is the code less its last
letter: every level is the sum of the one below. A cell is kept while it has
`KEEP` checklists over the year, so dense areas keep small cells and sparse ones
fall back to a coarser one; `demo.DemoSource` takes the longest code it finds.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import io
import json
import zipfile
from collections import defaultdict
from pathlib import Path

from fugleramme.demo import DEEPEST, tile_name
from fugleramme.names import canonical
from fugleramme.taxa import LABELS, is_bird

# A cell with fewer checklists than this over the year is too thin to stand alone.
KEEP = 200
# A bird on fewer of a cell's checklists than this over the year is left out.
LEAST = 3
# eBird splits since BirdNET v2.4's labels, under the label each was split from.
SPLITS = {
    "Setophaga aestiva": "Setophaga petechia",
    "Vireo swainsoni": "Vireo gilvus",
    "Larus smithsonianus": "Larus argentatus",
    "Astur atricapillus": "Accipiter gentilis",
    "Tyto furcata": "Tyto alba",
    "Melanitta deglandi": "Melanitta fusca",
    "Numenius hudsonicus": "Numenius phaeopus",
}

csv.field_size_limit(1 << 30)


def _rows(path: Path):
    with zipfile.ZipFile(path) as z, z.open(z.namelist()[0]) as raw:
        reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8"), delimiter="\t")
        yield from ({k.lower(): v for k, v in row.items()} for row in reader)


def _labels() -> dict[str, str]:
    """Lowercased spelling -> current name, for every bird BirdNET v2.4 names."""
    names = (line.split("_", 1)[0] for line in LABELS.read_text().splitlines() if "_" in line)
    return {
        spelling.lower(): canonical(sci)
        for sci in names
        if is_bird(sci)
        for spelling in (sci, canonical(sci))
    }


def _name(verbatim: str, known: dict[str, str]) -> str | None:
    binomial = " ".join(verbatim.split()[:2])  # a subspecies counts as its species
    return known.get(SPLITS.get(binomial, binomial).lower())


def _corner(code: str) -> tuple[float, float]:
    """A point inside a cell's 1° parent, to find its tile by."""
    lon, lat = int(code[1:4]), int(code[5:7])
    return (
        lat + 0.5 if code[4] == "N" else -lat - 0.5,
        lon + 0.5 if code[0] == "E" else -lon - 0.5,
    )


def build(birds_zip: Path, totals_zip: Path) -> dict[str, dict]:
    known = _labels()
    totals: dict[str, list[int]] = defaultdict(lambda: [0] * 12)
    for row in _rows(totals_zip):
        code, month, n = row["cell"], int(row["month"]) - 1, int(row["checklists"])
        for level in range(DEEPEST + 1):
            totals[code[: len(code) - level]][month] += n

    birds: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(lambda: [0] * 12))
    for row in _rows(birds_zip):
        name = _name(row["name"], known)
        if name is None:
            continue
        code, month, n = row["cell"], int(row["month"]) - 1, int(row["checklists"])
        for level in range(DEEPEST + 1):
            birds[code[: len(code) - level]][name][month] += n

    tiles: dict[str, dict] = defaultdict(lambda: {"names": [], "cells": {}})
    index: dict[str, dict[str, int]] = defaultdict(dict)
    for code in sorted(totals):
        if sum(totals[code]) < KEEP:
            continue
        tile = tile_name(*_corner(code))
        names, at = tiles[tile]["names"], index[tile]
        kept = []
        for name, months in sorted(birds[code].items()):
            if sum(months) < LEAST:
                continue
            if name not in at:
                at[name] = len(names)
                names.append(name)
            kept.append([at[name], months])
        tiles[tile]["cells"][code] = {"checklists": totals[code], "birds": kept}
    return dict(tiles)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("birds", type=Path)
    parser.add_argument("totals", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    for name, tile in build(args.birds, args.totals).items():
        body = gzip.compress(json.dumps(tile, separators=(",", ":")).encode(), mtime=0)
        (args.out / f"{name}.json.gz").write_bytes(body)
        print(
            f"{name}: {len(tile['cells'])} cells, {len(tile['names'])} birds, {len(body) / 1e3:.0f} KB"
        )


if __name__ == "__main__":
    main()
