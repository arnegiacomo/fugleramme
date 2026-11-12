"""Wi-Fi setup without SSH (#308): a hotspot with a captive portal, opened when the frame has no network.

NetworkManager does the radio work through `sudo -n nmcli`, so this reaches frames through the
self-update: everything it needs ships on Raspberry Pi OS. The radio is one or the other, never
both, since hosting a hotspot while joined to a network crashes the Pi's Wi-Fi firmware.

Standard library only, and nothing from the rest of the package, so a frame that only drives a
panel (examples/inky) can carry a copy.
"""

from __future__ import annotations

import ipaddress
import logging
import queue
import re
import subprocess
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace
from pathlib import Path

log = logging.getLogger(__name__)

HOTSPOT = "fugleramme-hotspot"  # the NetworkManager profile, created on open and deleted on close
ADDRESS = "10.42.0.1"
SUBNET = ipaddress.ip_network("10.42.0.0/24")  # what ipv4.method shared hands out
# Read by every dnsmasq NetworkManager starts for a shared connection, the USB gadget's too, so
# it only holds anything while the hotspot is up. dnsmasq reads it at start, which leaves an
# already running gadget alone.
DNS_FILE = "/etc/NetworkManager/dnsmasq-shared.d/fugleramme.conf"
NFT_TABLE = "fugleramme"

GRACE = 5 * 60  # saved networks get this long after start before the hotspot opens
RETRY = 3 * 60  # how often a boot-opened hotspot looks for a saved network while nobody is on it
TICK = 5
JOIN_SECONDS = 60  # how long nmcli waits for a network to connect
_RUN_SECONDS = JOIN_SECONDS + 30

Run = Callable[[Sequence[str], str | None], subprocess.CompletedProcess[str]]


