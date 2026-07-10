"""Poll BirdNET-Go's `notes` table into the frame's `detections` table.

The only code that knows BirdNET-Go's schema: it maps each note into the frame's
shape, converting BirdNET-Go's local Date+Time to UTC. Idempotent (dedup on
scientific_name + detected_at) so a source reset or restart never dupes or skips.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from .db import Database

log = logging.getLogger(__name__)

_POLL_SECONDS = 10
# BirdNET-Go's notes.date + notes.time strings (Go layouts "2006-01-02" + "15:04:05").
_SRC_FORMAT = "%Y-%m-%d %H:%M:%S"
_SELECT = (
    "SELECT id, date, time, scientific_name, confidence, clip_name "
    "FROM notes WHERE id > ? ORDER BY id"
)


def to_utc(date: str, clock: str, tz: ZoneInfo) -> datetime:
    local = datetime.strptime(f"{date} {clock}", _SRC_FORMAT).replace(tzinfo=tz)
    return local.astimezone(timezone.utc)


def sync_once(source: sqlite3.Connection, target: Database, tz: ZoneInfo, cursor: int) -> int:
    """Copy notes with id > cursor into detections. Returns the new cursor."""
    for row in source.execute(_SELECT, (cursor,)).fetchall():
        detected_at = to_utc(row["date"], row["time"], tz)
        if not target.has_detection(row["scientific_name"], detected_at.isoformat()):
            target.insert(
                scientific_name=row["scientific_name"],
                confidence=row["confidence"],
                detected_at=detected_at,
                clip_path=row["clip_name"] or None,
            )
            log.info("detection: %s (%.2f) at %s", row["scientific_name"],
                     row["confidence"], detected_at.isoformat())
        cursor = max(cursor, row["id"])
    return cursor


def run(source_db: Path, target_db: Path, tz_name: str) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    tz = ZoneInfo(tz_name)
    target = Database(target_db)
    source: sqlite3.Connection | None = None
    cursor = 0
    log.info("Syncing %s -> %s (tz=%s)", source_db, target_db, tz_name)
    while True:
        try:
            if source is None:
                # rw, not the default: reads the WAL DB but won't create an empty
                # file shadowing BirdNET-Go's if it hasn't written yet.
                source = sqlite3.connect(f"file:{source_db}?mode=rw", uri=True)
                source.row_factory = sqlite3.Row
            cursor = sync_once(source, target, tz, cursor)
        except sqlite3.OperationalError as exc:
            # Source missing or recreated: reconnect and re-scan; dedup guards dupes.
            log.warning("source not ready (%s); retrying", exc)
            if source is not None:
                source.close()
            source = None
            cursor = 0
        time.sleep(_POLL_SECONDS)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fugleramme-sync", description=__doc__)
    parser.add_argument(
        "--source", type=Path, default=Path("/dev/shm/fugleramme/birdnet.db"),
        help="BirdNET-Go's SQLite file (the notes table)",
    )
    parser.add_argument(
        "--db", type=Path, default=Path("data/detections.db"),
        help="the frame's detections DB to write into",
    )
    parser.add_argument(
        "--tz", default="Europe/Oslo",
        help="timezone BirdNET-Go stores Date/Time in; must match the compose TZ",
    )
    args = parser.parse_args(argv)
    run(args.source, args.db, args.tz)


if __name__ == "__main__":
    main()
