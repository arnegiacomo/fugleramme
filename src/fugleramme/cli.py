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

from .collage import gather_entries, render_collage
from .config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DB_PATH,
    DEFAULT_HOST,
    DEFAULT_PORT,
    REPO_ROOT,
    Config,
)
from .db import Database
from .service import run
from .settings import SettingsStore


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fugleramme-frame", description=__doc__)
    parser.add_argument(
        "--images", type=Path, default=REPO_ROOT / "assets" / "birds",
        help="bird artwork directory",
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="settings file (#2)")
    parser.add_argument(
        "--output", type=Path, default=Path("frame.png"), help="rendered frame path"
    )
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--preview", type=Path, help="render the full-color collage to this path and exit"
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    config = Config(
        images_dir=args.images,
        db_path=args.db,
        output_path=args.output,
        host=args.host,
        port=args.port,
        config_path=args.config,
    )

    if args.preview:
        settings = SettingsStore(config.config_path).get()
        db = Database(config.db_path)
        rng = random.Random(hash(tuple(name for name, _ in db.species_since(settings.lookback_hours))))
        entries = gather_entries(db, config.images_dir, rng, settings.lookback_hours)
        render_collage(entries, settings.resolution(), False, rng).save(args.preview)
        db.close()
        print(f"preview written to {args.preview}")
        return

    run(config)


if __name__ == "__main__":
    main()
