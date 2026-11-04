"""Fugleramme's page on a Seeed 7.3" Spectra 6 panel, from a XIAO EE04 board.

MicroPython's SEEED_XIAO_ESP32S3 build, copied to the board as main.py with
config.py beside it. Enable "External e-ink panel" on the frame's admin page and
set "External panel size" to 7.3" first. Every wake it asks the frame for
/frame.e6 with the ETag of the last frame page on the glass (or none if a notice
replaced it); an unchanged page costs a 304 and nothing else. A new one is
downloaded whole, checked, and only then sent to the panel. The frame may be
served over HTTPS, which the port picks. Then it sleeps for the poll the page's
header carries, which is the admin's "Panel refresh", never below
MIN_SLEEP_MINUTES.

When something goes wrong the panel says so in black on white, once: a page
that does not fit this panel or a frame that is not serving one at once, a
frame it cannot reach only after NOTICE_AFTER wakes in a row, so a restart or
a Wi-Fi blip leaves the birds up. The next page that arrives replaces it.

The file format is in docs/screens.md. The pins come from Seeed_GFX2's
XIAO_ePaper_Board_Configs.h and the panel's command sequence from its
Driver_ED2208.cpp (https://github.com/Seeed-Studio/Seeed_GFX2, MIT License,
see its LICENSE). GPIO 43 and 44 double as UART0, so use the USB REPL.
"""

import binascii
import json
import socket
import ssl
import struct
import time

import config
import framebuf
import machine
import network

# load configuration
WIFI_NETWORKS = config.WIFI_NETWORKS
WIFI_HINT = config.WIFI_HINT
FRAME_HOST = config.FRAME_HOST
FRAME_PORT = config.FRAME_PORT
FRAME_TLS = config.FRAME_TLS
MIN_SLEEP_MINUTES = config.MIN_SLEEP_MINUTES
NOTICE_AFTER = config.NOTICE_AFTER
WIDTH = config.WIDTH
HEIGHT = config.HEIGHT

# /frame.e6: a 20-byte little-endian header, then the glass's rows, top to bottom.
HEADER = "<4sHBBHHII"
BLACK, WHITE = 0, 1
SCALE, MARGIN = 3, 48  # the built-in font is 8 px, too small at this size
FRESH = {"etag": "", "shown": "", "failures": 0, "poll": MIN_SLEEP_MINUTES}

# EE04 wiring, from Seeed_GFX2's XIAO_ePaper_Board_Configs.h.
SCK, MOSI = 7, 9  # XIAO D8, D10
CS, DC, RST, BUSY, POWER = 44, 10, 38, 4, 43

# Each row is (register command, command data), in hardware init order.
INIT = (
    (0xAA, b"\x49\x55\x20\x08\x09\x18"),
    (0x01, b"\x3f\x00\x32\x2a\x0e\x2a"),
    (0x00, b"\x5f\x69"),
    (0x03, b"\x00\x54\x00\x44"),
    (0x05, b"\x40\x1f\x1f\x2c"),
    (0x06, b"\x6f\x1f\x16\x25"),
    (0x08, b"\x6f\x1f\x1f\x22"),
    (0x13, b"\x00\x04"),
    (0x30, b"\x02"),
    (0x41, b"\x00"),
    (0x50, b"\x3f"),
    (0x60, b"\x02\x00"),
    (0x61, b"\x03\x20\x01\xe0"),
    (0x82, b"\x1e"),
    (0x84, b"\x01"),
    (0x86, b"\x00"),
    (0xE3, b"\x2f"),
    (0xE0, b"\x00"),
    (0xE6, b"\x00"),
)


class Problem(Exception):
    def __init__(self, message: str, lasting: bool = False):
        super().__init__(message)
        self.lasting = lasting


def wifi_hint() -> str:
    """The network that connected last time, tried first if still configured."""
    try:
        with open(WIFI_HINT) as file:
            return file.read()
    except OSError:
        return ""


def connect() -> None:
    hint = wifi_hint()
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    # The remembered network goes first; the rest keep their configured order.
    for ssid, password in sorted(WIFI_NETWORKS, key=lambda pair: pair[0] != hint):
        print("wifi: trying", ssid)
        wlan.connect(ssid, password)
        for _ in range(30):
            if wlan.isconnected():
                print("wifi: joined", ssid)
                if ssid != hint:
                    with open(WIFI_HINT, "w") as file:
                        file.write(ssid)
                return
            time.sleep(1)
        wlan.disconnect()
    raise Problem(
        "Cannot join any Wi-Fi network: " + ", ".join(ssid for ssid, _ in WIFI_NETWORKS) + "."
    )


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
        if FRAME_TLS:
            # server_hostname carries the SNI the frame's certificate needs.
            sock = ssl.wrap_socket(sock, server_hostname=FRAME_HOST)
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
                'panel" on its admin page, under the "Frame" tab, and set '
                '"External panel size" to 7.3".',
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
                f'this one is {WIDTH}x{HEIGHT}. Set "External panel size" to 7.3" '
                'on its admin page, under the "Frame" tab.',
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
    glass = framebuf.FrameBuffer(pixels, WIDTH, HEIGHT, framebuf.GS4_HMSB)
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
                    glass.fill_rect(x, y, SCALE, SCALE, BLACK)
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
        self.cs = machine.Pin(CS, machine.Pin.OUT, value=1)
        self.dc = machine.Pin(DC, machine.Pin.OUT, value=0)
        self.rst = machine.Pin(RST, machine.Pin.OUT, value=1)
        self.busy = machine.Pin(BUSY, machine.Pin.IN)
        self.power = machine.Pin(POWER, machine.Pin.OUT, value=0)

    def command(self, command: int, data=b"") -> None:
        # One SPI bus carries commands and data; DC distinguishes the two.
        self.cs.value(0)
        self.dc.value(0)
        self.spi.write(bytes([command]))
        if data:
            self.dc.value(1)
            self.spi.write(data)
        self.cs.value(1)
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
        time.sleep_ms(10)
        # BUSY may stay low after a reset until the setup is in, so wait only after power-on.
        for command, data in INIT:
            self.command(command, data)
        self.command(0x04)
        self.wait()

    def draw(self, pixels) -> None:
        self.command(0x10, pixels)
        self.command(0x12, b"\x00")
        self.wait(60)  # a full refresh of six colours takes about half a minute
        self.command(0x02, b"\x00")
        self.wait()

    def off(self) -> None:
        # Deep sleep drops the setup, which on() resets and sends again every wake.
        self.command(0x07, b"\xa5")
        time.sleep_ms(100)
        self.power.value(0)


def show(pixels) -> None:
    panel = Panel()
    try:
        panel.on()
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
