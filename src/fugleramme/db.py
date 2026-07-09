"""SQLite data access for detections.

WAL mode makes power-loss corruption a non-issue on the Pi. For the Mac dev
slice we own this table; the phase-2 detector (BirdNET-Go) will populate the
same shape. This module is a pure data-access layer - seeding lives in
`fugleramme.seed`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS detections (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    detected_at     TEXT    NOT NULL,   -- ISO 8601 UTC
    scientific_name TEXT    NOT NULL,   -- as emitted by the detector, e.g. "Turdus merula"
    confidence      REAL    NOT NULL,
    clip_path       TEXT               -- optional audio clip on disk
);
CREATE INDEX IF NOT EXISTS idx_detections_detected_at
    ON detections (detected_at DESC);
"""


@dataclass(frozen=True)
class Detection:
    id: int
    detected_at: datetime
    scientific_name: str
    confidence: float
    clip_path: str | None


def _row_to_detection(row: sqlite3.Row) -> Detection:
    return Detection(
        id=row["id"],
        detected_at=datetime.fromisoformat(row["detected_at"]),
        scientific_name=row["scientific_name"],
        confidence=row["confidence"],
        clip_path=row["clip_path"],
    )


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def insert(
        self,
        scientific_name: str,
        confidence: float,
        detected_at: datetime | None = None,
        clip_path: str | None = None,
    ) -> int:
        when = (detected_at or datetime.now(timezone.utc)).isoformat()
        cur = self.conn.execute(
            "INSERT INTO detections (detected_at, scientific_name, confidence, clip_path) "
            "VALUES (?, ?, ?, ?)",
            (when, scientific_name, confidence, clip_path),
        )
        self.conn.commit()
        return cur.lastrowid

    def latest(self) -> Detection | None:
        row = self.conn.execute(
            "SELECT * FROM detections ORDER BY detected_at DESC, id DESC LIMIT 1"
        ).fetchone()
        return _row_to_detection(row) if row else None

    def recent(self, limit: int = 20) -> list[Detection]:
        rows = self.conn.execute(
            "SELECT * FROM detections ORDER BY detected_at DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [_row_to_detection(r) for r in rows]

    def species_last_24h(self) -> list[tuple[str, int]]:
        """Distinct species seen in the last 24h with their detection count,
        most frequent first. Drives the kiosk collage."""
        since = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        rows = self.conn.execute(
            "SELECT scientific_name, COUNT(*) AS n FROM detections "
            "WHERE detected_at >= ? GROUP BY scientific_name ORDER BY n DESC, scientific_name",
            (since,),
        ).fetchall()
        return [(r["scientific_name"], r["n"]) for r in rows]

    def stats(self) -> dict:
        """Aggregate figures for the dashboard."""
        total = self.conn.execute("SELECT COUNT(*) FROM detections").fetchone()[0]
        species = self.conn.execute(
            "SELECT COUNT(DISTINCT scientific_name) FROM detections"
        ).fetchone()[0]
        since_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
        last_24h = self.conn.execute(
            "SELECT COUNT(*) FROM detections WHERE detected_at >= ?", (since_24h,)
        ).fetchone()[0]
        top = self.conn.execute(
            "SELECT scientific_name, COUNT(*) AS n, MAX(confidence) AS best "
            "FROM detections GROUP BY scientific_name ORDER BY n DESC LIMIT 10"
        ).fetchall()
        return {
            "total": total,
            "species": species,
            "last_24h": last_24h,
            "top": [dict(r) for r in top],
        }
