"""Live service state, written by the render loop and read by the admin view.

Plain attribute writes from one thread, reads from another: the GIL makes each
assignment atomic, and a stale read is one poll tick old at worst.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from PIL import Image

from .settings import Settings
from .wifi import State as WifiState

# The panel page as dithered, and the rotation it hangs at.
Frame = tuple[Image.Image, int]

MAT_TEST_SECONDS = 5 * 60  # long enough to hold a mat up to the glass, short enough to forget


@dataclass(frozen=True)
class MatTest:
    """Unsaved margins shown on the panel and the kiosk with their band painted, so a mat
    can be held up to them. In memory only: a restart or a Save ends it."""

    margin: int  # for a page that takes no edges
    edges: tuple[int, int, int, int]  # the glass's, unrotated, as `Settings.glass_margins`
    until: float  # time.monotonic()


def under_test(settings: Settings, test: MatTest | None) -> Settings:
    """Settings with the test's margins in place of the saved ones."""
    if test is None:
        return settings
    top, right, bottom, left = test.edges
    return replace(
        settings,
        margin=test.margin,
        margin_lock=False,
        margin_top=top,
        margin_right=right,
        margin_bottom=bottom,
        margin_left=left,
    )


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
    # The Wi-Fi setup's, published by its own thread; None where there is none (#308).
    wifi: WifiState | None = None
    # The admin writes it; read it through `testing`.
    mat_test: MatTest | None = None

    def testing(self) -> MatTest | None:
        """The margin test while it runs, dropped once it runs out."""
        test = self.mat_test
        if test is not None and time.monotonic() >= test.until:
            self.mat_test = test = None
        return test

    def rendered(self, frame: Frame) -> None:
        self.rendered_at = _now()
        self.frame = frame
