"""Render plates as the frame would draw them: one collage for the web, one dithered for the panel.

    uv run python tools/preview_plates.py out/ assets/artwork/classic/birds/turdus-merula.webp ...

Writes `web.png` and `panel.png` into the folder, at the fallback panel's size.
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

from fugleramme.config import DEFAULT_PANEL_SIZE, PANEL_SIZES
from fugleramme.render.collage import render_collage
from fugleramme.render.dither import dither


def species(plate: Path) -> str:
    """ "turdus-merula-2.webp" -> "Turdus merula", the name its mass is looked up by."""
    return re.sub(r"-\d+$", "", plate.stem).replace("-", " ").capitalize()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("out", type=Path, help="folder for web.png and panel.png")
    parser.add_argument("plates", type=Path, nargs="+")
    args = parser.parse_args()

    entries: list[tuple[str, Path | None]] = [(species(p), p) for p in args.plates]
    args.out.mkdir(parents=True, exist_ok=True)
    size = PANEL_SIZES[DEFAULT_PANEL_SIZE]
    render_collage(entries, size).save(args.out / "web.png")
    panel = render_collage(entries, size, textured=False)
    dither(panel).save(args.out / "panel.png")


if __name__ == "__main__":
    main()
