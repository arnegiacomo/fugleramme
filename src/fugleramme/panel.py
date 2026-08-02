"""Inky panel init and push, with graceful degrade.

The frame service owns the panel and treats it as optional: if the Inky library
or the physical device is absent (as on the Mac), we log a warning and return
None so the caller runs web-only.

The attached panel's own resolution is authoritative for the panel render - the
admin resolution setting is the kiosk's, not the glass's. The render is sized as
the viewer sees it, so `push` turns it back into the panel's native landscape,
which is the only buffer the driver accepts.
"""

from __future__ import annotations

import logging

from PIL import Image

log = logging.getLogger(__name__)

# PIL rotates counter-clockwise, matching how settings.rotation is described.
_TRANSPOSE = {
    90: Image.Transpose.ROTATE_90,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_270,
}


class Panel:
    def __init__(self, device):
        self._device = device
        self.resolution: tuple[int, int] = tuple(device.resolution)
        # Every driver class is named Inky; the module is what identifies the board.
        self.driver: str = type(device).__module__

    def push(self, image: Image.Image, rotation: int = 0) -> None:
        if rotation:
            image = image.transpose(_TRANSPOSE[rotation])
        if image.size != self.resolution:
            raise ValueError(f"image is {image.size}, panel is {self.resolution}")
        self._device.set_image(image)
        self._device.show()  # blocks ~35s on the 13.3" while the panel refreshes


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
    panel = Panel(device)
    log.info("Inky panel initialised: %s %sx%s", panel.driver, *panel.resolution)
    return panel
