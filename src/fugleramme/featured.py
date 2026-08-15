"""Which bird gets the day's page.

A walk over the life list rather than a roll: the longest-unshown species is
next, so every bird has its page before any bird has a second one, and a species
heard for the first time jumps the queue. The walk is persisted, since a restart
re-picking would put a different bird on the wall mid-morning.

The pick is a function of the stored walk and the day, so the kiosk computes the
same answer as the render loop without writing - only the loop commits, like
picks.py.

A bird also carries how many laps of the walk it has had, which is what lets a
species with several plates wear a different one each time round. Today's lap is
stored with today's bird rather than derived: the counter has already moved on by
the time the kiosk asks, and the two must agree.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

FILENAME = "featured.json"


def _counts(raw) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    return {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, int)}


class Featured:
    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            raw = {}
        self._day = raw.get("day") if isinstance(raw.get("day"), int) else None
        self._name = raw.get("name") if isinstance(raw.get("name"), str) else None
        self._lap = raw.get("lap") if isinstance(raw.get("lap"), int) else 0
        self._shown = _counts(raw.get("shown"))
        self._laps = _counts(raw.get("laps"))

    def choose(
        self, day: int, candidates: list[str], commit: bool = False
    ) -> tuple[str, int] | None:
        """Today's bird and how many laps of the walk it has already had, or None
        with nothing to choose from. `candidates` are in life-list order, which
        breaks ties on the first pass so the walk starts with the first bird ever
        heard."""
        with self._lock:
            if self._day == day and self._name in candidates:
                return self._name, self._lap
            if not candidates:
                return None
            # -1, not 0: day 0 is a real ordinal, and a bird shown then would
            # read as never shown.
            pick = min(
                range(len(candidates)),
                key=lambda i: (self._shown.get(candidates[i], -1), i),
            )
            name = candidates[pick]
            lap = self._laps.get(name, 0)
            if commit:
                self._day, self._name, self._lap = day, name, lap
                self._shown[name] = day
                self._laps[name] = lap + 1
                self._write()
            return name, lap

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = {
            "day": self._day,
            "name": self._name,
            "lap": self._lap,
            "shown": dict(sorted(self._shown.items())),
            "laps": dict(sorted(self._laps.items())),
        }
        tmp.write_text(json.dumps(payload, indent=2) + "\n")
        os.replace(tmp, self.path)
