"""Read-only adapter over BirdNET-Go's SQLite.

The only place that knows BirdNET-Go's schema (a `labels`/`label_types` join,
epoch-seconds timestamps). Opened `mode=ro`; the frame reads BirdNET-Go's file
directly. The method surface (`Detection`, `species_since`, `recent`,
`latest`, `stats`) hides the source from callers.
"""

from __future__ import annotations

import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Keep real species only, and drop detections the user marked incorrect in
# BirdNET-Go (verified='false_positive'); unreviewed and correct are kept.
_FROM = (
    "FROM detections d "
    "JOIN labels l ON l.id = d.label_id "
    "JOIN label_types t ON t.id = l.label_type_id "
    "LEFT JOIN detection_reviews rv ON rv.detection_id = d.id "
    "WHERE t.name = 'species' "
    "AND (rv.verified IS NULL OR rv.verified <> 'false_positive')"
)
_COLS = "d.id, d.detected_at, l.scientific_name, d.confidence, d.clip_name"


@dataclass(frozen=True)
class Detection:
    id: int
    detected_at: datetime
    scientific_name: str
    confidence: float
    clip_path: str | None


@dataclass(frozen=True)
class Species:
    scientific_name: str
    count: int
    first_seen: datetime


def _row_to_detection(row: sqlite3.Row) -> Detection:
    return Detection(
        id=row["id"],
        detected_at=datetime.fromtimestamp(row["detected_at"], tz=timezone.utc),
        scientific_name=row["scientific_name"],
        confidence=row["confidence"],
        clip_path=row["clip_name"] or None,
    )


def _epoch_hours_ago(hours: int) -> int:
    return int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp())


class Database:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._uri = f"file:{self.path}?mode=ro"
        self.conn: sqlite3.Connection | None = None
        # Shared across the threaded server's requests; reentrant for _rows -> close.
        self._lock = threading.RLock()

    def _connect(self) -> sqlite3.Connection | None:
        if self.conn is None:
            try:
                conn = sqlite3.connect(self._uri, uri=True, check_same_thread=False)
            except sqlite3.OperationalError:
                return None  # DB not created yet
            conn.row_factory = sqlite3.Row
            self.conn = conn
        return self.conn

    def _rows(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            conn = self._connect()
            if conn is None:
                return []
            try:
                return conn.execute(sql, params).fetchall()
            except sqlite3.OperationalError:
                # Missing/recreated: drop the handle, treat as empty, reconnect next call.
                self.close()
                return []

    def _scalar(self, sql: str, params: tuple = (), default: int = 0) -> int:
        rows = self._rows(sql, params)
        return rows[0][0] if rows else default

    def close(self) -> None:
        with self._lock:
            if self.conn is not None:
                self.conn.close()
                self.conn = None

    def latest(self) -> Detection | None:
        rows = self._rows(
            f"SELECT {_COLS} {_FROM} ORDER BY d.detected_at DESC, d.id DESC LIMIT 1"
        )
        return _row_to_detection(rows[0]) if rows else None

    def recent(self, limit: int = 20) -> list[Detection]:
        rows = self._rows(
            f"SELECT {_COLS} {_FROM} ORDER BY d.detected_at DESC, d.id DESC LIMIT ?",
            (limit,),
        )
        return [_row_to_detection(r) for r in rows]

    def species_since(self, hours: int = 24) -> list[tuple[str, int]]:
        """Distinct species seen in the last `hours` with their detection count,
        most frequent first. Drives the kiosk collage; window is the #2 setting."""
        rows = self._rows(
            f"SELECT l.scientific_name AS scientific_name, COUNT(*) AS n {_FROM} "
            "AND d.detected_at >= ? "
            "GROUP BY l.scientific_name ORDER BY n DESC, l.scientific_name",
            (_epoch_hours_ago(hours),),
        )
        return [(r["scientific_name"], r["n"]) for r in rows]

    def life_list(self, until: int | None = None) -> list[Species]:
        """Every species ever recorded, with its count and the date it was first
        heard, earliest first. `until` cuts the tally off at an epoch: the bird
        of the day counts only what was already true this morning, so its page
        does not re-render every time the bird calls again."""
        where = " AND d.detected_at < ?" if until is not None else ""
        rows = self._rows(
            f"SELECT l.scientific_name AS scientific_name, COUNT(*) AS n, "
            f"MIN(d.detected_at) AS first {_FROM}{where} "
            "GROUP BY l.scientific_name ORDER BY first, l.scientific_name",
            (until,) if until is not None else (),
        )
        return [
            Species(
                scientific_name=r["scientific_name"],
                count=r["n"],
                first_seen=datetime.fromtimestamp(r["first"], tz=timezone.utc),
            )
            for r in rows
        ]

    def stats(self) -> dict:
        """Aggregate figures for the dashboard."""
        top = self._rows(
            "SELECT l.scientific_name AS scientific_name, COUNT(*) AS n, "
            f"MAX(d.confidence) AS best {_FROM} "
            "GROUP BY l.scientific_name ORDER BY n DESC LIMIT 10"
        )
        return {
            "total": self._scalar(f"SELECT COUNT(*) {_FROM}"),
            "species": self._scalar(f"SELECT COUNT(DISTINCT l.scientific_name) {_FROM}"),
            "last_24h": self._scalar(
                f"SELECT COUNT(*) {_FROM} AND d.detected_at >= ?", (_epoch_hours_ago(24),)
            ),
            "top": [dict(r) for r in top],
        }
