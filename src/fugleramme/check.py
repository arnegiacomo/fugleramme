"""Ask a BirdNET-Go whether it answers everything the frame needs.

    fugleramme-check                                  # the saved connection
    fugleramme-check --detector http://pi.local:8090  # someone else's

Points at the fake or at a real station, which is what catches `fake.py`
drifting from upstream.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from . import languages
from .api import ApiSource
from .config import DEFAULT_CONFIG_PATH, DEFAULT_DETECTOR_URL
from .settings import Settings, SettingsStore
from .source import Unavailable
from .web import hostinfo

_OK, _FAIL = "ok  ", "FAIL"


def _describe(value: Any) -> str:
    if isinstance(value, list) and value and all(isinstance(v, str) for v in value):
        return ", ".join(value)
    if isinstance(value, list):
        return f"{len(value)} species"
    return str(value)


def _check(label: str, run) -> bool:
    try:
        print(f"{_OK} {label:<22} {_describe(run())}")
        return True
    except Unavailable as error:
        print(f"{_FAIL} {label:<22} {error}")
    except Exception as error:  # a shape the frame cannot read is a failure too
        print(f"{_FAIL} {label:<22} {type(error).__name__}: {error}")
    return False


def _latest(source: ApiSource) -> str:
    newest = source.latest()
    return "none" if newest is None else f"{newest.scientific_name} at {newest.detected_at}"


def _first(source: ApiSource) -> str:
    life = source.life_list()
    return f"{len(life)} species, earliest {life[0].first_seen.date()}" if life else "none"


def run(url: str, username: str, password: str, cache_dir: Path) -> int:
    source = ApiSource(url, username, password)
    languages.use(source)
    reachable, version = hostinfo.detector(url)
    print(f"{url}\n")
    print(f"{_OK if reachable else _FAIL} {'reachable':<22} {version or 'no answer'}")
    checks = [
        ("species, 6 hours", lambda: source.species_since(6)),
        ("species, 24 hours", lambda: source.species_since(24)),
        ("species, all time", lambda: source.species_since(0)),
        ("latest detection", lambda: _latest(source)),
        ("life list", lambda: _first(source)),
        ("name languages", lambda: sorted(languages.catalog(cache_dir))),
    ]
    passed = [_check(label, run_one) for label, run_one in checks]
    failed = passed.count(False) + (not reachable)
    print(f"\n{failed} failed" if failed else "\nall good")
    return 1 if failed else 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--detector", help=f"base URL (default: saved, or {DEFAULT_DETECTOR_URL})")
    parser.add_argument("--username", default="")
    parser.add_argument("--password", default="")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH)
    args = parser.parse_args()

    saved = SettingsStore(args.config, Settings(detector_url=DEFAULT_DETECTOR_URL)).get()
    sys.exit(
        run(
            args.detector or saved.detector_url,
            args.username or saved.detector_username,
            args.password or saved.detector_password,
            args.config.parent,
        )
    )


if __name__ == "__main__":
    main()
