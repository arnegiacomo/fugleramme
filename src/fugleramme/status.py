"""Live service state, written by the render loop and read by the admin view.

Plain attribute writes from one thread, reads from another: the GIL makes each
assignment atomic, and a stale read is one poll tick old at worst.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from PIL import Image

# The panel page as dithered, and the rotation it hangs at.
Frame = tuple[Image.Image, int]


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass
class Status:
    started_at: datetime = field(default_factory=_now)
    rendered_at: datetime | None = None
    # For /frame.e6.
    frame: Frame | None = None
    push_error: str | None = None
    # Update state: the admin view writes `requested`, the loop does the work.
    update_available: str | None = None
    update_requested: str | None = None
    updating: bool = False
    update_error: str | None = None
    update_phase: str | None = None
    update_percent: int | None = None
    reboot_error: str | None = None

    def rendered(self, frame: Frame) -> None:
        self.rendered_at = _now()
        self.frame = frame
