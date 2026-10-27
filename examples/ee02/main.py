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

Every OTA_EVERY_N_RUNS wakes the panel also asks the frame for its own program
at FIRMWARE. A different program is downloaded, compile-checked and staged as
main.py.new, and boot.py swaps it in at the next boot as a trial: the new
program deletes boot.py's main.py.bak once a wake has reached the frame
without a problem, and otherwise boot.py puts the old one back and keeps the
rejected version at bay through main.etag. A watchdog in boot.py catches a
program that hangs instead of crashing, and an update that keeps failing the
same way is announced on the glass. OTA is off while FIRMWARE is None.

The user LED (GPIO21, active low) reports the wake: 1 long = button 1, 2 long
= button 2, 1 short = timer wake or reset. Button 2 only checks for updates
while OTA is on. Then short-long-short once Wi-Fi is up, five short when it
cannot join, steady on while the panel refreshes (~30 s), and three short if
that refresh failed.

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
import os
import socket
import ssl
import struct
import time

import config
import esp32
import framebuf
import machine
import network

try:
    import hashlib
except ImportError:  # some MicroPython builds leave it out
    hashlib = None

# load configuration
WIFI_NETWORKS = config.WIFI_NETWORKS
WIFI_HINT = config.WIFI_HINT
FRAME_HOST = config.FRAME_HOST
FRAME_PORT = config.FRAME_PORT
FRAME_TLS = config.FRAME_TLS
FIRMWARE = getattr(config, "FIRMWARE", None)
OTA_ENABLED = isinstance(FIRMWARE, str)
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

# boot.py arms this; main.py feeds it during long network waits.
WATCHDOG_TIMEOUT_MS = 300_000

# The panel's program is checked every OTA_EVERY_N_RUNS wakes. An update is
# staged for boot.py, which swaps it in and leaves main.py.bak behind until
# the new program has pulled a page cleanly. The board pulls the buttons high
# and a press pulls them low: any press on button 1 (GPIO2, XIAO D1) forces a
# fresh page, while button 2 (GPIO3, XIAO D2, "Next Page") asks for an update
# check at once when OTA is on. EXT0 and EXT1 tell the two buttons apart after
# the wake.
OTA_EVERY_N_RUNS = 48
MAX_FIRMWARE_BYTES = 1_000_000
BUTTON_REFRESH = 2
BUTTON_NEXT = 3

# The XIAO's user LED (GPIO21) is the board's only controllable light: active
# low, so 0 is on. It blinks the wake's progress, since a page takes a while.
LED = 21
SHORT, LONG = 120, 480

FRESH = {
    "etag": "",
    "shown": "",
    "failures": 0,
    "poll": MIN_SLEEP_MINUTES,
    "refreshes_since_firmware_check": 0,
    "ota_failures": 0,
}

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


_WATCHDOG = None


def blink(pattern) -> None:
    """Blink the user LED: `pattern` is on-durations in ms, off in between."""
    led = machine.Pin(LED, machine.Pin.OUT, value=1)  # active low: 1 is off
    for duration in pattern:
        led.value(0)
        time.sleep_ms(duration)
        led.value(1)
        time.sleep_ms(duration)


def button_wake() -> str:
    """Which button woke the board: refresh, update, or an empty string."""
    try:
        reason = machine.wake_reason()
    except (AttributeError, ValueError):
        return ""  # a build without wake reasons still sleeps and checks on the count
    if reason in (getattr(machine, "PIN_WAKE", None), getattr(machine, "EXT0_WAKE", None)):
        return "refresh"
    if reason == getattr(machine, "EXT1_WAKE", None):
        return "update"
    return ""


def feed_watchdog() -> None:
    """Feed the watchdog boot.py arms during a firmware trial, over long
    network waits. Outside a trial nothing is armed, and feeding would be
    pointless."""
    global _WATCHDOG
    if _WATCHDOG is None:
        if not there("main.py.bak"):
            return
        _WATCHDOG = machine.WDT(timeout=WATCHDOG_TIMEOUT_MS)
    _WATCHDOG.feed()


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
            feed_watchdog()
            if wlan.isconnected():
                print("wifi: joined", ssid)
                if ssid != hint:
                    with open(WIFI_HINT, "w") as file:
                        file.write(ssid)
                blink((SHORT, LONG, SHORT))
                return
            time.sleep(1)
        wlan.disconnect()
    blink((SHORT,) * 5)
    raise Problem(
        "Cannot join any Wi-Fi network: " + ", ".join(ssid for ssid, _ in WIFI_NETWORKS) + "."
    )


def disconnect() -> None:
    network.WLAN(network.STA_IF).active(False)


def there(name: str) -> bool:
    try:
        os.stat(name)
        return True
    except OSError:
        return False


