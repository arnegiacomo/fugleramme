"""Which bird gets the day's page.

A walk over the life list rather than a roll: the longest-unshown species is
next, so every bird has its page before any bird has a second one, and a species
heard for the first time jumps the queue. The walk is persisted, since a restart
re-picking would put a different bird on the wall mid-morning.

The pick is a function of the stored walk and the day, so the kiosk computes the
same answer as the render loop without writing - only the loop commits, like
picks.py.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path

FILENAME = "featured.json"


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
        shown = raw.get("shown")
        self._shown: dict[str, int] = (
            {k: v for k, v in shown.items() if isinstance(k, str) and isinstance(v, int)}
            if isinstance(shown, dict) else {}
        )

    def choose(self, day: int, candidates: list[str], commit: bool = False) -> str | None:
        """Today's bird, or None with nothing to choose from. `candidates` are in
        life-list order, which breaks ties on the first pass so the walk starts
        with the first bird ever heard."""
        with self._lock:
            if self._day == day and self._name in candidates:
                return self._name
            if not candidates:
                return None
            # -1, not 0: day 0 is a real ordinal, and a bird shown then would
            # read as never shown.
            pick = min(
                range(len(candidates)),
                key=lambda i: (self._shown.get(candidates[i], -1), i),
            )
            name = candidates[pick]
            if commit:
                self._day, self._name = day, name
                self._shown[name] = day
                self._write()
            return name

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        payload = {"day": self._day, "name": self._name, "shown": dict(sorted(self._shown.items()))}
        tmp.write_text(json.dumps(payload, indent=2) + "\n")
        os.replace(tmp, self.path)
