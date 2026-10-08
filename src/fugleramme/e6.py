"""The panel page packed for an external e-ink panel, so a microcontroller
can stream it to the glass without touching it.

A 20-byte little-endian header, then the payload:

    0  magic "E6F1" (u32)   4  version (u16)       6  encoding (u8)
    7  poll minutes (u8)    8  width (u16)         10 height (u16)
    12 payload length (u32) 16 payload CRC-32 (u32)

Encoding 1 is the controllers' own colour codes, two pixels a byte with the left
one in the high nibble. The glass is driven as two halves: every row's left half
goes to the first controller (CS0), then every row's right half to the second
(CS1), so the payload is those two runs back to back.

The poll is the frame's Panel refresh in minutes, 0 meaning as soon as it
changes: the client sleeps that long between fetches, its own minimum on top.
"""

from __future__ import annotations

import struct
import zlib

import numpy as np
from PIL import Image

from .panel import to_glass

MAGIC = b"E6F1"
VERSION = 1
ENCODING = 1
HEADER = struct.Struct("<4sHBBHHII")

# `dither`'s palette order - black, white, yellow, red, blue, green - to the
# controllers' codes, which skip 4.
_NATIVE = np.array([0, 1, 2, 3, 5, 6], dtype=np.uint8)


def encode(frame: Image.Image, rotation: int, poll: int) -> bytes:
    """The dithered panel page, as it hangs, packed for the glass."""
    # A quarter turn clockwise from the landscape glass, as Pimoroni's driver turns it.
    glass = to_glass(frame, rotation).transpose(Image.Transpose.ROTATE_270)
    pixels = np.asarray(glass, dtype=np.uint8)
    height, width = pixels.shape
    codes = _NATIVE[pixels]
    halves = np.concatenate(np.hsplit(codes, 2))
    payload = ((halves[:, 0::2] << 4) | halves[:, 1::2]).tobytes()
    header = HEADER.pack(
        MAGIC,
        VERSION,
        ENCODING,
        min(poll, 255),
        width,
        height,
        len(payload),
        zlib.crc32(payload),
    )
    return header + payload
