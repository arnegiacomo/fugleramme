"""Guards on what `tools/add_bird.py` does to a cut-out before it ships.

`prepare` is the only step between a contributor's cut-out and the plate the
frame draws, so it may crop and shrink and nothing else. The soft edge is where
that goes wrong unseen: its pixels are nearly transparent in an editor, but
`render.paper` treats anything over alpha 24 as the plate and prints it.

`forget_box` is the other silent one: a bird box is normalised to the trimmed
cut-out, so a plate re-cut under its box is sized off a patch of paper and the
page says nothing about it.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import add_bird

PAPER = (0xF0, 0xEC, 0xE5)
DRAWN = 24  # render.paper.process_sprite: `opaque = alpha > 24`


def _disc(path: Path, size: int, margin: int) -> Path:
    """One flat colour under a soft-edged disc - whatever comes back in any other
    colour was made by the tool."""
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).ellipse((margin, margin, size - margin, size - margin), fill=255)
    img = Image.new("RGBA", (size, size), (*PAPER, 0))
    img.putalpha(mask.filter(ImageFilter.GaussianBlur(0.8)))
    img.save(path)
    return path


def test_shrinking_keeps_the_soft_edge_its_colour(tmp_path: Path) -> None:
    out = np.asarray(add_bird.prepare(_disc(tmp_path / "disc.png", 2400, 200))).astype(int)
    alpha, rgb = out[..., 3], out[..., :3]
    edge = (alpha > DRAWN) & (alpha < 255)
    assert edge.sum() > 1000, "the disc lost its soft edge, so this test checks nothing"
    off = np.abs(rgb - np.array(PAPER)).max(axis=2)
    assert off[edge].max() <= 1, (
        f"{int((edge & (off > 1)).sum())} of {int(edge.sum())} soft-edge pixels the frame draws "
        f"changed colour in the downscale, the worst by {int(off[edge].max())} levels"
    )


def test_shrinking_keeps_the_inside_its_colour(tmp_path: Path) -> None:
    out = np.asarray(add_bird.prepare(_disc(tmp_path / "disc.png", 2400, 200))).astype(int)
    solid = out[..., 3] == 255
    assert np.abs(out[..., :3][solid] - np.array(PAPER)).max() <= 1


def test_prepare_crops_to_the_alpha_and_caps_the_longest_side(tmp_path: Path) -> None:
    img = add_bird.prepare(_disc(tmp_path / "disc.png", 2400, 200), cap=600)
    assert max(img.size) == 600
    alpha = np.asarray(img)[..., 3]
    edges = (alpha[0], alpha[-1], alpha[:, 0], alpha[:, -1])
    assert all(edge.any() for edge in edges), "a fully transparent row or column was left on"


def test_prepare_leaves_a_cut_out_under_the_cap_alone(tmp_path: Path) -> None:
    path = _disc(tmp_path / "disc.png", 800, 100)
    with Image.open(path) as opened:
        source = opened.convert("RGBA")
    expected = np.asarray(source.crop(source.getchannel("A").getbbox()))
    assert np.array_equal(np.asarray(add_bird.prepare(path)), expected)


def _boxed(style: Path, listed: dict[str, list[float]]) -> Path:
    (style / add_bird.BIRDS).mkdir(parents=True)
    record = style / add_bird.GEOMETRY
    record.write_text(json.dumps(listed, indent=1, sort_keys=True) + "\n")
    return record


def test_forget_box_drops_the_one_entry(tmp_path: Path) -> None:
    kept = {"birds/keep.webp": [0.1, 0.2, 0.3, 0.4]}
    record = _boxed(tmp_path / "scratch", {**kept, "birds/recut.webp": [0.5, 0.6, 0.7, 0.8]})
    add_bird.forget_box(tmp_path / "scratch", "recut.webp")
    assert json.loads(record.read_text()) == kept


def test_forget_box_leaves_the_file_alone_for_a_plate_it_has_no_box_for(tmp_path: Path) -> None:
    record = _boxed(tmp_path / "scratch", {"birds/keep.webp": [0.1, 0.2, 0.3, 0.4]})
    before = record.read_bytes()
    add_bird.forget_box(tmp_path / "scratch", "brand-new.webp")
    assert record.read_bytes() == before, "a plate with no box rewrote the whole record"


def test_forget_box_is_a_no_op_for_a_style_that_keeps_no_boxes(tmp_path: Path) -> None:
    style = tmp_path / "scratch"
    (style / add_bird.BIRDS).mkdir(parents=True)
    add_bird.forget_box(style, "anything.webp")
    assert not (style / add_bird.GEOMETRY).exists()
