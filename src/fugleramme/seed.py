"""Seed BirdNET-Go-shaped fixtures for a hardware-free dev loop.

Writes the minimal slice the read adapter joins on (`label_types`, `labels`,
`detections`) with fake detections, plus the species-name cache the language
settings read - together, everything the frame would otherwise need a
running BirdNET-Go for. Re-runnable: appends detections, reusing the reference
rows, and leaves an existing names cache alone.

Usage:
    python -m fugleramme.seed --count 20      # writes to detector/data/birdnet.db
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import DEFAULT_CONFIG_PATH, DEFAULT_DB_PATH
from .languages import cache_path

# Common Norwegian species; some without artwork (Cyanistes, Erithacus), which the collage omits.
SPECIES = [
    "Turdus merula",
    "Parus major",
    "Fringilla coelebs",
    "Pica pica",
    "Passer domesticus",
    "Cyanistes caeruleus",
    "Erithacus rubecula",
    "Corvus cornix",
]

# Two languages for those species, as BirdNET-Go's own dictionaries give them:
# lowercase in Norwegian, titled in English. code -> (display name, {species: name})
NAMES: dict[str, tuple[str, dict[str, str]]] = {
    "nb": ("Norwegian", {
        "Turdus merula": "svarttrost",
        "Parus major": "kjøttmeis",
        "Fringilla coelebs": "bokfink",
        "Pica pica": "skjære",
        "Passer domesticus": "gråspurv",
        "Cyanistes caeruleus": "blåmeis",
        "Erithacus rubecula": "rødstrupe",
        "Corvus cornix": "kråke",
    }),
    "en": ("English", {
        "Turdus merula": "Eurasian Blackbird",
        "Parus major": "Great Tit",
        "Fringilla coelebs": "Common Chaffinch",
        "Pica pica": "Eurasian Magpie",
        "Passer domesticus": "House Sparrow",
        "Cyanistes caeruleus": "Eurasian Blue Tit",
        "Erithacus rubecula": "European Robin",
        "Corvus cornix": "Hooded Crow",
    }),
}

# Minimal slice of BirdNET-Go's normalized schema - only the columns db.py reads.
_SCHEMA = """
CREATE TABLE IF NOT EXISTS label_types (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS labels (
    id              INTEGER PRIMARY KEY,
    scientific_name TEXT NOT NULL,
    label_type_id   INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS detections (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    label_id    INTEGER NOT NULL,
    detected_at INTEGER NOT NULL,   -- epoch seconds UTC
    confidence  REAL NOT NULL,
    clip_name   TEXT
);
CREATE TABLE IF NOT EXISTS detection_reviews (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    detection_id INTEGER NOT NULL,
    verified     TEXT NOT NULL      -- 'correct' | 'false_positive'
);
"""


def seed(path: Path, count: int) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")  # mirror BirdNET-Go
        conn.executescript(_SCHEMA)
        conn.execute("INSERT OR IGNORE INTO label_types (id, name) VALUES (1, 'species')")
        label_id = {}
        for i, name in enumerate(SPECIES, start=1):
            conn.execute(
                "INSERT OR IGNORE INTO labels (id, scientific_name, label_type_id) "
                "VALUES (?, ?, 1)",
                (i, name),
            )
            label_id[name] = i
        now = datetime.now(UTC)
        for i in range(count):
            name = random.choice(SPECIES)
            when = int((now - timedelta(minutes=i * 7)).timestamp())
            cur = conn.execute(
                "INSERT INTO detections (label_id, detected_at, confidence, clip_name) "
                "VALUES (?, ?, ?, NULL)",
                (label_id[name], when, round(random.uniform(0.6, 0.98), 2)),
            )
            # Mark a fraction "incorrect" so the frame's false_positive filter is exercised.
            if random.random() < 0.15:
                conn.execute(
                    "INSERT INTO detection_reviews (detection_id, verified) "
                    "VALUES (?, 'false_positive')",
                    (cur.lastrowid,),
                )
        conn.commit()
        # Fold the WAL into the main file so the read-only frame sees the rows.
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        return count
    finally:
        conn.close()


def seed_names(cache_dir: Path, force: bool = False) -> list[str]:
    """Write the names cache languages.py reads, so a container-less loop still
    has languages. Returns the files written.

    The blank ETag is deliberate: languages.py refetches unconditionally, so the
    first real BirdNET-Go to answer replaces the fixture with its own 6.5k names.
    Existing files are kept unless forced - a fetched cache is the better copy.
    """
    written = []
    files: dict[str, dict] = {
        "languages": {"languages": {code: display for code, (display, _) in NAMES.items()}}
    }
    files |= {code: {"etag": "", "names": names} for code, (_, names) in NAMES.items()}
    for name, payload in files.items():
        path = cache_path(cache_dir, name)
        if path.exists() and not force:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        written.append(name)
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--count", type=int, default=20)
    parser.add_argument(
        "--names", action=argparse.BooleanOptionalAction, default=True,
        help="also seed the species-name cache",
    )
    parser.add_argument(
        "--names-dir", type=Path, default=DEFAULT_CONFIG_PATH.parent,
        help="where the names cache goes: the settings file's directory, as the frame reads it",
    )
    parser.add_argument(
        "--force", action="store_true", help="replace an existing names cache"
    )
    args = parser.parse_args()

    n = seed(args.db, args.count)
    print(f"seeded {n} detections into {args.db}")
    if args.names:
        written = seed_names(args.names_dir, args.force)
        print(
            f"seeded names ({', '.join(written)}) under {args.names_dir}" if written
            else f"names cache already present under {args.names_dir}"
        )


if __name__ == "__main__":
    main()
