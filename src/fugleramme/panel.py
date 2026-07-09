"""Inky panel init with graceful degrade.

The frame service owns the panel and treats it as optional: if the Inky
library or the physical device is absent (as on the Mac, and per issue #1),
we log a warning and return None so the caller runs web-only. Pushing pixels
is the same rendered image either way. The actual SPI push is exercised in
phase 2 on hardware.
"""

from __future__ import annotations

import logging

from PIL import Image

log = logging.getLogger(__name__)


class Panel:
    def __init__(self, device):
        self._device = device

    def push(self, image: Image.Image) -> None:
        self._device.set_image(image)
        self._device.show()


def init_panel() -> Panel | None:
    """Return a Panel, or None if no Inky is available (web-only mode)."""
    try:
        from inky.auto import auto
    except Exception as exc:  # library not installed (Mac dev loop)
        log.warning("Inky library unavailable (%s); running web-only", exc)
        return None
    try:
        device = auto()
    except Exception as exc:  # library present but no panel wired up
        log.warning("No Inky panel detected (%s); running web-only", exc)
        return None
    log.info("Inky panel initialised: %sx%s", *device.resolution)
    return Panel(device)
