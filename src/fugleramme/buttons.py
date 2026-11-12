"""The panel's four buttons, wired to presentation settings.

The inky library has no button API - they are plain GPIO lines on the panel
board, read here with gpiod. A press is nothing but a settings write, so no
state crosses threads and presses during the slow e-ink refresh coalesce into
one re-render.

A press fires on release, so holding A for `HOLD` can open or close the Wi-Fi
setup (#308) without also changing the mode. The hold fires while A is still down.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import timedelta
from functools import partial
from pathlib import Path

from .modes import MODES
from .names import available_styles
from .settings import Settings, SettingsStore

log = logging.getLogger(__name__)

LABELS = ("A", "B", "C", "D")  # top to bottom, unrotated

# BCM lines per label. The 13.3" is the odd one out - its C is on 25, not 16.
_PINS = (5, 6, 16, 24)
_PINS_13_3 = (5, 6, 25, 24)

_DEBOUNCE = timedelta(milliseconds=50)

HOLD = 5.0  # seconds A is held to open or close the Wi-Fi setup


def pins_for(driver: str) -> tuple[int, ...]:
    """Button lines for a panel, keyed on its driver module."""
    return _PINS_13_3 if "el133uf1" in driver else _PINS


def _next(current: str, options: list[str]) -> str:
    """The one after `current`, wrapping. An unset or stale value starts over."""
    index = options.index(current) + 1 if current in options else 0
    return options[index % len(options)]


def changes_for(label: str, settings: Settings, images_dir: Path) -> dict | None:
    """The settings a press writes, or None if the button does nothing."""
    if label == "A":
        return {"mode": _next(settings.mode, list(MODES))}
    if label == "B":
        return {"show_names": not settings.show_names}
    if label == "C":
        # settings.rotation is counter-clockwise; a press turns the picture clockwise.
        return {"rotation": (settings.rotation - 90) % 360}
    if label == "D":
        available = available_styles(images_dir)
        return {"style": _next(settings.style, available)} if available else None
    return None


def press(label: str, store: SettingsStore, images_dir: Path) -> None:
    """Apply one press, persisting it like an admin edit would."""
    changes = changes_for(label, store.get(), images_dir)
    if changes is None:
        log.info("Button %s: unbound", label)
        return
    store.update(**changes)
    log.info("Button %s: %s", label, changes)


class Presses:
    """Which edges make a press, apart from the GPIO so a test can drive it. A button
    presses when it is let go; A held past HOLD fires its hold instead, once, while still
    held, and its release then does nothing. Without a hold, A presses like the others."""

    def __init__(self, hold: bool):
        self._hold = hold
        self._down: dict[str, float] = {}
        self._held = False

    def down(self, label: str, at: float) -> None:
        self._down[label] = at

    def up(self, label: str) -> bool:
        """Whether this release is a press."""
        pressed = self._down.pop(label, None) is not None
        if label == "A" and self._held:
            self._held = False
            return False
        return pressed

    def wait(self, now: float) -> float | None:
        """Seconds until A's hold is due, or None while there is nothing to wait for."""
        if not self._hold or self._held or "A" not in self._down:
            return None
        return max(0.0, self._down["A"] + HOLD - now)

    def held(self, now: float) -> bool:
        """Whether A's hold fires now."""
        if self.wait(now) != 0.0:
            return False
        self._held = True
        return True


def watch(
    driver: str,
    store: SettingsStore,
    images_dir: Path,
    hold: Callable[[], None] | None = None,
) -> None:
    """Block on button edges forever. Returns at once if the GPIO lines are unusable.
    `hold` is what holding A does, if anything."""
    try:
        import gpiod
        import gpiodevice
        from gpiod.line import Bias, Direction, Edge
    except Exception as exc:
        log.warning("gpiod unavailable (%s); running without buttons", exc)
        return

    pins = pins_for(driver)
    try:
        chip = gpiodevice.find_chip_by_platform()
        offsets = [chip.line_offset_from_id(pin) for pin in pins]
        config = dict.fromkeys(
            offsets,
            gpiod.LineSettings(
                direction=Direction.INPUT,
                bias=Bias.PULL_UP,
                edge_detection=Edge.BOTH,
                debounce_period=_DEBOUNCE,
            ),
        )
        request = chip.request_lines(consumer="fugleramme-buttons", config=config)
    except Exception as exc:
        log.warning("Buttons unavailable (%s); running without them", exc)
        return

    log.info("Buttons ready: %s", dict(zip(LABELS, pins, strict=True)))
    presses = Presses(hold is not None)
    while True:
        if request.wait_edge_events(presses.wait(time.monotonic())):
            for event in request.read_edge_events():
                label = LABELS[offsets.index(event.line_offset)]
                # Pulled up, so a press pulls the line down.
                if event.event_type == gpiod.EdgeEvent.Type.FALLING_EDGE:
                    presses.down(label, time.monotonic())
                elif presses.up(label):
                    _safely(label, partial(press, label, store, images_dir))
        if hold is not None and presses.held(time.monotonic()):
            log.info("Button A held")
            _safely("A", hold)


def _safely(label: str, action: Callable[[], None]) -> None:
    try:
        action()
    except Exception:  # a failed write must not take the thread with it
        log.exception("Button %s failed", label)
