"""The /frame.e6 wire format: what a microcontroller streams to an
external e-ink panel without looking at it, so every byte has to land
where the controller expects it."""

from __future__ import annotations

import struct
import zlib

import numpy as np
import pytest
from PIL import Image

from fugleramme import e6

# A glass turned to how the page hangs at each rotation: what `to_glass` turns back.
_HUNG = {
    90: Image.Transpose.ROTATE_270,
    180: Image.Transpose.ROTATE_180,
    270: Image.Transpose.ROTATE_90,
}


def _page(rows: list[list[int]]) -> Image.Image:
    """A dithered page, as palette indices."""
    pixels = np.array(rows, dtype=np.uint8)
    height, width = pixels.shape
    return Image.frombytes("P", (width, height), pixels.tobytes())


def _marked(width: int, height: int, marks: dict[tuple[int, int], int]) -> Image.Image:
    """A white page with a few pixels, by (x, y), in other palette indices."""
    pixels = np.ones((height, width), dtype=np.uint8)
    for (x, y), index in marks.items():
        pixels[y, x] = index
    return Image.frombytes("P", (width, height), pixels.tobytes())


def test_the_header_is_20_little_endian_bytes():
    data = e6.encode(_page([[0, 1, 2, 3, 4, 5, 0, 1], [5, 4, 3, 2, 1, 0, 5, 4]]), 0, poll=15)

    assert e6.HEADER.size == 20
    assert data[0:4] == b"E6F1"
    assert int.from_bytes(data[4:6], "little") == 1  # version
    assert data[6] == 1  # encoding
    assert data[7] == 15  # poll minutes
    assert int.from_bytes(data[8:10], "little") == 8  # width
    assert int.from_bytes(data[10:12], "little") == 2  # height
    assert int.from_bytes(data[12:16], "little") == len(data) - 20 == 8
    assert int.from_bytes(data[16:20], "little") == zlib.crc32(data[20:])


def test_a_poll_beyond_a_byte_clamps():
    """The admin offers at most an hour, but settings.json takes any number and the
    header has one byte for it."""
    data = e6.encode(_page([[0, 1], [2, 3]]), 0, poll=24 * 60)

    assert data[7] == 255


def test_the_payload_is_the_controllers_codes_two_to_a_byte():
    """Black, white, yellow, red, blue, green become 0, 1, 2, 3, 5, 6, and the left
    pixel takes the high nibble."""
    data = e6.encode(_page([[0, 1, 2, 3, 4, 5, 0, 1], [5, 4, 3, 2, 1, 0, 5, 4]]), 0, poll=0)

    assert data[20:] == bytes([0x01, 0x23, 0x56, 0x01, 0x65, 0x32, 0x10, 0x65])


def test_the_13_inch_page_turns_a_quarter_clockwise_onto_two_controllers():
    """How Pimoroni's driver turns the same glass: the page's left column, bottom
    to top, is the glass's first row. Every row's left half goes to the first
    controller, then every row's right half to the second."""
    page = _marked(1600, 1200, {(0, 1199): 0, (0, 0): 3, (1599, 1199): 4, (1599, 0): 5})
    payload = e6.encode(page, 0, poll=0)[20:]

    half = len(payload) // 2  # 1600 rows of 300 bytes for each controller
    assert payload[0] == 0x01  # bottom left: the first controller's first pixel
    assert payload[half + 299] == 0x13  # top left: the end of the second's first row
    assert payload[half - 300] == 0x51  # bottom right: the first's last row
    assert payload[-1] == 0x16  # top right: the second's last pixel


def test_the_13_inch_page_fills_the_glass_exactly():
    data = e6.encode(Image.new("P", (1600, 1200), 1), 0, poll=0)

    assert struct.unpack_from("<HHI", data, 8) == (1200, 1600, 960_000)
    assert len(data) == 20 + 960_000
    assert set(data[20:]) == {0x11}  # white everywhere


def test_the_7_inch_page_is_its_glass_row_by_row():
    """One controller reads the landscape glass as it is drawn, top row first."""
    page = _marked(800, 480, {(0, 0): 0, (799, 0): 3, (0, 479): 4, (799, 479): 5})
    data = e6.encode(page, 0, poll=0)

    assert struct.unpack_from("<HHI", data, 8) == (800, 480, 192_000)
    payload = data[20:]
    assert payload[0] == 0x01  # top left
    assert payload[399] == 0x13  # top right
    assert payload[479 * 400] == 0x51  # bottom left
    assert payload[-1] == 0x16  # bottom right


def test_a_portrait_7_inch_page_turns_back_onto_its_landscape_glass():
    """Hung at 90°, the page's top right corner is the glass's first pixel."""
    data = e6.encode(_marked(480, 800, {(479, 0): 0}), 90, poll=0)

    assert struct.unpack_from("<HH", data, 8) == (800, 480)
    assert data[20] == 0x01


@pytest.mark.parametrize("size", e6.GLASSES)
@pytest.mark.parametrize("rotation", [90, 180, 270])
def test_a_page_packs_the_same_however_it_hangs(size, rotation):
    """The glass is what gets packed, so a portrait 13.3" page still goes to two
    controllers, and a page hung upside down still lands the right way up."""
    width, height = size
    glass = _marked(width, height, {(0, 0): 0, (width - 1, 0): 3, (0, height - 1): 4})

    assert e6.encode(glass.transpose(_HUNG[rotation]), rotation, poll=0) == e6.encode(
        glass, 0, poll=0
    )
