"""Adapter invariants: the frame reads BirdNET-Go's schema read-only, mapping
epoch->UTC, joining species names, filtering non-species, and windowing to 24h."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from fugleramme.db import Database


def _birdnet_db(path, detections):
    """Write a minimal BirdNET-Go-shaped DB. `detections` rows are
    (id, label_id, detected_at_epoch, confidence, clip_name)."""
    conn = sqlite3.connect(path)
    conn.executescript(
        "CREATE TABLE label_types (id INTEGER PRIMARY KEY, name TEXT);"
        "CREATE TABLE labels (id INTEGER PRIMARY KEY, scientific_name TEXT, label_type_id INTEGER);"
        "CREATE TABLE detections (id INTEGER PRIMARY KEY, label_id INTEGER, "
        "detected_at INTEGER, confidence REAL, clip_name TEXT);"
        "INSERT INTO label_types VALUES (1,'species'),(2,'noise');"
        "INSERT INTO labels VALUES (10,'Turdus merula',1),(11,'Parus major',1),(12,'Static',2);"
    )
    conn.executemany("INSERT INTO detections VALUES (?, ?, ?, ?, ?)", detections)
    conn.commit()
    conn.close()


def test_join_epoch_and_species_filter(tmp_path):
    db_path = tmp_path / "birdnet.db"
    _birdnet_db(db_path, [
        (1, 10, 1_752_573_600, 0.9, None),        # Turdus merula, species
        (2, 11, 1_752_573_630, 0.8, "clip.wav"),  # Parus major, species
        (3, 12, 1_752_573_660, 0.7, None),        # Static, noise -> filtered out
    ])
    db = Database(db_path)

    recent = db.recent()
    assert {d.scientific_name for d in recent} == {"Turdus merula", "Parus major"}
    parus = next(d for d in recent if d.scientific_name == "Parus major")
    assert parus.clip_path == "clip.wav"
    assert parus.detected_at == datetime.fromtimestamp(1_752_573_630, tz=timezone.utc)

    stats = db.stats()
    assert stats["total"] == 2          # noise excluded
    assert stats["species"] == 2
    db.close()


def test_species_since_window(tmp_path):
    now = datetime.now(timezone.utc)
    recent_epoch = int((now - timedelta(hours=1)).timestamp())
    stale_epoch = int((now - timedelta(hours=30)).timestamp())
    db_path = tmp_path / "birdnet.db"
    _birdnet_db(db_path, [
        (1, 10, recent_epoch, 0.9, None),   # inside default 24h window
        (2, 10, recent_epoch, 0.8, None),   # inside window, same species
        (3, 11, stale_epoch, 0.7, None),    # outside 24h, inside 48h
    ])
    db = Database(db_path)

    assert db.species_since() == [("Turdus merula", 2)]
    assert db.species_since(hours=48) == [("Turdus merula", 2), ("Parus major", 1)]
    assert db.stats()["last_24h"] == 2
    assert db.stats()["total"] == 3         # stale row still counts in totals
    db.close()


def test_missing_db_reads_empty(tmp_path):
    """The frame may start before BirdNET-Go creates the DB - reads are empty,
    not an error, so the render loop keeps going."""
    db = Database(tmp_path / "does-not-exist.db")
    assert db.species_since() == []
    assert db.recent() == []
    assert db.latest() is None
    assert db.stats()["total"] == 0
