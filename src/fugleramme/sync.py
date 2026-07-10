"""Poll BirdNET-Go's detections into the frame's `detections` table.

The only code that knows BirdNET-Go's schema. BirdNET-Go's own table is also
called `detections` (a coincidence - it lives in a separate DB file); it is
normalized, so the species name comes from a join to `labels` and the timestamp
is a Unix epoch (UTC, seconds). This maps each new row into the frame's shape.
Idempotent (dedup on scientific_name + detected_at) so a source reset or restart
never dupes or skips.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

from .db import Database

log = logging.getLogger(__name__)

_POLL_SECONDS = 10
# BirdNET-Go stores only species detections we care about; noise/environment/
# device labels are filtered out. detected_at is epoch seconds (UTC).
_SELECT = (
    "SELECT d.id, d.detected_at, l.scientific_name, d.confidence, d.clip_name "
    "FROM detections d "
    "JOIN labels l ON l.id = d.label_id "
    "JOIN label_types t ON t.id = l.label_type_id "
    "WHERE t.name = 'species' AND d.id > ? "
    "ORDER BY d.id"
)


def sync_once(source: sqlite3.Connection, target: Database, cursor: int) -> int:
    """Copy detections with id > cursor into the frame's table. Returns the new cursor."""
    for row in source.execute(_SELECT, (cursor,)).fetchall():
        detected_at = datetime.fromtimestamp(row["detected_at"], tz=timezone.utc)
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


def run(source_db: Path, target_db: Path) -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    target = Database(target_db)
    source: sqlite3.Connection | None = None
    cursor = 0
    log.info("Syncing %s -> %s", source_db, target_db)
    while True:
        try:
            if source is None:
                # rw, not the default: reads the WAL DB but won't create an empty
                # file shadowing BirdNET-Go's if it hasn't written yet.
                source = sqlite3.connect(f"file:{source_db}?mode=rw", uri=True)
                source.row_factory = sqlite3.Row
            cursor = sync_once(source, target, cursor)
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
        help="BirdNET-Go's SQLite file",
    )
    parser.add_argument(
        "--db", type=Path, default=Path("data/detections.db"),
        help="the frame's detections DB to write into",
    )
    args = parser.parse_args(argv)
    run(args.source, args.db)


if __name__ == "__main__":
    main()
