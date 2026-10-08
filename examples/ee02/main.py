"""Fugleramme's page on a Seeed 13.3" Spectra 6 panel, from a XIAO EE02 board.

MicroPython's SEEED_XIAO_ESP32S3 build (it needs the board's octal PSRAM),
copied to the board as main.py. Enable "External e-ink panel" on the frame's admin page
first. Every wake it asks the frame for /frame.e6 with the ETag of the last
frame page on the glass (or none if a notice replaced it); an unchanged page
costs a 304 and nothing else. A new one is downloaded whole, checked, and only
then sent to the panel. Then it sleeps for the poll the page's header carries,
which is the admin's "Panel refresh", never below MIN_SLEEP_MINUTES.

When something goes wrong the panel says so in black on white, once: a page
that does not fit this panel or a frame that is not serving one at once, a
frame it cannot reach only after NOTICE_AFTER wakes in a row, so a restart or
a Wi-Fi blip leaves the birds up. The next page that arrives replaces it.

The file format is in docs/screens.md. The panel's command sequence is ported
from Seeed_GFX2's Driver_T133A01.cpp
(https://github.com/Seeed-Studio/Seeed_GFX2, MIT License, see its LICENSE).
GPIO 43 and 44 double as UART0, so use the USB REPL.
"""

import binascii
import json
import socket
import struct
import time

import framebuf
import machine
import network

# Change to your WiFi credentials
WIFI_SSID = "your-network"
WIFI_PASSWORD = "your-password"

# Change to your Fugleramme setup
FRAME_HOST = "fugleramme.local"
FRAME_PORT = 8080

# The minimum sleep duration between two polls
MIN_SLEEP_MINUTES = 5

# Failed wakes in a row before an unreachable frame is worth a refresh.
NOTICE_AFTER = 3

WIDTH, HEIGHT = 1200, 1600

# /frame.e6: a 20-byte little-endian header, then the left-controller rows
# followed by the right-controller rows.
HEADER = "<4sHBBHHII"
BLACK, WHITE = 0, 1
SCALE, MARGIN = 4, 96  # the built-in font is 8 px, far too small at this size
FRESH = {"etag": "", "shown": "", "failures": 0, "poll": MIN_SLEEP_MINUTES}

# EE02 wiring, from Seeed_GFX2's XIAO_ePaper_Board_Configs.h.
SCK, MOSI = 7, 9  # XIAO D8, D10
CS0, CS1, DC, RST, BUSY, POWER = 44, 41, 10, 38, 4, 43

# Controller-select bit flags for the shared SPI bus.
PRIMARY, SECONDARY, BOTH = 1, 2, 3

# Each row is (controller target, register command, command data), in hardware init order.
INIT = (
    (PRIMARY, 0x74, b"\x00\x0c\x0c\xd9\xdd\xdd\x15\x15\x55"),
    (BOTH, 0xF0, b"\x49\x55\x13\x5d\x05\x10"),
    (BOTH, 0x00, b"\xdf\x69"),
    (PRIMARY, 0xA5, b"\x44\x54\x00"),
    (BOTH, 0x50, b"\x37"),
    (BOTH, 0x60, b"\x03\x03"),
    (BOTH, 0x86, b"\x10"),
    (BOTH, 0xE3, b"\x22"),
    (BOTH, 0x61, b"\x04\xb0\x03\x20"),
    (PRIMARY, 0x01, b"\x0f\x00\x28\x2c\x28\x38"),
    (PRIMARY, 0xB6, b"\x07"),
    (PRIMARY, 0x06, b"\xe0\x20"),
    (PRIMARY, 0xB7, b"\x01"),
    (PRIMARY, 0x05, b"\xe0\x20"),
    (PRIMARY, 0xB0, b"\x01"),
    (PRIMARY, 0xB1, b"\x02"),
)


class Problem(Exception):
    def __init__(self, message: str, lasting: bool = False):
        super().__init__(message)
        self.lasting = lasting


def connect() -> None:
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(WIFI_SSID, WIFI_PASSWORD)
    for _ in range(30):
        if wlan.isconnected():
            return
        time.sleep(1)
    raise Problem(f"Cannot join the Wi-Fi network {WIFI_SSID}.")


def disconnect() -> None:
    network.WLAN(network.STA_IF).active(False)


def read_exactly(sock, buffer) -> None:
    view = memoryview(buffer)
    got = 0
    while got < len(buffer):
        count = sock.readinto(view[got:])
        if not count:
            raise OSError("connection closed early")
        got += count


