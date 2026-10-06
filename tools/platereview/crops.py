"""Build the data a crop preview runs on: each whole scan with the crop proposed for it.

    python crops.py DIR        every bird listed in DIR/crops.json
    python crops.py DIR junco  only ids containing "junco" (the rest keep their old images)

DIR/crops.json in, DIR/crops.js and DIR/img/ out. Each entry names an `id`, a `name`, the
bird's `spec` and optionally a `url` - the full-resolution scan itself, not the page it sits
on. A spec whose `scan` is not on disk yet is downloaded from `url` to that path, so
`plate.py crop` finds it there afterwards.

The page is `crop.html` beside this file and is never generated. It shows the whole scan
with the spec's `box` on it; a person drags the box to where it belongs, says why, and
"Copy crop notes" hands both back for the spec. Nothing here edits a spec.

Several entries may share a scan - a page with more than one crop on it. The scan
is written once, as img/<id>/full.jpg under the first of them, at its own pixel count.
"""

import json
import shutil
import sys
import urllib.request
from pathlib import Path
from typing import Any

from PIL import Image
from plate import WORK

Image.MAX_IMAGE_PIXELS = None
HERE = Path(__file__).resolve().parent
AGENT = "fugleramme-platereview (https://github.com/arnegiacomo/fugleramme)"


def read_crops(path: Path) -> list[dict[str, Any]]:
    """The crops a previous run wrote, so rebuilding one bird leaves the rest alone."""
    if not path.exists():
        return []
    body = path.read_text().partition("=")[2].rstrip().rstrip(";")
    return list(json.loads(body))


def download(url: str, to: Path) -> None:
    # Wikimedia and the Internet Archive both refuse urllib's default agent
    request = urllib.request.Request(url, headers={"User-Agent": AGENT})
    to.parent.mkdir(parents=True, exist_ok=True)
    part = to.with_name(to.name + ".part")  # a broken download must not pass for the scan
    with urllib.request.urlopen(request, timeout=120) as response, part.open("wb") as out:
        shutil.copyfileobj(response, out)
    part.replace(to)
    print(f"downloaded {to}  {to.stat().st_size // 1024} KB")


def scan_of(bird: dict[str, Any]) -> str:
    return str(json.loads(Path(bird["spec"]).read_text())["scan"])


def build(bird: dict[str, Any], work: Path, owner: str) -> dict[str, Any]:
    """One crop. `owner` is the first bird in crops.json cut from the same scan: a plate
    with several birds on it is written once, under that id, and the page groups by it."""
    key, spec_path = bird["id"], Path(bird["spec"])
    spec = json.loads(spec_path.read_text())
    scan_path = Path(spec["scan"])
    if not scan_path.exists():
        if "url" not in bird:
            raise SystemExit(f"{key}: {scan_path} is missing and crops.json gives no url for it")
        download(bird["url"], scan_path)

    full = work / "img" / owner / "full.jpg"
    scan = Image.open(scan_path)
    if key == owner or not full.exists():
        full.parent.mkdir(parents=True, exist_ok=True)
        if scan.format == "JPEG":  # already what a browser reads: no need to re-encode it
            shutil.copy(scan_path, full)
        else:
            scan.convert("RGB").save(full, quality=92)

    # the seed is in crop px, and plate.py shrinks a crop longer than WORK: put it back on the
    # scan, so the page can draw it and say where it lands once the box has moved
    x0, y0, x1, y1 = spec["box"]
    scale = min(1.0, WORK / max(x1 - x0, y1 - y0))
    seed = spec.get("seed")
    print(f"{key:14} {scan.width}x{scan.height}  box {spec['box']}")
    return {
        "id": key,
        "name": bird["name"],
        "spec": spec_path.as_posix(),
        "scan": scan_path.as_posix(),
        "full": f"img/{owner}/full.jpg",
        "url": bird.get("url", ""),
        "w": scan.width,
        "h": scan.height,
        "box": [x0, y0, x1, y1],
        "seed": seed and [round(x0 + seed[0] / scale, 1), round(y0 + seed[1] / scale, 1)],
        "work": WORK,
    }


if __name__ == "__main__":
    work, wanted = Path(sys.argv[1]).resolve(), sys.argv[2:]
    data_path = work / "crops.js"
    known = {c["id"]: c for c in read_crops(data_path)}
    crops = json.loads((work / "crops.json").read_text())
    owners: dict[str, str] = {}
    for bird in crops:
        owner = owners.setdefault(scan_of(bird), bird["id"])
        if not wanted or any(w in bird["id"] for w in wanted):
            known[bird["id"]] = build(bird, work, owner)
    ordered = [known[c["id"]] for c in crops if c["id"] in known]
    # A script tag, not JSON, for the same reason as birds.js: the page opens off file://
    data_path.write_text(f"window.CROPS = {json.dumps(ordered, indent=1)};\n")
    if not (work / "crop.html").exists():
        shutil.copy(HERE / "crop.html", work / "crop.html")
    print("wrote", data_path)