def installed_etag() -> str:
    """What the running program believes is on the frame, kept in flash rather
    than RTC memory: a power cut during a trial must not lose it, or the
    rejected version would be fetched all over again."""
    try:
        with open("main.etag") as file:
            return file.read()
    except OSError:
        return ""


def firmware_target(path: str):
    """Split a FIRMWARE URL into (host, port, tls, path); a bare path is
    served by the frame's own host."""
    if "://" not in path:
        return FRAME_HOST, FRAME_PORT, FRAME_TLS, path
    tls = path.startswith("https://")
    hostpart, _, location = path.partition("://")[2].partition("/")
    host, _, port = hostpart.partition(":")
    return host, int(port) if port else (443 if tls else 80), tls, "/" + location


def read_exactly(sock, buffer) -> None:
    view = memoryview(buffer)
    got = 0
    while got < len(buffer):
        feed_watchdog()
        count = sock.readinto(view[got:])
        if not count:
            raise OSError("connection closed early")
        got += count


def _get(path: str, etag: str, target=None):
    """One GET to the frame, headers consumed. `target` is an optional
    (host, port, tls) triple for a request that goes to another host than the
    frame's page. Returns (sock, status, etag, content_length) - the socket
    still open, closed by the caller in its own finally."""
    host, port, tls = target or (FRAME_HOST, FRAME_PORT, FRAME_TLS)
    address = socket.getaddrinfo(host, port)[0][-1]
    sock = socket.socket()
    sock.settimeout(30)
    try:
        sock.connect(address)
        if tls:
            # server_hostname carries the SNI the frame's certificate needs.
            sock = ssl.wrap_socket(sock, server_hostname=host)
        request = f"GET {path} HTTP/1.0\r\nHost: {host}\r\n"
        if etag:
            request += f"If-None-Match: {etag}\r\n"
        sock.write((request + "\r\n").encode())
        status = int(sock.readline().split()[1])
        served = ""
        length = None
        while (line := sock.readline()) not in (b"\r\n", b""):
            name, _, value = line.decode().partition(":")
            name = name.strip().lower()
            value = value.strip()
            if name == "etag":
                served = value
            elif name == "content-length":
                length = int(value)
        return sock, status, served, length
    except Exception:
        sock.close()
        raise


def fetch(etag: str):
    """Returns (page, poll): page is None when the frame still has the one
    drawn, and poll is None with it, since a page the frame revalidates
    carries the same poll as the one on the glass."""
    sock, status, new_etag, _length = _get("/frame.e6", etag)
    try:
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


def download(etag: str, refresh: bool = False):
    try:
        connect()
        # A forced refresh asks for the body even when our ETag still matches.
        return fetch("" if refresh else etag)
    except Problem:
        raise
    except Exception as error:
        raise Problem(f"Cannot reach the frame at {FRAME_HOST}:{FRAME_PORT} ({error}).") from error
    finally:
        # Wi-Fi is only needed for fetching; keep it off while the panel refreshes.
        disconnect()


def firmware():
    """Returns (source, etag) for the panel's program, or None while it is
    unchanged - or while a frame that predates the route answers 404, which is
    not a failure, only nothing new."""
    installed = installed_etag()
    host, port, tls, path = firmware_target(FIRMWARE)
    sock, status, served, length = _get(path, installed, (host, port, tls))
    try:
        if status in (304, 404):
            return None
        if status != 200:
            raise Problem(f"The frame answered {status} for {FIRMWARE}.")
        if served == "":
            # Without an ETag there is nothing to revalidate against, so every
            # check would download and install the program again. Say so
            # instead of silently rebooting the panel once an interval.
            raise Problem(f"The frame sent {FIRMWARE} without an ETag.")
        if length is None:
            raise Problem("The frame did not send the program's length.")
        if length <= 0 or length > MAX_FIRMWARE_BYTES:
            raise Problem(f"The frame sent an implausible program length ({length}).")
        if served != installed:
            print("ota: new version", served)
            blink((SHORT,))
        source = bytearray(length)
        read_exactly(sock, source)
        return bytes(source), served
    finally:
        sock.close()


def download_firmware():
    try:
        connect()
        return firmware()
    except Problem:
        raise
    except Exception as error:
        raise Problem(f"Cannot reach the frame at {FRAME_HOST}:{FRAME_PORT} ({error}).") from error
    finally:
        disconnect()


