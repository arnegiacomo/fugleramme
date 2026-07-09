"""Seed fake detections for a hardware-free dev loop.

Kept out of the data-access layer on purpose: seeding is a dev/ops concern.

Usage:
    python -m fugleramme.seed --db data/detections.db --count 20
"""

from __future__ import annotations

import argparse
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .db import Database

# A handful of common Norwegian species for a believable dashboard. Mixes ones
# with artwork (Turdus merula, Parus major) and ones that will hit the fallback
# card (Cyanistes caeruleus, Erithacus rubecula) so both paths get exercised.
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


def seed(db: Database, count: int) -> list[int]:
    now = datetime.now(timezone.utc)
    ids = []
    for i in range(count):
        ids.append(
            db.insert(
                scientific_name=random.choice(SPECIES),
                confidence=round(random.uniform(0.6, 0.98), 2),
                detected_at=now - timedelta(minutes=i * 7),
            )
        )
    return ids


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed fake detections.")
    parser.add_argument("--db", type=Path, default=Path("data/detections.db"))
    parser.add_argument("--count", type=int, default=20)
    args = parser.parse_args()

    db = Database(args.db)
    try:
        ids = seed(db, args.count)
    finally:
        db.close()
    print(f"seeded {len(ids)} detections into {args.db}")


if __name__ == "__main__":
    main()
