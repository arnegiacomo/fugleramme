"""The /frame.e6 wire format: what a microcontroller streams to an
external e-ink panel without looking at it, so every byte has to land
where the controller expects it."""

from __future__ import annotations

import struct
import zlib

import numpy as np
from PIL import Image

from fugleramme import e6


def _page(rows: list[list[int]]) -> Image.Image:
    """A dithered page, as palette indices."""
    pixels = np.array(rows, dtype=np.uint8)
    height, width = pixels.shape
    return Image.frombytes("P", (width, height), pixels.tobytes())


def test_the_header_is_20_little_endian_bytes():
    data = e6.encode(_page([[0, 1, 2, 3, 4, 5, 0, 1], [5, 4, 3, 2, 1, 0, 5, 4]]), 90, poll=15)

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


def test_the_payload_is_the_controllers_codes_in_two_halves():
    """Black, white, yellow, red, blue, green become 0, 1, 2, 3, 5, 6; the left
    pixel takes the high nibble; every row's left half, then every row's right."""
    # A quarter turn back from 90 is the glass's own portrait: the page as it hangs.
    data = e6.encode(_page([[0, 1, 2, 3, 4, 5, 0, 1], [5, 4, 3, 2, 1, 0, 5, 4]]), 90, poll=0)

    left = bytes([0x01, 0x23, 0x65, 0x32])
    right = bytes([0x56, 0x01, 0x10, 0x65])
    assert data[20:] == left + right


def test_a_landscape_page_turns_a_quarter_clockwise_onto_the_glass():
    """How Pimoroni's driver turns the same glass: the page's left column, bottom
    to top, is the glass's first row."""
    data = e6.encode(_page([[0, 1], [2, 3], [4, 5], [0, 0]]), 0, poll=0)

    width, height = struct.unpack_from("<HH", data, 8)
    assert (width, height) == (4, 2)
    # Rows 0 5 2 0 and 0 6 3 1, split at the middle.
    assert data[20:] == bytes([0x05, 0x06, 0x20, 0x31])


def test_the_13_inch_page_fills_the_glass_exactly():
    data = e6.encode(Image.new("P", (1600, 1200), 1), 0, poll=0)

    assert struct.unpack_from("<HHI", data, 8) == (1200, 1600, 960_000)
    assert len(data) == 20 + 960_000
    assert set(data[20:]) == {0x11}  # white everywhere
