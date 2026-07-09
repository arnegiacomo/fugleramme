"""Command-line entry point for the frame service.

Two modes:
  --preview OUT.png   render the latest detection once and exit (no server,
                      no panel) - the hardware-free Mac layout loop.
  (default)           run the service: render loop + HTTP server, pushing to
                      the Inky panel if one is present.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import random

from .collage import DEFAULT_RESOLUTION, gather_entries, render_collage
from .config import DEFAULT_PANEL, PANEL_RESOLUTIONS, REPO_ROOT, Config, resolve_resolution
from .db import Database
from .service import run


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fugleramme-frame", description=__doc__)
    parser.add_argument(
        "--panel",
        choices=sorted(PANEL_RESOLUTIONS),
        default=DEFAULT_PANEL,
        help=f"Inky size preset (default {DEFAULT_PANEL})",
    )
    parser.add_argument(
        "--resolution", help="explicit WxH, overrides --panel (e.g. 800x480)"
    )
    parser.add_argument(
        "--images", type=Path, default=REPO_ROOT / "assets" / "birds",
        help="bird artwork directory",
    )
    parser.add_argument("--db", type=Path, default=Path("data/detections.db"))
    parser.add_argument(
        "--output", type=Path, default=Path("frame.png"), help="rendered frame path"
    )
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument(
        "--preview", type=Path, help="render the full-color collage to this path and exit"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    resolution = resolve_resolution(args.panel, args.resolution)
    config = Config(
        resolution=resolution,
        images_dir=args.images,
        db_path=args.db,
        output_path=args.output,
        host=args.host,
        port=args.port,
    )

    if args.preview:
        db = Database(config.db_path)
        species = db.species_last_24h()
        rng = random.Random(hash(tuple(name for name, _ in species)))
        entries = gather_entries(db, config.images_dir, rng)
        render_collage(entries, DEFAULT_RESOLUTION, False, rng).save(args.preview)
        db.close()
        print(f"preview written to {args.preview}")
        return

    run(config)


if __name__ == "__main__":
    main()
