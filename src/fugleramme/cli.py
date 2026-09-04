"""Command-line entry point for the frame service.

Two modes:
  --preview OUT.png   render the page once and exit (no server, no push). It
                      still reads the panel's size, which shapes the page.
  (default)           run the service: render loop + HTTP server, pushing to
                      the Inky panel if one is present.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from . import modes
from .config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_DETECTOR_URL,
    DEFAULT_HOST,
    DEFAULT_PORT,
    REPO_ROOT,
    Config,
)
from .languages import namer
from .panel import init_panel, resolution_of
from .picks import FILENAME as PICKS_FILE, Picks
from .service import detector, run
from .source import Unavailable


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="fugleramme-frame", description=__doc__)
    parser.add_argument(
        "--images",
        type=Path,
        default=REPO_ROOT / "assets" / "artwork",
        help="bird artwork directory",
    )
    parser.add_argument(
        "--detector",
        default=DEFAULT_DETECTOR_URL,
        help="BirdNET-Go base URL; only used when the settings file names none",
    )
    parser.add_argument(
        "--config", type=Path, default=DEFAULT_CONFIG_PATH, help="settings file (#2)"
    )
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
        detector_url=args.detector,
        output_path=args.output,
        host=args.host,
        port=args.port,
        config_path=args.config,
    )

    if args.preview:
        store, source = detector(config)
        settings = store.get()
        data_dir = config.config_path.parent
        name_of = namer(settings.primary_language, settings.secondary_language, data_dir)
        ctx = modes.context(
            source,
            config.images_dir,
            Picks(data_dir / PICKS_FILE),
            settings,
            name_of,
            settings.web_size(resolution_of(init_panel())),
        )
        try:
            page = modes.render(ctx)
        except Unavailable as exc:
            # A blank page is worse than no page: it looks like a working frame.
            raise SystemExit(f"No page written: {exc}") from exc
        page.save(args.preview)
        source.close()
        print(f"preview written to {args.preview}")
        return

    run(config)


if __name__ == "__main__":
    main()