def update(state: dict, asked: bool):
    """Check the frame for a new program when the count runs out or the button
    asks. Returns (state, problem): the problem is None when the check was
    skipped or passed, and the failure the panel may want to say when it did
    not. On a new version this never returns: the board restarts onto it, and
    boot.py rolls it back if it fails its trial."""
    if not OTA_ENABLED:
        return state, None
    if not asked and state["refreshes_since_firmware_check"] < OTA_EVERY_N_RUNS:
        return state, None
    if there("main.py.bak"):
        # A trial is still unconfirmed; installing now would overwrite the way
        # back with the program being trialled.
        return state, None
    print("ota: checking", FIRMWARE)
    try:
        answer = download_firmware()
    except Problem as problem:
        # The counter goes back to zero: a failed check waits a full interval
        # for the next one instead of retrying on every wake.
        return dict(
            state, refreshes_since_firmware_check=0, ota_failures=state["ota_failures"] + 1
        ), problem
    if answer is None:
        print("ota: up to date")
        return dict(state, refreshes_since_firmware_check=0, ota_failures=0), None
    source, served = answer
    print("ota: installing", served)
    try:
        compile(source, "main.py", "exec")
    except SyntaxError:
        # Never rename a program that cannot load; say so once the streak says.
        return dict(state, ota_failures=state["ota_failures"] + 1), Problem(
            "The frame sends a program this panel cannot load."
        )
    # Stage atomically: boot.py must never see a half-written program.
    with open("main.py.tmp", "wb") as file:
        file.write(source)
        file.flush()
    try:
        os.remove("main.py.new")
    except OSError:
        pass
    os.rename("main.py.tmp", "main.py.new")
    # Record what was installed before restarting, in flash so a power cut
    # cannot lose it, and after staging so a cut here only costs one refetch.
    with open("main.etag.tmp", "w") as file:
        file.write(served)
        file.flush()
    try:
        os.remove("main.etag")
    except OSError:
        pass
    os.rename("main.etag.tmp", "main.etag")
    blink((SHORT,) * 5)
    machine.reset()


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
    # LED held on while the panel refreshes (~30 s): do not press anything,
    # and do not unplug, until it goes out.
    panel = Panel()
    led = machine.Pin(LED, machine.Pin.OUT, value=0)
    try:
        panel.on()
        panel.draw(pixels)
    except OSError:
        led.value(1)
        blink((SHORT,) * 3)  # three short blinks: the refresh failed
        raise
    finally:
        try:
            panel.off()
        except OSError:
            pass
        led.value(1)


def load(rtc) -> dict:
    """Load the ETag, last notice text, failure count and poll from RTC memory
    across deep-sleep wakes."""
    try:
        return dict(FRESH, **json.loads(bytes(rtc.memory()).decode()))
    except ValueError:
        return FRESH  # a cold start leaves the memory empty


def main(wake: str) -> int:
    """One wake: fetch, draw when the page moved, and return the minutes to sleep."""
    refresh = wake == "refresh"
    # Button 2 asks for an immediate update check; button 1 only repaints.
    asked = wake == "update"
    rtc = machine.RTC()
    state = load(rtc)
    if OTA_ENABLED:
        state = dict(
            state,
            refreshes_since_firmware_check=state["refreshes_since_firmware_check"] + 1,
        )
    rtc.memory(json.dumps(state).encode())
    state, problem = update(state, asked)
    if problem is not None and state["ota_failures"] >= NOTICE_AFTER:
        # An update that keeps failing is worth the glass saying so. It never
        # costs this wake's page, though: the page below is still fetched and
        # drawn, and when it moves it replaces the notice.
        message = f"The panel's program update keeps failing. ({problem})"
        print("fugleramme:", message)
        if message != state["shown"]:
            show(notice(message))
            state = dict(state, shown=message)
        rtc.memory(json.dumps(state).encode())
    try:
        # A notice is not the page: ask for the body even when the saved page
        # ETag still matches, so the next good wake replaces the notice.
        etag = "" if state["shown"] else state["etag"]
        page, poll = download(etag, refresh)
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
    # This wake reached the frame without a problem, which is the trial's
    # confirmation: boot.py keeps main.py.bak exactly until it sees this.
    try:
        os.remove("main.py.bak")
    except OSError:
        pass
    rtc.memory(json.dumps(dict(state, failures=0)).encode())
    return max(state["poll"], MIN_SLEEP_MINUTES)


# Immediate feedback on why the board woke, before anything slow happens:
#   1 long  = button 1 (refetch and redraw)
#   2 long  = button 2 (firmware update check, when OTA is on)
#   1 short = timer wake, reset or power-on
_wake = button_wake()
blink({"refresh": (LONG,), "update": (LONG, LONG)}.get(_wake, (SHORT,)))

try:
    minutes = main(_wake)
except Exception as error:
    print("fugleramme:", error)
    minutes = MIN_SLEEP_MINUTES

# The frame's poll decides the sleep; the minimum is the floor under it. Button
# 1 forces a fresh page, button 2 asks for an update check at once when OTA is
# on; EXT0 and EXT1 keep them distinguishable on the next wake.
for pin in (BUTTON_REFRESH, BUTTON_NEXT):
    machine.Pin(pin, machine.Pin.IN, machine.Pin.PULL_UP)
esp32.wake_on_ext0(machine.Pin(BUTTON_REFRESH), 0)
esp32.wake_on_ext1((machine.Pin(BUTTON_NEXT),), 0)
machine.deepsleep(minutes * 60 * 1000)
