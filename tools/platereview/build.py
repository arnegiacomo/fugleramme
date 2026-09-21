"""Build the data a plate review runs on: every shipped cut-out beside the scan it came from.

    python build.py            every plate listed in plates.json
    python build.py junco      only ids containing "junco" (the rest keep their old images)
    python build.py DIR [ids]  the same, for a review folder elsewhere: DIR/plates.json in,
                               DIR/birds.js and DIR/img/ out

The page itself is `index.html` beside this file and is never generated: a review folder
holds only what its plates differ in. Copy or symlink the page next to the folder's
`birds.js` and open it.

For each plate it writes four aligned layers into img/<id>/:

    scan.jpg    the scan crop, untouched
    plate.jpg   the shipped WebP on the frame's own paper, through the frame's own
                halo treatment (fugleramme.render.paper), as it will print
    flags.jpg   plate.jpg with suspect pixels in red
    diff.jpg    plate.jpg with every pixel that no longer matches the scan in red, and the
                scan washed blue wherever ink was cut away

A suspect pixel is flat halo-toned paper where the bird should be: either deeper
inside the cut-out than the halo reaches, or lying over scan pixels that carry a
tint (a cream bill, a buff flank). Deliberate gaps between legs and perch flag too;
the page is there so a person decides. Zoom windows are the places with the most
suspect pixels and the most pale plumage.

Run with a Python that can import fugleramme (any worktree's .venv).
"""

import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageFilter

from fugleramme.render.paper import PAD, paper_texture, process_sprite

Image.MAX_IMAGE_PIXELS = None
HERE = Path(__file__).resolve().parent
WORK = HERE
PAPER = np.array([0xF0, 0xEC, 0xE5])
MARGIN = 40  # px of page round the plate
HALO = 17  # px, the halo a plate ships with at 1200
WINDOW = (240, 180)  # zoom window, px of the plate
ZOOMS = 6
EDGE = 90  # px from the silhouette that still counts as its edge
DIFF = 40  # levels a pixel may drift through resizing and WebP before it counts as changed
PAPER_LIKE = 228  # min channel above which a scan pixel is paper


def read_birds(path: Path) -> list[dict[str, Any]]:
    """The birds a previous run wrote, so rebuilding one plate leaves the rest alone."""
    if not path.exists():
        return []
    body = path.read_text().partition("=")[2].rstrip().rstrip(";")
    return list(json.loads(body))


def box_sum(a, w, h):
    """Sum of a over every w x h window, by its top-left corner."""
    c = np.pad(a.astype(np.int64), ((1, 0), (1, 0))).cumsum(0).cumsum(1)
    return c[h:, w:] - c[:-h, w:] - c[h:, :-w] + c[:-h, :-w]


def erode(mask, r):
    """The pixels of a boolean mask at least r px from anything outside it, by running
    sums over a square: Pillow's MinFilter takes minutes at the sizes used here."""
    padded = np.pad(~mask, r, constant_values=True)
    return box_sum(padded, 2 * r + 1, 2 * r + 1) == 0


