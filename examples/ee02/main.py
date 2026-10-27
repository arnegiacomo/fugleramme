"""Fugleramme's page on a Seeed 13.3" Spectra 6 panel, from a XIAO EE02 board.

MicroPython's SEEED_XIAO_ESP32S3 build (it needs the board's octal PSRAM),
copied to the board as main.py. Enable "External e-ink panel" on the frame's admin page
first. Every wake it asks the frame for /frame.e6 with the ETag of the last
frame page on the glass (or none if a notice replaced it); an unchanged page
costs a 304 and nothing else. A new one is downloaded whole, checked, and only
then sent to the panel. The frame may be served over HTTPS, which the port
picks. Then it sleeps for the poll the page's header carries, which is the
admin's "Panel refresh", never below MIN_SLEEP_MINUTES.

When something goes wrong the panel says so in black on white, once: a page
that does not fit this panel or a frame that is not serving one at once, a
frame it cannot reach only after NOTICE_AFTER wakes in a row, so a restart or
a Wi-Fi blip leaves the birds up. The next page that arrives replaces it.

The panel is taken over without a cut to its supply. A brief interruption of
an energised panel has repeatedly left it unable to refresh, though the exact
mechanism is not established. A refresh is trusted only when BUSY actually
moved and stayed low for a full refresh's time. A failed refresh is never
retried in the same wake; the next wake's takeover recovers the panel.

The file format is in docs/screens.md. The panel's command sequence is
inspired by Seeed_GFX2's Driver_T133A01.cpp
(https://github.com/Seeed-Studio/Seeed_GFX2, MIT License, see its LICENSE).
Several changes were made at once to recover a corrupted panel. They seem
to fix the failures seen here. They were not bisected, so which change
matters is not known.
GPIO 43 and 44 double as UART0, so use the USB REPL.
"""

import binascii
import json
import socket
import ssl
import struct
import time

import config
import esp32
import framebuf
import machine
import network

WIFI_NETWORKS = config.WIFI_NETWORKS
WIFI_HINT = config.WIFI_HINT
FRAME_HOST = config.FRAME_HOST
FRAME_PORT = config.FRAME_PORT
FRAME_TLS = config.FRAME_TLS
MIN_SLEEP_MINUTES = config.MIN_SLEEP_MINUTES
NOTICE_AFTER = config.NOTICE_AFTER
WIDTH = config.WIDTH
HEIGHT = config.HEIGHT

# /frame.e6: a 20-byte little-endian header, then the left-controller rows
# followed by the right-controller rows.
HEADER = "<4sHBBHHII"
BLACK, WHITE = 0, 1
SCALE, MARGIN = 4, 96  # the built-in font is 8 px, far too small at this size

# T133A01 BUSY is active-low: LOW while refreshing, HIGH when idle. A healthy
# full refresh stays busy for about 28 s, or about 47 s on a cold panel. Treat
# a missing or very short BUSY-low as a refresh that never started.
REFRESH_START_MS = 2_000
REFRESH_MIN_BUSY_MS = 10_000
REFRESH_TIMEOUT_MS = 60_000

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