def plain(args: Sequence[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(args), input=stdin, capture_output=True, text=True, timeout=_RUN_SECONDS, check=False
    )


def sudo(args: Sequence[str], stdin: str | None = None) -> subprocess.CompletedProcess[str]:
    """A command as root, refused rather than prompted for when no rule allows it."""
    return plain(["sudo", "-n", *args], stdin)


def fields(line: str) -> list[str]:
    """One line of `nmcli -t`: colon separated, with `\\:` and `\\\\` escaped."""
    out: list[str] = []
    current = ""
    escaped = False
    for char in line:
        if escaped:
            current, escaped = current + char, False
        elif char == "\\":
            escaped = True
        elif char == ":":
            out, current = [*out, current], ""
        else:
            current += char
    return [*out, current]


@dataclass(frozen=True)
class Network:
    ssid: str
    security: str  # nmcli's words, e.g. "WPA2", "WPA2 WPA3", "" for open
    signal: int

    @property
    def secure(self) -> bool:
        return bool(self.security)


def networks(listing: str) -> tuple[Network, ...]:
    """`nmcli -t -f SSID,SECURITY,SIGNAL dev wifi list`, strongest first, one row per name.
    Hidden networks have no name to list, and Enterprise ones need more than a password."""
    best: dict[str, Network] = {}
    for line in listing.splitlines():
        ssid, security, signal = (fields(line) + ["", "", ""])[:3]
        security = "" if security in ("", "--") else security
        if not ssid or "802.1X" in security:
            continue
        found = Network(ssid, security, int(signal) if signal.isdigit() else 0)
        if ssid not in best or found.signal > best[ssid].signal:
            best[ssid] = found
    return tuple(sorted(best.values(), key=lambda n: -n.signal))


def key_mgmt(security: str) -> str:
    """What nmcli calls a network's key management. WPA-PSK covers WPA2 and a network that
    offers WPA3 beside it; only a WPA3-only network needs SAE."""
    return "sae" if "WPA3" in security and "WPA2" not in security else "wpa-psk"


def on_hotspot(address: str) -> bool:
    """Whether a client address is a phone on the hotspot."""
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip in SUBNET


def hotspot_name(mac: str) -> str:
    """`Fugleramme-XXXX`, from the end of the Wi-Fi MAC, so two frames in one house differ."""
    return "Fugleramme-" + mac.replace(":", "")[-4:].upper()


class Nmcli:
    """The commands, and how their output reads. Changes go through `run`, which is `sudo`;
    reads through `read`, which needs no root and keeps sudo's two journal lines a call out
    of a check that runs every few seconds."""

    def __init__(self, port: int, run: Run = sudo, read: Run = plain):
        self._port = port
        self._run = run
        self._read = read

    def _ok(self, *args: str, stdin: str | None = None) -> bool:
        done = self._run(args, stdin)
        if done.returncode != 0:
            log.debug("%s: %s", " ".join(args[:3]), done.stderr.strip())
        return done.returncode == 0

    def _out(self, *args: str) -> str:
        done = self._run(args, None)
        return done.stdout if done.returncode == 0 else ""

    def _look(self, *args: str) -> str:
        done = self._read(args, None)
        return done.stdout if done.returncode == 0 else ""

    def allowed(self) -> bool:
        """Whether sudo lets this user run everything below without a password."""
        return all(
            self._ok("-l", *command)
            for command in (("nmcli",), ("nft", "-f", "-"), ("tee", DNS_FILE))
        )

    def device(self) -> str:
        """The Wi-Fi interface, or "" on a machine without one."""
        for line in self._look("nmcli", "-t", "-f", "DEVICE,TYPE", "device").splitlines():
            name, kind = (fields(line) + [""])[:2]
            if kind == "wifi":
                return name
        return ""

    def started(self) -> bool:
        """Whether NetworkManager has finished bringing up what it brings up at boot."""
        return self._look("nmcli", "-t", "-f", "STARTUP", "general").strip() == "started"

    def online(self) -> bool:
        """A default route out of any interface: Wi-Fi, ethernet, or the USB gadget while a
        computer shares its connection over it. Not NetworkManager's connected devices: the
        gadget's shared profile stays connected with no cable in, and the hotspot and Docker's
        bridges are connected too, none of them with a way out."""
        return "default" in self._look("ip", "-4", "route", "show", "default")

    def saved(self) -> tuple[str, ...]:
        """The names of the saved Wi-Fi networks."""
        uuids = [
            uuid
            for uuid, kind, name in (
                (fields(line) + ["", ""])[:3]
                for line in self._look(
                    "nmcli", "-t", "-f", "UUID,TYPE,NAME", "connection"
                ).splitlines()
            )
            if kind == "802-11-wireless" and name != HOTSPOT
        ]
        ssids = (
            self._look("nmcli", "-g", "802-11-wireless.ssid", "connection", "show", "uuid", uuid)
            for uuid in uuids
        )
        # -g escapes like -t, though there is only the one field.
        return tuple(fields(s.strip())[0] for s in ssids if s.strip())

    def scan(self) -> tuple[Network, ...]:
        listing = self._out(
            "nmcli", "-t", "-f", "SSID,SECURITY,SIGNAL", "device", "wifi", "list", "--rescan", "yes"
        )
        return networks(listing)

    def mac(self, device: str) -> str:
        path = Path(f"/sys/class/net/{device}/address")
        return path.read_text().strip() if path.exists() else ""

    def phones(self, device: str) -> bool:
        """Whether anything is connected to the hotspot."""
        return "Station " in self._look("iw", "dev", device, "station", "dump")

    def open(self, device: str, name: str, password: str) -> bool:
        """Raise the hotspot, with every name resolving to the frame and port 80 sent to the
        frame's own port, which is what makes a phone show the portal by itself."""
        self._ok(
            "tee",
            DNS_FILE,
            stdin=f"address=/#/{ADDRESS}\ndhcp-option=114,http://{ADDRESS}/\n",
        )
        # Created empty and deleted first, so a table left by a crash is replaced, not doubled.
        self._ok(
            "nft",
            "-f",
            "-",
            stdin=(
                f"table ip {NFT_TABLE} {{}}\ndelete table ip {NFT_TABLE}\n"
                f"table ip {NFT_TABLE} {{\n  chain prerouting {{\n"
                "    type nat hook prerouting priority dstnat; policy accept;\n"
                f'    iifname "{device}" tcp dport 80 redirect to :{self._port}\n  }}\n}}\n'
            ),
        )
        self._ok("nmcli", "connection", "delete", HOTSPOT)
        security = ["wifi-sec.key-mgmt", "wpa-psk", "wifi-sec.psk", password] if password else []
        added = self._ok(
            "nmcli",
            "connection",
            "add",
            "type",
            "wifi",
            "ifname",
            device,
            "con-name",
            HOTSPOT,
            "autoconnect",
            "no",
            "ssid",
            name,
            "802-11-wireless.mode",
            "ap",
            "802-11-wireless.band",
            "bg",
            "ipv4.method",
            "shared",
            "ipv4.addresses",
            f"{ADDRESS}/24",
            "ipv6.method",
            "disabled",
            *security,
        )
        return added and self._ok("nmcli", "connection", "up", HOTSPOT)

    def close(self) -> None:
        self._ok("nmcli", "connection", "down", HOTSPOT)
        self._ok("nmcli", "connection", "delete", HOTSPOT)
        self._ok("tee", DNS_FILE, stdin="")  # emptied rather than removed: no `rm` in sudoers
        self._ok("nft", "delete", "table", "ip", NFT_TABLE)

    def connect(self, device: str) -> bool:
        """Let NetworkManager pick a saved network for the device, clearing its retry block."""
        return self._ok("nmcli", "--wait", str(JOIN_SECONDS), "device", "connect", device)

    def join(self, device: str, ssid: str, password: str, security: str, hidden: bool) -> bool:
        """Save the network beside the others and connect to it; a network that does not
        connect is deleted again."""
        args = ["type", "wifi", "ifname", device, "con-name", ssid, "ssid", ssid]
        if password:
            args += ["wifi-sec.key-mgmt", key_mgmt(security), "wifi-sec.psk", password]
        if hidden:
            args += ["802-11-wireless.hidden", "yes"]
        added = self._run(["nmcli", "connection", "add", *args], None)
        found = re.search(r"\(([0-9a-f-]{36})\)", added.stdout)
        if added.returncode != 0 or not found:
            log.warning("Could not save %s: %s", ssid, added.stderr.strip())
            return False
        uuid = found.group(1)
        if self._ok("nmcli", "--wait", str(JOIN_SECONDS), "connection", "up", "uuid", uuid):
            return True
        self._ok("nmcli", "connection", "delete", "uuid", uuid)
        return False


@dataclass(frozen=True)
class State:
    """What the panel, the portal and the admin read. Replaced whole, never changed."""

    available: bool = False
    problem: str = ""  # why it is not, in the admin's words
    up: bool = False
    name: str = ""
    password: str = ""
    error: str = ""  # the last join that failed, for the setup screen
    networks: tuple[Network, ...] = field(default=())


@dataclass(frozen=True)
class _Join:
    ssid: str
    password: str
    hidden: bool


_TOGGLE = "toggle"


class Setup:
    """When the hotspot opens and closes. One thread runs `run`; the buttons and the portal
    only queue a request, so no NetworkManager call ever races another.

    - At start with no saved network, it opens once NetworkManager has started.
    - With saved networks but none connecting, it opens after GRACE.
    - Opened that way, it closes when another interface comes up, and every RETRY while no
      phone is on it, it joins a saved network that has come into range.
    - Holding button A opens it whatever the network, and holding A again closes it.
    - Never on its own once the frame has been online since start.
    """

    def __init__(
        self,
        nm: Nmcli,
        enabled: Callable[[], bool],
        password: Callable[[], str],
        publish: Callable[[State], None],
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._nm = nm
        self._enabled = enabled
        self._password = password
        self._publish = publish
        self._clock = clock
        self._sleep = sleep
        self._requests: queue.Queue[_Join | str] = queue.Queue()
        self._started = clock()
        self._been_online = False
        self._by_hand = False  # opened by holding A: no retries, closes only by A or a join
        self._retry_at = 0.0
        self._open_after = 0.0  # a hotspot that would not open is not tried again every tick
        self._device = ""
        self.state = State()

    def toggle(self) -> None:
        self._requests.put(_TOGGLE)

    def join(self, ssid: str, password: str, hidden: bool) -> None:
        self._requests.put(_Join(ssid, password, hidden))

    def _set(self, **changes) -> None:
        self.state = replace(self.state, **changes)
        self._publish(self.state)

    def start(self) -> bool:
        """Check the machine can do this at all. False leaves the reason on the state."""
        if not self._nm.allowed():
            self._set(problem="sudo refuses nmcli")
            log.warning(
                "Wi-Fi setup unavailable: sudo refuses nmcli, nft or tee without a password"
            )
            return False
        self._device = self._nm.device()
        if not self._device:
            self._set(problem="no Wi-Fi")
            log.warning("Wi-Fi setup unavailable: no Wi-Fi device")
            return False
        self._set(available=True, problem="")
        return True

    def run(self) -> None:
        if not self.start():
            return
        while True:
            try:
                request = self._requests.get(timeout=TICK)
            except queue.Empty:
                request = None
            try:
                self.step(request)
            except Exception:  # a failed command must not take the thread with it
                log.exception("Wi-Fi setup step failed")

    def step(self, request: _Join | str | None) -> None:
        if not self._enabled():
            if self.state.up:
                self._close()
            return
        if request == _TOGGLE:
            self._toggle()
        elif isinstance(request, _Join):
            self._join(request)
        else:
            self._check()

    def _check(self) -> None:
        if self._been_online and not self.state.up:
            return  # nothing opens on its own any more; only a hold on A does
        online = self._nm.online()
        self._been_online = self._been_online or online
        if self.state.up:
            if self._by_hand:
                return
            if online:
                log.info("Online through another interface, closing the hotspot")
                self._close()
            elif self._clock() >= self._retry_at and not self._nm.phones(self._device):
                self._retry()
            return
        if self._been_online or self._clock() < self._open_after or not self._nm.started():
            return
        if not self._nm.saved():
            self._open(by_hand=False)
        elif self._clock() - self._started >= GRACE:
            log.info("No saved network connected in %d minutes", GRACE // 60)
            self._open(by_hand=False)

    def _toggle(self) -> None:
        if self.state.up:
            log.info("Button A held: closing the hotspot")
            self._close()
            self._nm.connect(self._device)
            return
        log.info("Button A held: opening the hotspot")
        self._open(by_hand=True)

    def _retry(self) -> None:
        """Scan with the hotspot up, which a phone on it would barely notice, and leave it only
        for a saved network that is actually in range."""
        self._retry_at = self._clock() + RETRY
        found = self._nm.scan()
        if found:
            self._set(networks=found)
        saved = set(self._nm.saved())
        if not any(n.ssid in saved for n in found):
            return
        log.info("A saved network is in range, trying it")
        self._nm.close()
        if self._nm.connect(self._device):
            self._been_online = True
            self._set(up=False, error="")
            return
        self._open(by_hand=False)

    def _open(self, by_hand: bool, error: str = "") -> None:
        """Scan first: the scan list is what the portal offers, and it is cheapest before the
        radio is a hotspot."""
        found = self._nm.scan()
        name = hotspot_name(self._nm.mac(self._device))
        password = self._password()
        if not self._nm.open(self._device, name, password):
            log.error("Could not open the hotspot %s", name)
            self._nm.close()
            self._open_after = self._clock() + RETRY
            self._set(up=False)
            return
        self._by_hand = by_hand
        self._retry_at = self._clock() + RETRY
        log.info("Hotspot %s open", name)
        self._set(
            up=True,
            name=name,
            password=password,
            error=error,
            networks=found or self.state.networks,
        )

    def _close(self) -> None:
        self._nm.close()
        self._by_hand = False
        self._set(up=False, error="")
        log.info("Hotspot closed")

    def _join(self, request: _Join) -> None:
        if not self.state.up:
            return
        # The portal's answer has to reach the phone before the hotspot goes.
        self._sleep(2)
        security = next((n.security for n in self.state.networks if n.ssid == request.ssid), "")
        log.info("Joining %s", request.ssid)
        self._nm.close()
        if self._nm.join(
            self._device, request.ssid, request.password, security or "WPA2", request.hidden
        ):
            log.info("Joined %s", request.ssid)
            self._been_online = True
            self._by_hand = False
            self._set(up=False, error="")
            return
        log.warning("Could not join %s, reopening the hotspot", request.ssid)
        # Straight away, before NetworkManager falls back to a saved network: the setup screen
        # has to say the new one failed.
        self._open(self._by_hand, f"Couldn't join {request.ssid}")
