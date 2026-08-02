"""Live service state, written by the render loop and read by the admin view.

Plain attribute writes from one thread, reads from another: the GIL makes each
assignment atomic, and a stale read is one poll tick old at worst.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def _now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class Status:
    started_at: datetime = field(default_factory=_now)
    rendered_at: datetime | None = None
    push_error: str | None = None
    # Update state: the admin view writes `requested`, the loop does the work.
    update_available: str | None = None
    update_requested: str | None = None
    updating: bool = False
    update_error: str | None = None

    def rendered(self) -> None:
        self.rendered_at = _now()