class RefreshProblem(OSError):
    pass


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
    """Robust lifecycle.

    An energised panel must never see a short power interruption: refreshes
    after one have failed here, though the mechanism is not established. GPIO43
    (the panel's load switch) is UART0 TX: the ROM dirty-powers the panel at
    every boot, and this class takes such a panel over without touching its
    supply. The reset and extra init steps recover it in practice. They were
    added together and not bisected.
    """

    def __init__(self):
        # Release the hold off() left through the previous deep sleep.
        for num in (RST, DC, CS0, CS1, SCK, MOSI):
            machine.Pin(num, hold=False)
        # Drive the load switch high without releasing it first. A brief cut
        # of an energised panel has broken refreshes here.
        self.power = machine.Pin(POWER, machine.Pin.OUT, value=1)
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

    def command_rows(self, target: int, command: int, data) -> None:
        """Send a DTM in row-sized chunks, unlike the Seeed driver."""
        chips = [pin for chip, pin in self.cs.items() if target & chip]
        for pin in chips:
            pin.value(0)
        self.dc.value(0)
        self.spi.write(bytes([command]))
        self.dc.value(1)
        view = memoryview(data)
        stride = (WIDTH // 4) * 64  # 64 rows of 300 bytes
        for offset in range(0, len(view), stride):
            self.spi.write(view[offset : offset + stride])
            time.sleep_ms(1)
        for pin in chips:
            pin.value(1)
        self.dc.value(0)

    def wait(self, seconds: int = 5) -> None:
        # The controller takes a moment to pull BUSY low after a command; ready is high.
        time.sleep_ms(10)
        started = time.ticks_ms()
        # ticks_diff handles wraparound of MicroPython's tick counter.
        deadline = time.ticks_add(started, seconds * 1000)
        while True:
            if self.busy.value():
                return
            if time.ticks_diff(deadline, time.ticks_ms()) < 0:
                raise OSError("panel stayed busy")
            time.sleep_ms(50)

    def on(self) -> None:
        # POWER is already high; give it the settle a cold power-on got.
        time.sleep_ms(100)
        # 100/100 ms reset. Seeed uses 20/20 ms. One of the changes made at once.
        self.rst.value(0)
        time.sleep_ms(100)
        self.rst.value(1)
        time.sleep_ms(100)
        self.wait(5)
        for target, command, data in INIT:
            self.command(target, command, data)
            time.sleep_ms(10)
        # PLL: absent from the Seeed init. One of the changes added at once.
        # Whether it matters on its own is not known.
        self.command(BOTH, 0x30, b"\x08")
        time.sleep_ms(10)
        # PON before any pixel data, unlike the Seeed driver. One of the
        # changes not tested in isolation.
        self.command(BOTH, 0x04)
        self.wait(5)
        time.sleep_ms(30)

    def refresh(self) -> None:
        """Run DRF and follow BUSY through a real refresh, not just its edges."""
        started = time.ticks_ms()
        while self.busy.value():
            if time.ticks_diff(time.ticks_ms(), started) >= REFRESH_START_MS:
                raise RefreshProblem("panel did not start refreshing")
            time.sleep_ms(2)

        busy_since = time.ticks_ms()
        while not self.busy.value():
            now = time.ticks_ms()
            if time.ticks_diff(now, busy_since) >= REFRESH_TIMEOUT_MS:
                raise RefreshProblem("panel stayed busy")
            time.sleep_ms(5)

        busy_ms = time.ticks_diff(time.ticks_ms(), busy_since)
        if busy_ms < REFRESH_MIN_BUSY_MS:
            raise RefreshProblem(f"panel released BUSY after only {busy_ms} ms")

    def draw(self, pixels) -> None:
        half = len(pixels) // 2
        view = memoryview(pixels)
        # CCSET before each controller's DTM, unlike the Seeed driver. One of
        # the changes added together, not tested in isolation.
        for target, chunk in ((PRIMARY, view[:half]), (SECONDARY, view[half:])):
            self.command(BOTH, 0xE0, b"\x01")
            self.wait(5)
            time.sleep_ms(10)
            self.command_rows(target, 0x10, chunk)
        time.sleep_ms(30)
        self.command(BOTH, 0x12, b"\x01")
        self.refresh()

    def off(self) -> None:
        """Clean shutdown: POF, cut power, then hold the outputs at 0 V through
        deep sleep so the idle panel drains instead of being back-fed (GPIO44/CS0
        carries a UART pull-up). BUSY is the panel's output, so it stays an
        input."""
        # A hung controller may never release BUSY, but the power cut and pin
        # hold must still happen.
        try:
            self.command(BOTH, 0x02, b"\x00")
            self.wait(5)
            time.sleep_ms(100)
        finally:
            self.power.value(0)
            # Not every build offers deinit; a failed one leaves the pins to the hold below.
            try:
                self.spi.deinit()
            except (AttributeError, OSError):
                pass
            for num in (RST, DC, CS0, CS1, SCK, MOSI):
                machine.Pin(num, machine.Pin.OUT, value=0, hold=True)
            machine.Pin(BUSY, machine.Pin.IN)
            esp32.gpio_deep_sleep_hold(True)


def show(pixels) -> None:
    """One attempt only: a refresh that fails from the partial-charge window
    cannot be retried with a short power cycle; the next wake's takeover
    recovers the panel instead."""
    panel = Panel()
    try:
        panel.on()
        panel.draw(pixels)
    finally:
        try:
            panel.off()
        except OSError:
            pass


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
