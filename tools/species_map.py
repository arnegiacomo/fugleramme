"""Fetch what the species page's world map is drawn from.

    uv run python tools/species_map.py           # both
    uv run python tools/species_map.py --shapes  # the outline only
    uv run python tools/species_map.py --gbif    # the records only

Writes two files, both committed:

- `docs/assets/world.svg`: one `<path data-iso>` per ISO 3166 code, Equal Earth
  projected. Drawn from Natural Earth's map subunits, not its countries, since
  those split off the overseas parts GBIF files under their own code, like
  French Guiana or Svalbard. Antarctica is left out: no frame hangs there.
- `hooks/species_by_country.json`: per country, the birds GBIF has regular
  records of, asked as `docs/assets/species.js` asks, so the map and the page
  agree. It keeps only the birds BirdNET can name, with counts to two
  significant figures: the map only reads shares, and a refresh then rewrites
  only the counts that moved. The art is joined at build time, so a new plate
  needs no refetch. Run `--gbif` a couple of times a year and after updating
  the label list or the alias map, then commit.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

from fugleramme.names import canonical
from fugleramme.taxa import LABELS, is_bird

REPO = Path(__file__).resolve().parents[1]
SVG = REPO / "docs" / "assets" / "world.svg"
SNAPSHOT = REPO / "hooks" / "species_by_country.json"

SUBUNITS = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/v5.1.2/geojson/ne_50m_admin_0_map_subunits.geojson"
GBIF = "https://api.gbif.org/v1"

WIDTH = 1000
TOLERANCE = 0.35  # px: below what the map is ever drawn at
DOT = 4.0  # px: a country smaller than this also gets a dot to hover
# Natural Earth leaves these uncoded; GBIF files them under these countries.
UNCODED = {"Somaliland": "SO", "Northern Cyprus": "CY", "Crimea": "UA"}
LEFT_OUT = {"AQ", "-99"}

REGULAR = 25  # the page's vagrant floor: records in a decade
FACET = 1200


Point = tuple[float, float]


def _project(lon: float, lat: float) -> Point:
    """Equal Earth (Šavrič, Patterson, Jenny 2018), scaled to WIDTH, y down."""
    a1, a2, a3, a4 = 1.340264, -0.081106, 0.000893, 0.003796
    m = math.sqrt(3) / 2
    theta = math.asin(m * math.sin(math.radians(lat)))
    t2, t6 = theta**2, theta**6
    x = math.radians(lon) * math.cos(theta) / (m * (a1 + 3 * a2 * t2 + t6 * (7 * a3 + 9 * a4 * t2)))
    y = theta * (a1 + a2 * t2 + t6 * (a3 + a4 * t2))
    scale = WIDTH / (2 * 2.70646)
    return (x * scale + WIDTH / 2, -y * scale)


def _simplify(points: list[Point]) -> list[Point]:
    """Ramer-Douglas-Peucker."""
    if len(points) < 3:
        return points
    (x0, y0), (x1, y1) = points[0], points[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = math.hypot(dx, dy) or 1.0
    far, index = 0.0, 0
    for i, (x, y) in enumerate(points[1:-1], 1):
        d = abs(dy * (x - x0) - dx * (y - y0)) / norm if (dx or dy) else math.hypot(x - x0, y - y0)
        if d > far:
            far, index = d, i
    if far <= TOLERANCE:
        return [points[0], points[-1]]
    return _simplify(points[: index + 1])[:-1] + _simplify(points[index:])


def _ring(coordinates: list[list[float]]) -> str:
    # A closed ring simplifies to its two equal ends, so split it at the far point first.
    points = [_project(lon, lat) for lon, lat in coordinates]
    far = max(range(len(points)), key=lambda i: math.dist(points[0], points[i]))
    kept = _simplify(points[: far + 1])[:-1] + _simplify(points[far:])
    if len(kept) < 4:
        return ""
    return "M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in kept[:-1]) + "Z"


def _code(properties: dict) -> str:
    code = properties["ISO_A2_EH"]
    return UNCODED.get(properties["SUBUNIT"], code) if code == "-99" else code


def shapes() -> str:
    with urllib.request.urlopen(SUBUNITS) as response:
        features = json.load(response)["features"]
    polygons: dict[str, list[list[list[list[float]]]]] = {}
    for feature in features:
        code = _code(feature["properties"])
        if code in LEFT_OUT:
            continue
        geometry = feature["geometry"]
        parts = (
            geometry["coordinates"]
            if geometry["type"] == "MultiPolygon"
            else [geometry["coordinates"]]
        )
        polygons.setdefault(code, []).extend(parts)

    top = _project(0, 90)[1]
    bottom = _project(0, -60)[1]  # south of every continent but Antarctica
    paths = []
    for code, parts in sorted(polygons.items()):
        rings = [ring for part in parts for ring in part]
        d = "".join(_ring(ring) for ring in rings)
        projected = [_project(lon, lat) for ring in rings for lon, lat in ring]
        xs, ys = [p[0] for p in projected], [p[1] for p in projected]
        if max(max(xs) - min(xs), max(ys) - min(ys)) < DOT:
            biggest = [_project(lon, lat) for lon, lat in max((part[0] for part in parts), key=len)]
            cx = sum(x for x, _ in biggest) / len(biggest)
            cy = sum(y for _, y in biggest) / len(biggest)
            dot = f'<circle data-iso="{code}" class="dot" cx="{cx:.1f}" cy="{cy:.1f}" r="2.5"/>'
            paths.append((f'<path data-iso="{code}" d="{d}"/>' if d else "") + dot)
        elif d:
            paths.append(f'<path data-iso="{code}" d="{d}"/>')
    height = bottom - top
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {top:.0f} {WIDTH} {height:.0f}">\n'
        + "\n".join(paths)
        + "\n</svg>\n"
    )


def _get(path: str, params: dict[str, object], wait: int = 5) -> dict:
    url = f"{GBIF}/{path}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=120) as response:
            return json.load(response)
    except (urllib.error.URLError, TimeoutError) as error:
        # A burst gets a 429, and the odd query times out outright.
        refused = (
            isinstance(error, urllib.error.HTTPError) and error.code < 500 and error.code != 429
        )
        if refused or wait > 200:
            raise
        print(f"GBIF: {error}, retrying in {wait}s")
        time.sleep(wait)
        return _get(path, params, wait * 3)


def _records(iso2: str, years: str) -> dict[str, int]:
    """Binomial -> records in the country. Mirrors species.js's `recorded`."""
    counts: dict[str, int] = {}
    for offset in range(0, 3 * FACET, FACET):
        page = _get(
            "occurrence/search",
            {
                "taxonKey": 212,
                "facet": "scientificName",
                "facetLimit": FACET,
                "facetOffset": offset,
                "facetMincount": REGULAR,
                "limit": 0,
                "occurrenceStatus": "PRESENT",
                "basisOfRecord": "HUMAN_OBSERVATION",
                "hasCoordinate": "true",
                "year": years,
                "country": iso2,
            },
        )
        values = page["facets"][0]["counts"] if page.get("facets") else []
        for value in values:
            name = value["name"]
            binomial = re.match(r"^[A-Z][a-z]+ [a-z-]+", name)
            if binomial and not re.search(r" x |×", name):
                counts[binomial[0]] = counts.get(binomial[0], 0) + value["count"]
        if len(values) < FACET:
            break
    return dict(sorted(counts.items(), key=lambda item: -item[1]))


