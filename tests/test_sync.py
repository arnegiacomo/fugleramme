"""Syncer invariants: local->UTC conversion and idempotent copying of notes."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fugleramme.db import Database
from fugleramme.sync import sync_once, to_utc

OSLO = ZoneInfo("Europe/Oslo")


def test_to_utc_handles_dst():
    # Winter: Oslo is UTC+1, so 12:00 local -> 11:00 UTC.
    assert to_utc("2026-01-15", "12:00:00", OSLO) == datetime(2026, 1, 15, 11, tzinfo=timezone.utc)
    # Summer: Oslo is UTC+2, so 12:00 local -> 10:00 UTC.
    assert to_utc("2026-07-15", "12:00:00", OSLO) == datetime(2026, 7, 15, 10, tzinfo=timezone.utc)


def _source_with_notes(rows: list[tuple[int, str, str, str, float, str | None]]) -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        "CREATE TABLE notes (id INTEGER PRIMARY KEY, date TEXT, time TEXT, "
        "scientific_name TEXT, confidence REAL, clip_name TEXT)"
    )
    conn.executemany("INSERT INTO notes VALUES (?, ?, ?, ?, ?, ?)", rows)
    return conn


def test_sync_maps_and_advances_cursor(tmp_path):
    source = _source_with_notes([
        (1, "2026-07-15", "12:00:00", "Turdus merula", 0.9, None),
        (2, "2026-07-15", "12:00:30", "Parus major", 0.8, "clip.wav"),
    ])
    target = Database(tmp_path / "detections.db")

    cursor = sync_once(source, target, OSLO, 0)

    assert cursor == 2
    recent = target.recent()
    assert {d.scientific_name for d in recent} == {"Turdus merula", "Parus major"}
    parus = next(d for d in recent if d.scientific_name == "Parus major")
    assert parus.clip_path == "clip.wav"
    assert parus.detected_at == datetime(2026, 7, 15, 10, 0, 30, tzinfo=timezone.utc)


def test_sync_is_idempotent_after_source_reset(tmp_path):
    """Re-running from cursor 0 (as happens when the tmpfs source DB is recreated)
    must not duplicate rows already in detections."""
    rows = [(1, "2026-07-15", "12:00:00", "Turdus merula", 0.9, None)]
    target = Database(tmp_path / "detections.db")

    sync_once(_source_with_notes(rows), target, OSLO, 0)
    sync_once(_source_with_notes(rows), target, OSLO, 0)  # source reset, cursor back to 0

    assert len(target.recent()) == 1
