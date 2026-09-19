# /// script
# requires-python = ">=3.11"
# dependencies = ["pillow>=10.0", "torch>=2.2", "torchvision>=0.17"]
# ///
"""Propose a bird box for a plate: where the bird sits in the file it was cut into.

The collage scales a cut-out's longest side to what the species' mass asks for,
which is the bird's own length only when the plate is one bird cut tight. A plate
carrying a second bird or a wash of riverbank is sized by the scenery instead, so
each one gets a box round the bird its mass refers to (`render/sizes.py`).

COCO detection transfers to 19th-century engravings better than it has any right
to - every plate sampled scored over 0.98 on its main bird, and it separates two
birds on one plate. The boxes are loose though, duplicated at several scales on
one bird, and it finds birds in grass, so what comes out is a proposal to nudge
in `tools/bird_box.py`, never an answer.

    uv run tools/bird_boxes.py assets/artwork/classic/birds/turdus-merula.webp

Prints {"<filename>": {"box": [x0, y0, x1, y1], "cut": [w, h]}} to stdout. The box
is fractions of the *trimmed* cut-out, which is what the collage measures, and the
cut is the crop they were measured against - a box outliving a re-cut is wrong in
a way nothing else catches. A plate it cannot read is left out rather than guessed
at, and no box at all is the safe state: the plate sizes as the whole picture.

Its dependencies are declared above rather than in pyproject.toml: `uv run` builds
them per invocation, so torch stays out of uv.lock and off the Pi. The first run
downloads about 2 GB of wheels plus the COCO weights, and is slow.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from PIL import Image

PAPER = (242, 237, 226)  # render.paper.TARGET_PAPER; a cut-out on black scores worse
DETECT = 800  # longest side the detector sees; the box is normalised anyway
SCORE = 0.5  # COCO confidence to count as a bird at all
CONTAINED = 0.75  # fraction of a box inside another to count as enclosed
SWALLOWS = (1.6, 4.0)  # area ratio band where an enclosed box reads as a second bird
SURE = 0.7  # confidence an enclosed box needs before it can condemn its container
FLOOR = 0.25  # of the cut-out's longest side; under this the detector found a speck

Box = list[float]
Entry = dict[str, list[float]]

# The weights `detect` asks for: this goes stale rather than lying if they change.
WEIGHTS = "fasterrcnn_resnet50_fpn_v2_coco-dd69338a.pth"


def downloaded() -> bool:
    """Whether the detector has ever run on this machine.

    The weights land only after a run that got as far as loading the model, which
    means the wheels were built first - so this one file answers for the whole two
    gigabytes, and a caller can ask before committing anyone to the download.
    """
    home = Path(os.environ.get("TORCH_HOME") or Path.home() / ".cache" / "torch")
    return (home / "hub" / "checkpoints" / WEIGHTS).is_file()


def trim(path: Path) -> Image.Image:
    """The cut-out with its transparent margin off. `render.page.trim`, kept here
    rather than imported: this script runs in its own environment, without the
    package, so that torch is never a dependency of the frame."""
    img = Image.open(path).convert("RGBA")
    bbox = img.getchannel("A").getbbox()
    return img.crop(bbox) if bbox else img


def flatten(img: Image.Image) -> Image.Image:
    page = Image.new("RGB", img.size, PAPER)
    page.paste(img, (0, 0), img)
    return page


def _area(box: Box) -> float:
    return max(0.0, box[2] - box[0]) * max(0.0, box[3] - box[1])


def _swallows(outer: Box, inner: Box) -> bool:
    """`outer` holds `inner`, and the two are far enough apart in size to be two
    birds rather than two reads of one - so `outer` is covering a group.

    Banded at both ends. Below the band the pair is one bird read twice; above it
    `inner` is a part or a speck in the distance - a head, a foot, a stork on the
    far bank - and condemning the bird that holds it sends the box onto the speck.
    """
    lap = [
        max(outer[0], inner[0]),
        max(outer[1], inner[1]),
        min(outer[2], inner[2]),
        min(outer[3], inner[3]),
    ]
    if _area(lap) < CONTAINED * _area(inner) or not _area(inner):
        return False
    return SWALLOWS[0] <= _area(outer) / _area(inner) <= SWALLOWS[1]


def pick(boxes: list[Box], scores: list[float], span: tuple[int, int]) -> Box | None:
    """The one bird the species' mass refers to: the largest adult.

    Only a confident box may condemn its container, or a stray read on a wing
    would drop the bird it sits on.
    """
    sure = [box for box, score in zip(boxes, scores, strict=True) if score >= SURE]
    singles = [box for box in boxes if not any(_swallows(box, o) for o in sure if o != box)]
    best = max(singles or boxes, key=lambda b: max(b[2] - b[0], b[3] - b[1]), default=None)
    if best is None:
        return None
    # This small is the detector on a speck. No box beats a twentyfold ratio.
    if max(best[2] - best[0], best[3] - best[1]) < FLOOR * max(span):
        return None
    return best


def detect(paths: list[Path]) -> dict[str, Entry]:
    import torch
    import torchvision
    from torchvision.models.detection import (
        FasterRCNN_ResNet50_FPN_V2_Weights,
        fasterrcnn_resnet50_fpn_v2,
    )

    weights = FasterRCNN_ResNet50_FPN_V2_Weights.DEFAULT
    bird = weights.meta["categories"].index("bird")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = fasterrcnn_resnet50_fpn_v2(weights=weights, box_score_thresh=SCORE)
    model.eval().to(device)

    found: dict[str, Entry] = {}
    with torch.no_grad():
        for number, path in enumerate(paths, 1):
            art = trim(path)
            page = flatten(art)
            page.thumbnail((DETECT, DETECT), Image.Resampling.LANCZOS)
            tensor = torchvision.transforms.functional.to_tensor(page).to(device)
            out = model([tensor])[0]
            keep = out["labels"] == bird
            best = pick(out["boxes"][keep].tolist(), out["scores"][keep].tolist(), page.size)
            if best is None:
                print(f"  {path.name}: no bird found", file=sys.stderr)
                continue
            width, height = page.size
            found[path.name] = {
                "box": [best[0] / width, best[1] / height, best[2] / width, best[3] / height],
                "cut": list(art.size),
            }
            if len(paths) > 20 and number % 25 == 0:
                print(f"  {number}/{len(paths)}", file=sys.stderr)
    return found


def main() -> None:
    paths = [Path(argument) for argument in sys.argv[1:]]
    missing = [str(path) for path in paths if not path.exists()]
    if not paths or missing:
        sys.exit(f"usage: bird_boxes.py PLATE [PLATE ...]{chr(10)}no such file: {missing}")
    json.dump(detect(paths), sys.stdout, indent=1, sort_keys=True)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