def _detectable() -> set[str]:
    """Every spelling `hooks/species.py` joins a bird by."""
    labels = (line.split("_", 1)[0] for line in LABELS.read_text().splitlines() if "_" in line)
    return {name.lower() for sci in labels if is_bird(sci) for name in (sci, canonical(sci))}


def gbif() -> str:
    year = datetime.now(UTC).year
    years = f"{year - 9},{year}"
    countries = _get("enumeration/country", {})
    # One at a time: GBIF answers each in about a second and turns away a crowd.
    records = [_records(row["iso2"], years) for row in countries]
    detectable = _detectable()
    kept = [
        {
            binomial: int(float(f"{count:.2g}"))
            for binomial, count in counts.items()
            if binomial.lower() in detectable
        }
        for counts in records
    ]
    # One country a line, so a refresh diffs by country. Empty countries stay, so a
    # test can hold the map's codes to GBIF's.
    lines = [
        f'  "{row["iso2"]}": {json.dumps({"name": row["title"], "records": counts}, ensure_ascii=False)}'
        for row, counts in zip(countries, kept, strict=True)
    ]
    head = {"fetched": datetime.now(UTC).date().isoformat(), "years": years}
    return json.dumps(head)[:-1] + ', "countries": {\n' + ",\n".join(sorted(lines)) + "\n}}\n"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--shapes", action="store_true", help="only the outline")
    parser.add_argument("--gbif", action="store_true", help="only the records")
    args = parser.parse_args()
    both = not (args.shapes or args.gbif)
    if both or args.shapes:
        SVG.write_text(shapes())
        print(f"{SVG.relative_to(REPO)}: {SVG.stat().st_size // 1024} KB")
    if both or args.gbif:
        SNAPSHOT.write_text(gbif())
        print(f"{SNAPSHOT.relative_to(REPO)}: {SNAPSHOT.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