def fetch(etag: str):
    """Returns (page, poll): page is None when the frame still has the one
    drawn, and poll is None with it, since a page the frame revalidates
    carries the same poll as the one on the glass."""
    address = socket.getaddrinfo(FRAME_HOST, FRAME_PORT)[0][-1]
    sock = socket.socket()
    sock.settimeout(30)
    try:
        sock.connect(address)
        request = f"GET /frame.e6 HTTP/1.0\r\nHost: {FRAME_HOST}\r\n"
        if etag:
            request += f"If-None-Match: {etag}\r\n"
        sock.write((request + "\r\n").encode())
        status = int(sock.readline().split()[1])
        new_etag = ""
        while (line := sock.readline()) not in (b"\r\n", b""):
            name, _, value = line.decode().partition(":")
            if name.strip().lower() == "etag":
                new_etag = value.strip()

        if status == 304:
            # Unchanged: the frame has nothing to send and the glass keeps its birds.
            return None, None
        if status == 404:
            raise Problem(
                'The frame is not serving this panel. Enable "External e-ink '
                'panel" on its admin page, under the "Frame" tab.',
                lasting=True,
            )
        if status == 503:
            raise Problem("The frame has not drawn a page yet.")
        if status != 200:
            raise Problem(f"The frame answered {status}.")

        # The header declares the poll, format, dimensions, payload length and CRC.
        header = bytearray(struct.calcsize(HEADER))
        read_exactly(sock, header)
        magic, version, encoding, poll, width, height, length, crc = struct.unpack(HEADER, header)

        if (magic, version, encoding) != (b"E6F1", 1, 1):
            raise Problem(
                "The frame sends a page this program cannot read.",
                lasting=True,
            )

        # A page for another panel cannot be resized, only refused.
        if (width, height, length) != (WIDTH, HEIGHT, WIDTH * HEIGHT // 2):
            raise Problem(
                f"The frame lays its page out for a {width}x{height} panel, "
                f"this one is {WIDTH}x{HEIGHT}. Is another panel connected "
                "to the frame?",
                lasting=True,
            )

        pixels = bytearray(length)
        read_exactly(sock, pixels)

        # Damaged pixels would smear across an e-ink panel for days; check first.
        if binascii.crc32(pixels) != crc:
            raise Problem("The page arrived damaged.")

        return (pixels, new_etag), poll
    finally:
        sock.close()


def download(etag: str):
    try:
        connect()
        return fetch(etag)
    except Problem:
        raise
    except Exception as error:
        raise Problem(f"Cannot reach the frame at {FRAME_HOST}:{FRAME_PORT} ({error}).") from error
    finally:
        # Wi-Fi is only needed for fetching; keep it off while the panel refreshes.
        disconnect()


def wrap(text: str, width: int) -> list:
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > width:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}" if line else word
    return lines + [line]


