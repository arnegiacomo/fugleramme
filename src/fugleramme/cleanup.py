"""Tidy what earlier releases left behind on a frame.

An update never re-runs run.sh (`updates.apply`), so a file or a setting a
release stops using stays on every frame that updated into it. Each task here
removes one such leftover, and startup is the one place that reaches every
frame however it updated. The render loop calls `start` after its first render,
so cleanup never delays startup or competes with that render.

A task is a dated function. The date is three months after the release that
made it, when every frame has had its chance to run it, and its entry can go.
Nothing enforces it. Every task must be safe to run again on every startup.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Task:
    name: str
    remove_after: date
    run: Callable[[Path], None]  # handed the data dir


def _artwork_picks(data_dir: Path) -> None:
    # Per-bird variant picks, unread since the pick went by day (#302).
    (data_dir / "artwork.json").unlink(missing_ok=True)


TASKS = (Task("artwork.json", date(2027, 1, 21), _artwork_picks),)


def run(data_dir: Path) -> None:
    """Every task in turn. One failing is logged and skipped, never fatal."""
    for task in TASKS:
        try:
            task.run(data_dir)
        except Exception:
            log.exception("Cleanup task %s failed", task.name)


def start(data_dir: Path) -> None:
    """`run` on a daemon thread, so a slow SD card never holds up the loop."""
    threading.Thread(target=run, args=(data_dir,), name="cleanup", daemon=True).start()
