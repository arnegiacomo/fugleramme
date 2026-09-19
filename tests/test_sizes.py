"""Guards on how a bird box becomes a size.

`span_ratio` is what makes a plate bigger than its bird, and it fails quietly in
both directions: a box nobody notices is wrong draws the bird at the wrong size,
and a box the loader cannot read takes the render loop down with it. The frame
has no page to fall back to, so a hand-edited typo must cost one plate its box
and nothing else.
"""

from __future__ import annotations

import json
from pathlib import Path

from fugleramme.render.sizes import GEOMETRY, geometry_of, span_ratio

WIDE = (1000, 400)


def _style(tmp_path: Path, boxes: dict[str, object]) -> Path:
    style = tmp_path / "scratch"
    (style / "birds").mkdir(parents=True)
    (style / GEOMETRY).write_text(json.dumps(boxes))
    return style / "birds" / "bird.webp"


def _entry(box: list[float], cut: tuple[int, int] = WIDE) -> dict[str, object]:
    return {"box": box, "cut": list(cut)}


def test_a_plate_with_no_record_sizes_as_the_whole_picture(tmp_path: Path) -> None:
    assert span_ratio(tmp_path / "birds" / "bird.webp", WIDE) == 1.0


def test_a_box_over_the_whole_plate_sizes_as_the_whole_picture(tmp_path: Path) -> None:
    plate = _style(tmp_path, {"birds/bird.webp": _entry([0.0, 0.0, 1.0, 1.0])})
    assert span_ratio(plate, WIDE) == 1.0


def test_a_bird_across_half_the_plate_doubles_it(tmp_path: Path) -> None:
    plate = _style(tmp_path, {"birds/bird.webp": _entry([0.25, 0.0, 0.75, 1.0])})
    assert span_ratio(plate, WIDE) == 2.0


def test_only_the_longest_side_is_read(tmp_path: Path) -> None:
    """A box tight on the short axis of a wide plate must not change the size -
    the collage scales a cut-out by its longest side and nothing else."""
    plate = _style(tmp_path, {"birds/bird.webp": _entry([0.0, 0.4, 1.0, 0.6])})
    assert span_ratio(plate, WIDE) == 1.0


def test_an_unreadable_box_costs_that_plate_alone(tmp_path: Path) -> None:
    """One bad entry must not raise, and must not take its neighbours with it."""
    plate = _style(
        tmp_path,
        {
            "birds/bird.webp": _entry([0.25, 0.0, 0.75, 1.0]),
            "birds/text.webp": _entry(["x", 0.0, 0.75, 1.0]),
            "birds/short.webp": _entry([0.25, 0.0, 0.75]),
            "birds/inverted.webp": _entry([0.75, 0.0, 0.25, 1.0]),
            "birds/outside.webp": _entry([0.25, 0.0, 1.4, 1.0]),
            "birds/nocut.webp": {"box": [0.25, 0.0, 0.75, 1.0]},
            "birds/bare.webp": [0.25, 0.0, 0.75, 1.0],
            "birds/null.webp": None,
        },
    )
    assert span_ratio(plate, WIDE) == 2.0
    for name in ("text", "short", "inverted", "outside", "nocut", "bare", "null"):
        bad = plate.with_name(f"{name}.webp")
        assert geometry_of(bad) is None, f"{name} should have been dropped"
        assert span_ratio(bad, WIDE) == 1.0


def test_a_record_that_is_not_json_leaves_every_plate_alone(tmp_path: Path) -> None:
    style = tmp_path / "scratch"
    (style / "birds").mkdir(parents=True)
    (style / GEOMETRY).write_text("{ this is not json")
    assert span_ratio(style / "birds" / "bird.webp", WIDE) == 1.0


def test_a_box_drawn_on_a_crop_that_has_moved_is_ignored(tmp_path: Path) -> None:
    """The one failure nothing else can see.

    Re-cut a plate and its box still holds four valid fractions, in range and in
    order - they just point at a different part of the picture now. Without the
    cut recorded beside them the bird is drawn to a measurement of the branch,
    and no test, no log line and no look at the file says so.
    """
    plate = _style(tmp_path, {"birds/bird.webp": _entry([0.25, 0.0, 0.75, 1.0], WIDE)})
    assert span_ratio(plate, WIDE) == 2.0
    assert span_ratio(plate, (1200, 400)) == 1.0, "a box from another crop was trusted"
