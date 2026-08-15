"""Which of a style's images each species is currently wearing.

A style may hold several images for one bird. Rolling the dice per render made
the whole page churn - a new species, a shifted detection count or a restart
reshuffled every bird. Rolling once per species and holding it for as long as
that bird is in the window means the frame only changes when the birds do. The
pick is dropped when the species leaves the window, so a bird that returns
tomorrow returns in a different picture.

Persisted next to the settings file: a restart re-rolling everything is exactly
the churn this exists to remove. Shared by the render loop and the HTTP server
in one process, so writes take the lock like SettingsStore's do.
"""

from __future__ import annotations

import json
import os
import random
import threading
from collections.abc import Iterable
from pathlib import Path

FILENAME = "artwork.json"


class Picks:
    """Species -> the artwork filename it is wearing, held across renders."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._lock = threading.Lock()
        try:
            raw = json.loads(self.path.read_text())
        except (OSError, json.JSONDecodeError):
            raw = {}
        self._held = {k: v for k, v in raw.items() if isinstance(k, str) and isinstance(v, str)}

    def choose(self, name: str, variants: list[Path]) -> Path | None:
        """The image this species is wearing. Held if it is still one of the
        style's variants (a re-curation or a style switch drops it), else a
        fresh roll."""
        if not variants:
            return None
        by_name = {path.name: path for path in variants}
        with self._lock:
            held = by_name.get(self._held.get(name, ""))
            if held is not None:
                return held
            chosen = random.choice(variants)
            self._held[name] = chosen.name
            self._write()
            return chosen

    def retain(self, names: Iterable[str]) -> None:
        """Forget every species that has left the window, so its next visit
        rolls again. Only the render loop calls this: the kiosk and the admin
        preview can be looking at a different window."""
        keep = set(names)
        with self._lock:
            if self._held.keys() <= keep:
                return
            self._held = {k: v for k, v in self._held.items() if k in keep}
            self._write()

    def _write(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(dict(sorted(self._held.items())), indent=2) + "\n")
        os.replace(tmp, self.path)
