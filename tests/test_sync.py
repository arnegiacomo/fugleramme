"""Syncer invariants: epoch->UTC mapping and idempotent copying of detections."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from fugleramme.db import Database
from fugleramme.sync import sync_once


def _fake_birdnet(detections: list[tuple[int, int, int, float, str | None]]) -> sqlite3.Connection:
    """Minimal BirdNET-Go schema: detections join labels/label_types.
    detections rows are (id, label_id, detected_at_epoch, confidence, clip_name)."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        "CREATE TABLE label_types (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE labels (id INTEGER PRIMARY KEY, scientific_name TEXT, label_type_id INTEGER);"
        "CREATE TABLE detections (id INTEGER PRIMARY KEY, label_id INTEGER, "
        "detected_at INTEGER, confidence REAL, clip_name TEXT);"
        "INSERT INTO label_types VALUES (1,'species'),(2,'noise');"
        "INSERT INTO labels VALUES (10,'Turdus merula',1),(11,'Parus major',1),(12,'Static',2);"
    )
    conn.executemany("INSERT INTO detections VALUES (?, ?, ?, ?, ?)", detections)
    return conn


def test_sync_maps_epoch_and_skips_non_species(tmp_path):
    source = _fake_birdnet([
        (1, 10, 1_752_573_600, 0.9, None),        # Turdus merula, species
        (2, 11, 1_752_573_630, 0.8, "clip.wav"),  # Parus major, species
        (3, 12, 1_752_573_660, 0.7, None),        # Static, noise -> filtered out
    ])
    target = Database(tmp_path / "detections.db")

    cursor = sync_once(source, target, 0)

    # Cursor tracks the max species id returned; the noise row is filtered out in
    # SQL, never returned, and a later species row (id > 2) is still picked up.
    assert cursor == 2
    recent = target.recent()
    assert {d.scientific_name for d in recent} == {"Turdus merula", "Parus major"}
    parus = next(d for d in recent if d.scientific_name == "Parus major")
    assert parus.clip_path == "clip.wav"
    assert parus.detected_at == datetime.fromtimestamp(1_752_573_630, tz=timezone.utc)


def test_sync_is_idempotent_after_source_reset(tmp_path):
    """Re-running from cursor 0 (as when the tmpfs source DB is recreated) must
    not duplicate rows already in detections."""
    rows = [(1, 10, 1_752_573_600, 0.9, None)]
    target = Database(tmp_path / "detections.db")

    sync_once(_fake_birdnet(rows), target, 0)
    sync_once(_fake_birdnet(rows), target, 0)  # source reset, cursor back to 0

    assert len(target.recent()) == 1