def windows(score, size, count, floor):
    """The highest-scoring windows that do not overlap much."""
    w, h = size
    sums = box_sum(score, w, h).astype(float)
    picked: list[list[int]] = []
    while len(picked) < count and sums.size:
        y, x = np.unravel_index(sums.argmax(), sums.shape)
        if sums[y, x] < floor:
            break
        picked.append([int(x), int(y), w, h])
        sums[max(0, y - h * 2 // 3) : y + h * 2 // 3, max(0, x - w * 2 // 3) : x + w * 2 // 3] = -1
    return picked


def build(bird):
    key, name, pr = bird["id"], bird["name"], bird.get("pr", "")
    plate_path = Path(bird["plate"])
    style, stem = plate_path.parent.parent, plate_path.stem
    plate = Image.open(plate_path).convert("RGBA")
    manifest = style / "manifest.json"
    entry = (
        json.loads(manifest.read_text()).get(f"birds/{plate_path.name}", {})
        if manifest.exists()
        else {}
    )

    scan, cut = Image.open(bird["scan"]).convert("RGB"), Image.open(bird["cut"]).convert("RGBA")
    assert scan.size == cut.size, (key, scan.size, cut.size)
    alpha = np.asarray(cut)[..., 3]
    rows, cols = np.flatnonzero(alpha.any(1)), np.flatnonzero(alpha.any(0))
    x0, y0, x1, y1 = cols[0], rows[0], cols[-1] + 1, rows[-1] + 1
    f = plate.width / (x1 - x0)  # plate px per scan-crop px
    m = MARGIN / f
    W, H = plate.width + 2 * MARGIN, plate.height + 2 * MARGIN

    # the scan, on the same canvas as the plate; white beyond the crop's own edge
    grown = Image.new("RGB", (scan.width + 400, scan.height + 400), (255, 255, 255))
    grown.paste(scan, (200, 200))
    region = (x0 - m + 200, y0 - m + 200, x1 + m + 200, y1 + m + 200)
    scan_layer = grown.resize((W, H), Image.Resampling.LANCZOS, box=region)

    # does the scratch cut-out still match what shipped?
    derived = (
        np.asarray(cut.crop((x0, y0, x1, y1)).resize(plate.size, Image.Resampling.LANCZOS))[..., 3]
        > 128
    )
    shipped = np.asarray(plate)[..., 3] > 128
    match = int((derived & shipped).sum()) / max(1, int((derived | shipped).sum()))

    # the plate as the frame prints it
    page = paper_texture(W, H).convert("RGB")
    origin = (MARGIN - PAD, MARGIN - PAD)
    sprite = process_sprite(plate, origin)
    page.paste(sprite, origin, sprite)

    # suspect pixels, on the canvas
    raw = np.zeros((H, W, 4), np.int16)
    raw[MARGIN : MARGIN + plate.height, MARGIN : MARGIN + plate.width] = np.asarray(plate)
    solid = raw[..., 3] > 250
    inner = erode(solid, HALO + 4)
    flat = (raw[..., 3] > 250) & (np.abs(raw[..., :3] - PAPER).max(2) <= 4)
    s = np.asarray(scan_layer).astype(np.int16)
    tinted = (s.min(2) > 205) & (s.max(2) - s.min(2) > 12)
    suspect = flat & (inner | tinted)
    # drop specks: an anti-aliased feather edge passes through the paper tone for a pixel or two
    speckless = Image.fromarray((suspect * 255).astype(np.uint8), "L").filter(
        ImageFilter.MinFilter(3)
    )
    suspect = np.asarray(speckless.filter(ImageFilter.MaxFilter(3))) > 0
    # pale plumage near the silhouette is where a leak can start; white deep inside cannot leak
    deep = erode(solid, EDGE)
    pale = inner & ~deep & (s.min(2) > 228)

    # the ring: dark colour under a soft edge the frame still draws (alpha 25-254)
    ring = (raw[..., 3] >= 25) & (raw[..., 3] < 255) & (raw[..., :3].max(2) < 200)
    fat = (
        np.asarray(
            Image.fromarray((ring * 255).astype(np.uint8), "L").filter(ImageFilter.MaxFilter(5))
        )
        > 0
    )

    # the difference layer: the plate where it still matches the scan, red where it does not,
    # and the scan washed blue where ink was cut away
    nearest = np.full((H, W), 255, np.int16)
    for dy in (-1, 0, 1):  # the two were resized separately, so allow a pixel of drift
        for dx in (-1, 0, 1):
            shifted = np.roll(s, (dy, dx), axis=(0, 1))
            nearest = np.minimum(nearest, np.abs(raw[..., :3] - shifted).max(2))
    paper_both = flat & (
        s.min(2) > PAPER_LIKE
    )  # halo over scan paper: a change of tone, not of content
    changed = solid & ~paper_both & (nearest > DIFF)
    changed = (
        np.asarray(
            Image.fromarray((changed * 255).astype(np.uint8), "L")
            .filter(ImageFilter.MinFilter(3))
            .filter(ImageFilter.MaxFilter(3))
        )
        > 0
    )
    removed = (raw[..., 3] < 25) & (s.min(2) < PAPER_LIKE)
    diff = np.asarray(page).copy()
    diff[removed] = (s[removed] * 0.45 + np.array([40, 90, 200]) * 0.55).astype(np.uint8)
    diff[changed] = (235, 30, 30)

    flags = np.asarray(page).copy()
    flags[suspect] = (235, 30, 30)
    flags[fat] = (255, 0, 200)

    out = WORK / "img" / key
    out.mkdir(parents=True, exist_ok=True)
    scan_layer.save(out / "scan.jpg", quality=92)
    page.save(out / "plate.jpg", quality=92)
    Image.fromarray(flags).save(out / "flags.jpg", quality=92)
    Image.fromarray(diff).save(out / "diff.jpg", quality=92)
    thumb = page.copy()
    thumb.thumbnail((160, 160))
    thumb.save(out / "thumb.jpg", quality=85)

    zooms = windows(suspect * 8 + pale, WINDOW, ZOOMS, floor=400)
    print(
        f"{key:14} {W}x{H}  match {match:.3f}  suspect {int(suspect.sum()):6}  zooms {len(zooms)}"
    )
    return {
        "id": key,
        "name": name,
        "pr": pr,
        "file": f"{stem}.webp",
        "source": entry.get("source", ""),
        "url": entry.get("url", ""),
        "w": W,
        "h": H,
        "match": round(float(match), 3),
        "suspect": int(suspect.sum()),
        "ring": int(ring.sum()),
        "changed": int(changed.sum()),
        "zooms": zooms,
    }


if __name__ == "__main__":
    args = sys.argv[1:]
    if args and Path(args[0]).is_dir():  # a review folder: plates.json in, birds.js and img/ out
        WORK, args = Path(args[0]).resolve(), args[1:]
    wanted = args
    data_path = WORK / "birds.js"
    known = {b["id"]: b for b in read_birds(data_path)}
    plates = json.loads((WORK / "plates.json").read_text())
    for bird in plates:
        if not wanted or any(w in bird["id"] for w in wanted):
            known[bird["id"]] = build(bird)
    ordered = [known[b["id"]] for b in plates if b["id"] in known]
    # A script tag, not JSON: the page has to load this straight off the filesystem, and
    # fetch() of a file:// URL is blocked as cross-origin. Double-clicking must keep working.
    data_path.write_text(f"window.BIRDS = {json.dumps(ordered, indent=1)};\n")
    if not (WORK / "index.html").exists():
        shutil.copy(HERE / "index.html", WORK / "index.html")
    print("wrote", data_path)
