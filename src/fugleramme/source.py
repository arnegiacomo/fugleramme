"""Where detections come from, as the rest of the frame sees them.

One protocol over BirdNET-Go, so nothing above it knows whether the detector is
the container beside it or an install across the house. `api.ApiSource` is the
implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

# What a detector refusing the frame wants, in the one wording every surface
# uses: the admin's Detector row, its language menu, and `fugleramme-check`.
NEEDS_PASSWORD = "needs a password"


class Unavailable(Exception):
    """The detector could not be reached, or answered with something else.

    Never confuse this with an empty result: empty means the detector answered
    and there were genuinely no birds. A source that returned [] on a timeout
    would collapse the collage to a bare perch and push that to the glass.
    """


@dataclass(frozen=True)
class Detection:
    id: int
    detected_at: datetime
    scientific_name: str
    confidence: float
    clip_path: str | None


@dataclass(frozen=True)
class Species:
    scientific_name: str
    first_seen: datetime


class Source(Protocol):
    @property
    def base_url(self) -> str:
        """Which detector this is. Anything held from one station is not the
        answer for another, so callers key their caches on it."""

    def latest(self) -> Detection | None: ...

    def recent(self, limit: int = 20) -> list[Detection]: ...

    def species_since(self, hours: int = 24) -> list[tuple[str, int]]:
        """Species heard in the last `hours` with their detection count, most
        frequent first then by name. `hours` of 0 or less is not a window:
        every species ever heard."""
        ...

    def life_list(self) -> list[Species]:
        """Every species ever recorded with the date it was first heard, earliest first."""
        ...

    def stats(self) -> dict: ...

    def close(self) -> None: ...