def notice(message: str) -> bytearray:
    """A page, packed like /frame.e6's, saying `message` the glass's own way up."""
    pixels = bytearray(WIDTH * HEIGHT // 2)
    half = len(pixels) // 2
    view = memoryview(pixels)
    # Both GS4_HMSB framebuffers view this payload, one packed 4-bit half per controller.
    halves = [
        framebuf.FrameBuffer(view[i * half : (i + 1) * half], WIDTH // 2, HEIGHT, framebuf.GS4_HMSB)
        for i in (0, 1)
    ]
    for glass in halves:
        glass.fill(WHITE)

    glyph = framebuf.FrameBuffer(bytearray(8), 8, 8, framebuf.MONO_HLSB)
    # Rasterize one built-in 8x8 glyph at a time; SCALE enlarges its set pixels below.
    across = WIDTH - 2 * MARGIN

    for row, line in enumerate(wrap(f"Fugleramme: {message}", across // (8 * SCALE))):
        for col, char in enumerate(line):
            glyph.fill(0)
            glyph.text(char, 0, 0, 1)
            for gy in range(8):
                for gx in range(8):
                    if not glyph.pixel(gx, gy):
                        continue
                    x = MARGIN + (col * 8 + gx) * SCALE
                    y = MARGIN + (row * 10 + gy) * SCALE
                    # Both halves get each box; FrameBuffer clips to its own bounds.
                    for i, glass in enumerate(halves):
                        glass.fill_rect(x - i * WIDTH // 2, y, SCALE, SCALE, BLACK)
    return pixels


class Panel:
    def __init__(self):
        self.spi = machine.SPI(
            1,
            baudrate=10_000_000,
            polarity=0,
            phase=0,
            sck=machine.Pin(SCK),
            mosi=machine.Pin(MOSI),
        )
        self.cs = {
            PRIMARY: machine.Pin(CS0, machine.Pin.OUT, value=1),
            SECONDARY: machine.Pin(CS1, machine.Pin.OUT, value=1),
        }
        self.dc = machine.Pin(DC, machine.Pin.OUT, value=0)
        self.rst = machine.Pin(RST, machine.Pin.OUT, value=1)
        self.busy = machine.Pin(BUSY, machine.Pin.IN)
        self.power = machine.Pin(POWER, machine.Pin.OUT, value=0)

    def command(self, target: int, command: int, data=b"") -> None:
        # Shared SPI carries commands and data; CS selects controllers and DC distinguishes the two.
        chips = [pin for chip, pin in self.cs.items() if target & chip]
        for pin in chips:
            pin.value(0)
        self.dc.value(0)
        self.spi.write(bytes([command]))
        if data:
            self.dc.value(1)
            self.spi.write(data)
        for pin in chips:
            pin.value(1)
        self.dc.value(0)

    def wait(self, seconds: int = 5) -> None:
        # The controller takes a moment to pull BUSY low after a command; ready is high.
        time.sleep_ms(10)
        # ticks_diff handles wraparound of MicroPython's tick counter.
        deadline = time.ticks_add(time.ticks_ms(), seconds * 1000)
        while not self.busy.value():
            if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                raise OSError("panel stayed busy")
            time.sleep_ms(50)

    def on(self) -> None:
        self.power.value(1)
        time.sleep_ms(50)
        self.rst.value(0)
        time.sleep_ms(20)
        self.rst.value(1)
        time.sleep_ms(20)
        self.wait()
        for target, command, data in INIT:
            self.command(target, command, data)
            time.sleep_ms(10)

    def draw(self, pixels) -> None:
        half = len(pixels) // 2
        view = memoryview(pixels)
        self.command(BOTH, 0xE0, b"\x01")
        self.wait()
        # Memoryview slices send each controller its contiguous half without copying the page.
        self.command(PRIMARY, 0x10, view[:half])
        self.command(SECONDARY, 0x10, view[half:])
        self.command(BOTH, 0x04)
        self.wait()
        time.sleep_ms(30)
        self.command(BOTH, 0x12, b"\x01")
        self.wait(60)  # a full refresh of six colours takes about half a minute
        time.sleep_ms(30)
        self.command(BOTH, 0x02, b"\x00")
        self.wait()

    def off(self) -> None:
        self.command(PRIMARY, 0x07, b"\xa5")
        time.sleep_ms(100)
        self.power.value(0)


def show(pixels) -> None:
    panel = Panel()
    panel.on()
    try:
        panel.draw(pixels)
    finally:
        panel.off()


def load(rtc) -> dict:
    """Load the ETag, last notice text, failure count and poll from RTC memory
    across deep-sleep wakes."""
    try:
        return dict(FRESH, **json.loads(bytes(rtc.memory()).decode()))
    except ValueError:
        return FRESH  # a cold start leaves the memory empty


def main() -> int:
    """One wake: fetch, draw when the page moved, and return the minutes to sleep."""
    rtc = machine.RTC()
    state = load(rtc)
    try:
        page, poll = download(state["etag"])
    except Problem as problem:
        failures = state["failures"] + 1
        message = str(problem)
        print("fugleramme:", message)
        if message != state["shown"] and (problem.lasting or failures >= NOTICE_AFTER):
            # Show lasting errors at once, but wait for repeated transient failures.
            # The message check avoids redrawing the same notice.
            show(notice(message))

            # No ETag: the next page that arrives replaces the notice. The poll is
            # the frame's, not the page's, so it outlives the reset.
            state = dict(state, etag="", shown=message)
        state = dict(state, failures=failures)
        rtc.memory(json.dumps(state).encode())
        return max(state["poll"], MIN_SLEEP_MINUTES)
    if poll is not None:
        state = dict(state, poll=poll)
    if page is not None:
        pixels, etag = page
        show(pixels)
        state = dict(state, etag=etag, shown="")
    rtc.memory(json.dumps(dict(state, failures=0)).encode())
    return max(state["poll"], MIN_SLEEP_MINUTES)


try:
    minutes = main()
except Exception as error:
    print("fugleramme:", error)
    minutes = MIN_SLEEP_MINUTES

# The frame's poll decides the sleep; the minimum is the floor under it.
machine.deepsleep(minutes * 60 * 1000)
