"""Fugleramme's page on an Inky Impression, from a Pi that does not run Fugleramme.

It shows the page a Fugleramme on another machine draws. Enable "External
e-ink panel" on that frame's admin page first.
Every POLL_SECONDS it asks the frame for /frame.png with the ETag of the last
page; an unchanged page costs a 304 and nothing else. A new one goes on the
glass once it reads and fits the panel. If the frame cannot be reached, the page
on the glass stays.

/frame.png is the frame's panel page as a six-colour picture, already turned to
the glass, so set_image passes it through without dithering it again. Without
an Inky of its own, the frame lays it out for the 13.3" Impression.

The panel's buttons trigger the corresponding actions on the remote frame via
the /press endpoint. A frame that requires sign-in takes its admin password with
each press.
"""

import io
import logging
import threading
import time
from datetime import timedelta
from http.client import HTTPException
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import config
import gpiod
import gpiodevice
from gpiod.line import Bias, Direction, Edge
from inky.auto import auto
from PIL import Image

# load configuration
FRAME_URL = config.FRAME_URL.rstrip("/")
POLL_SECONDS = config.POLL_SECONDS

TIMEOUT = 30  # a page is a few hundred kilobytes at most, maybe over a slow Wi-Fi

LABELS = ("A", "B", "C", "D")  # top to bottom
# BCM lines per label. The 13.3" is the odd one out - its C is on 25, not 16.
PINS, PINS_13_3 = (5, 6, 16, 24), (5, 6, 25, 24)

log = logging.getLogger("fugleramme")


def press(label: str) -> None:
    """One button, pressed on the frame."""
    fields = {"button": label, "password": config.ADMIN_PASSWORD}
    request = Request(FRAME_URL + "/press", data=urlencode(fields).encode())
    with urlopen(request, timeout=TIMEOUT):
        pass
    log.info("Button %s pressed", label)


def watch(pins: tuple) -> None:
    """Block on button edges forever."""
    chip = gpiodevice.find_chip_by_platform()
    offsets = [chip.line_offset_from_id(pin) for pin in pins]
    line = gpiod.LineSettings(
        direction=Direction.INPUT,
        bias=Bias.PULL_UP,
        edge_detection=Edge.FALLING,
        debounce_period=timedelta(milliseconds=50),
    )
    request = chip.request_lines(consumer="fugleramme-buttons", config=dict.fromkeys(offsets, line))
    while True:
        for event in request.read_edge_events():
            label = LABELS[offsets.index(event.line_offset)]
            try:
                press(label)
            except Exception as error:  # a failed press must not take the buttons with it
                log.warning("Button %s failed: %s", label, error)


def fetch(etag: str):
    """The page and its ETag, or None while it is still `etag`."""
    request = Request(FRAME_URL + "/frame.png", headers={"If-None-Match": etag} if etag else {})
    try:
        with urlopen(request, timeout=TIMEOUT) as response:
            return response.read(), response.headers.get("ETag", "")
    except HTTPError as error:
        if error.code == 304:
            return None
        if error.code == 404:
            raise ValueError("no page there - is External e-ink panel on?") from error
        raise


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    display = auto()
    # Every driver class is named Inky; the module is what identifies the board.
    pins = PINS_13_3 if "el133uf1" in type(display).__module__ else PINS
    threading.Thread(target=watch, args=(pins,), daemon=True).start()
    log.info("Showing the page from %s", FRAME_URL)

    etag = ""
    problem = None
    while True:
        try:
            fetched = fetch(etag)
            if problem:
                log.info("Frame reachable again")
                problem = None
        except (OSError, ValueError, HTTPException) as error:
            # Logged once per cause; the page already on the glass stays.
            cause = f"{type(error).__name__}: {error}"
            if cause != problem:
                log.warning("No page from %s, holding the current one (%s)", FRAME_URL, cause)
                problem = cause
            fetched = None
        if fetched is not None:
            # The ETag is kept for a page that is refused too, so it is not
            # downloaded again until it changes.
            body, etag = fetched
            try:
                page = Image.open(io.BytesIO(body))
                page.load()
                if page.size != tuple(display.resolution):
                    raise ValueError(f"the page is {page.size}, the panel {display.resolution}")
            except (OSError, ValueError) as error:
                log.warning("Page refused: %s", error)
            else:
                display.set_image(page)
                display.show()  # about half a minute on the 13.3"
                log.info("New page on the glass")
        time.sleep(POLL_SECONDS)


main()
