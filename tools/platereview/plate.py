"""Cut one bird out of a scanned plate, driven by a JSON spec.

    plate.py crop  spec.json            crop the scan to the bird, at working size
    plate.py zoom  spec.json x0,y0,x1,y1 [image]   a gridded close-up, in crop pixels
    plate.py cut   spec.json            the cut-out with its halo, plus a check image

Spec: scan, box (scan px), paper_min, seed, and optionally remove (polygons),
caps ([x, y, r] discs kept inside a removed area, to round a branch's cut end),
gaps (seeds in paper the outside flood cannot reach), clones ([polygon, dx, dy]).
All but box are in crop pixels. The halo follows docs/adding-artwork.md.
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

Image.MAX_IMAGE_PIXELS = None
WORK = 2400  # longest side of the working crop; the shipped plate is capped at 1200
PAPER = (0xF0, 0xEC, 0xE5)
HALO_SHIPPED = 17  # px of halo wanted once the plate is capped at 1200
SEVERED = 20000  # px of ink off the seed's component worth warning about: a heron's legs
# ran to 71,000, a plate number to a few hundred


def region(polygons, size):
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    for polygon in polygons:
        draw.polygon([tuple(p) for p in polygon], fill=255)
    return np.asarray(mask) > 0


def flood(mask, seed):
    """The pixels of a boolean mask connected to seed. fromarray is read-only, so copy."""
    if not mask[seed[1], seed[0]]:  # floodfill would fill the background the seed sits in
        print(f"  ! seed {list(seed)} is not inside the mask, skipped")
        return np.zeros_like(mask)
    image = Image.fromarray((mask * 255).astype(np.uint8), "L").copy()
    ImageDraw.floodfill(image, tuple(seed), 128)
    return np.asarray(image) == 128


def as_mask(mask):
    return Image.fromarray((mask * 255).astype(np.uint8), "L")


def crop(spec, out):
    im = Image.open(spec["scan"]).convert("RGB").crop(spec["box"])
    if max(im.size) > WORK:
        scale = WORK / max(im.size)
        im = im.resize(
            (round(im.width * scale), round(im.height * scale)), Image.Resampling.LANCZOS
        )
    im.save(out / "crop.png")
    print("crop", im.size)
    zoom(out, (0, 0, *im.size), "crop.png", "overview", step=100)


def zoom(out, box, source, name, step=50):
    x0, y0, x1, y1 = box
    im = Image.open(out / source).convert("RGB")
    z = 1400 / (x1 - x0)
    view = im.crop(box).resize((1400, round((y1 - y0) * z)), Image.Resampling.LANCZOS)
    draw = ImageDraw.Draw(view)
    for gx in range((x0 // step + 1) * step, x1, step):
        draw.line([((gx - x0) * z, 0), ((gx - x0) * z, view.height)], fill=(0, 120, 255))
        draw.text(((gx - x0) * z + 2, 2), str(gx), fill=(0, 0, 200))
    for gy in range((y0 // step + 1) * step, y1, step):
        draw.line([(0, (gy - y0) * z), (view.width, (gy - y0) * z)], fill=(0, 120, 255))
        draw.text((2, (gy - y0) * z + 2), str(gy), fill=(0, 0, 200))
    view.save(out / f"zoom-{name}.jpg", quality=88)
    print("zoom", name, view.size)


def cut(spec, out):
    rgb = Image.open(out / "crop.png").convert("RGB")
    for polygon, dx, dy in spec.get("clones", []):
        shifted = Image.fromarray(np.roll(np.asarray(rgb), (-dy, -dx), axis=(0, 1)))
        patch = Image.new("L", rgb.size, 0)
        ImageDraw.Draw(patch).polygon([tuple(p) for p in polygon], fill=255)
        rgb = Image.composite(shifted, rgb, patch.filter(ImageFilter.GaussianBlur(1.5)))
    arr = np.asarray(rgb)
    h, w = arr.shape[:2]
    blank = arr.min(axis=2) > spec["paper_min"]
    if "balance" in spec:  # an aged scan: scale each channel so its paper lands on the halo's tone
        gain = np.array(PAPER) / np.array(spec["balance"])
        rgb = Image.fromarray(np.clip(arr * gain, 0, 255).round().astype(np.uint8), "RGB")
    removed = region(spec.get("remove", []), (w, h))
    if "ground" in spec and "outline" in spec:
        # a hand trace is a few px loose: just inside it, drop what is coloured like the
        # painted ground (pink or brown: red well over green) and not dark enough to be ink
        g = spec["ground"]
        inside = region([spec["outline"]], (w, h))
        core = np.asarray(as_mask(inside).filter(ImageFilter.MinFilter(2 * g["band"] + 1))) > 0
        a = arr.astype(int)
        groundlike = (a[..., 0] - a[..., 1] > g["rg"]) & (a.max(axis=2) > g["dark"])
        rows_below = np.arange(h)[:, None] >= g["ymin"]
        removed |= inside & ~core & groundlike & rows_below
    if "keep" in spec:  # a paper-pale part with a faint outline: never let the flood in
        blank = blank & ~region(spec["keep"], (w, h))
    if "outline" in spec:  # a hand-traced edge, for a bird on a painted ground
        removed |= ~region([spec["outline"]], (w, h))
    yy, xx = np.mgrid[:h, :w]
    for x, y_lo, y_hi in spec.get("caps", []):
        # the branch is the longest inked run in this column; the disc is as thick as it
        column = np.flatnonzero(~blank[y_lo:y_hi, x]) + y_lo
        run = max(np.split(column, np.flatnonzero(np.diff(column) > 1) + 1), key=len)
        y, r = (run[0] + run[-1]) / 2, (run[-1] - run[0] + 1) / 2
        print(f"cap at x={x}: y {run[0]}-{run[-1]}, radius {r:.0f}")
        removed &= (xx - x) ** 2 + (yy - y) ** 2 > r**2

    for y, x_lo, x_hi in spec.get("hcaps", []):  # the same, for a branch that runs upright
        row = np.flatnonzero(~blank[y, x_lo:x_hi]) + x_lo
        run = max(np.split(row, np.flatnonzero(np.diff(row) > 1) + 1), key=len)
        x, r = (run[0] + run[-1]) / 2, (run[-1] - run[0] + 1) / 2
        print(f"cap at y={y}: x {run[0]}-{run[-1]}, radius {r:.0f}")
        removed &= (xx - x) ** 2 + (yy - y) ** 2 > r**2

    for x, y, r in spec.get("discs", []):  # a pale branch: plug the cut end so the flood stays out
        inside = (xx - x) ** 2 + (yy - y) ** 2 <= r**2
        removed &= ~inside
        blank = blank & ~inside

    # paper reachable from the border once the branches are gone, through a 1 px
    # paper frame so every edge seeds it
    # Only clean paper lets the outside in, and only through openings wider than the seal:
    # pale plumage is lighter than paper_min, and its outline is often faint or dotted, so a
    # flood through everything "blank" walks into a white bill or belly and flattens it.
    clean = blank & (arr.min(axis=2) > spec.get("paper_clean", 241))
    seal = spec.get("seal", 3)
    wall = (
        as_mask(~clean)
        .filter(ImageFilter.MaxFilter(2 * seal + 1))
        .filter(ImageFilter.MinFilter(2 * seal + 1))
    )
    sealed = ~(np.asarray(wall) > 0)
    outside = flood(np.pad(sealed | removed, 1, constant_values=True), (0, 0))[1:-1, 1:-1]
    # sealing also shuts the narrow paper between toes or tail feathers; let the outside
    # back into clean paper, a short way only, so a gap in an outline cannot run deep
    for _ in range(spec.get("regrow", 30)):
        outside = outside | (
            (np.asarray(as_mask(outside).filter(ImageFilter.MaxFilter(3))) > 0) & (clean | removed)
        )
    # only the piece the bird is in: drops figure numbers, specks and other birds
    bird = flood(~outside, spec["seed"])
    # That flood is also how a leg, a tail or a bill disappears: sever one from the body and
    # it is simply not in the seed's component any more, silently. Figure numbers and stray
    # specks are small, so anything large enough to be part of the bird is worth a look.
    dropped = int((~outside & ~bird).sum())
    if dropped > SEVERED:
        print(f"  ! {dropped} px not connected to the seed - check for a severed leg or tail")
    # Paper the flood could not reach is scan-toned, and the frame shifts all paper
    # by one delta, so it would print off the page's tone: give it the halo's.
    gap = np.zeros_like(bird)
    for seed in spec.get("gaps", []):
        gap |= flood(bird & (clean | removed), seed)  # removed: painted ground a perch encloses
    print(f"bird {int(bird.sum())} px of {w * h}, gaps {int(gap.sum())} px")

    rows, cols = np.flatnonzero(bird.any(1)), np.flatnonzero(bird.any(0))
    longest = max(rows[-1] - rows[0], cols[-1] - cols[0])
    halo_px = float(HALO_SHIPPED * max(1.0, longest / 1200))  # numpy scalars trip GaussianBlur
    soft = as_mask(bird & ~gap).filter(ImageFilter.GaussianBlur(0.8))
    grown = np.asarray(as_mask(bird).filter(ImageFilter.GaussianBlur(halo_px / 2))) > 6
    alpha = as_mask(grown).filter(ImageFilter.GaussianBlur(0.8))

    result = Image.composite(rgb, Image.new("RGB", (w, h), PAPER), soft).convert("RGBA")
    result.putalpha(alpha)
    result.save(out / "cut.png")
    check = Image.new("RGB", (w, h), (70, 110, 160))  # a loud ground, to show leaks and stubs
    check.paste(result, (0, 0), result)
    check.save(out / "check.png")
    small = check.copy()
    small.thumbnail((1500, 1500))
    small.save(out / "check.jpg", quality=90)


if __name__ == "__main__":
    command, spec_path = sys.argv[1], Path(sys.argv[2])
    spec, out = json.loads(spec_path.read_text()), spec_path.parent
    if command == "crop":
        crop(spec, out)
    elif command == "zoom":
        box = tuple(int(v) for v in sys.argv[3].split(","))
        zoom(
            out,
            box,
            sys.argv[4] if len(sys.argv) > 4 else "crop.png",
            sys.argv[5] if len(sys.argv) > 5 else "a",
            step=int(sys.argv[6]) if len(sys.argv) > 6 else 50,
        )
    elif command == "cut":
        cut(spec, out)
