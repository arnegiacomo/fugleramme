"""Facts about the machine the frame runs on, for the admin's System panel.

Nothing here renders - the admin decides how a probe reads.
"""

from __future__ import annotations

import json
import shutil
import socket
import time
from pathlib import Path
from urllib.request import urlopen

_ONLINE_TTL = 60
# The row a user watches while fixing it, so cached only long enough to keep a
# burst of reloads off the probe.
_DETECTOR_TTL = 5
_online_cache: tuple[float, bool] | None = None
_detector_cache: tuple[str, float, tuple[bool, str]] | None = None


def reachable(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def _default_iface() -> str:
    """Interface holding the default route. Linux only; other dev hosts get nothing."""
    try:
        rows = Path("/proc/net/route").read_text().splitlines()[1:]
    except OSError:
        return ""
    # Columns are Iface, Destination (hex, all-zero for the default route).
    return next((f[0] for r in rows if len(f := r.split()) > 1 and f[1] == "00000000"), "")


def online() -> tuple[bool, str]:
    """Whether the internet answers, and the interface it goes out of. Cached,
    so a page load never waits out a dead link twice in a minute."""
    global _online_cache
    now = time.monotonic()
    if _online_cache is None or now - _online_cache[0] >= _ONLINE_TTL:
        # Cloudflare by IP - no name lookup to hang on; 443 since some networks filter 53.
        _online_cache = (now, reachable("1.1.1.1", 443))
    return _online_cache[1], _default_iface()


def detector(url: str) -> tuple[bool, str]:
    """Whether BirdNET-Go answers at `url`, and the version it reports. The
    frame's update leaves the container alone, so the version drifts from the tag
    the compose pins until `run.sh` runs. Cached like `online()`, but briefly."""
    global _detector_cache
    now = time.monotonic()
    cached = _detector_cache if _detector_cache and _detector_cache[0] == url else None
    if cached is None or now - cached[1] >= _DETECTOR_TTL:
        _detector_cache = (url, now, _probe_detector(url))
        return _detector_cache[2]
    return cached[2]


def _probe_detector(url: str) -> tuple[bool, str]:
    # /api/v2/health sits outside BirdNET-Go's auth group, so PrivateMode answers too.
    try:
        with urlopen(f"{url}/api/v2/health", timeout=3) as response:
            return True, str(json.load(response).get("version") or "")
    except (OSError, ValueError):
        return False, ""


def lan_address() -> str:
    host = socket.gethostname()
    if "." not in host:
        host += ".local"  # avahi publishes it; the Pi's bare hostname does not resolve off-box
    try:
        # Connecting a UDP socket sends nothing; it just picks the outbound interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 1))
            return f"{host} · {s.getsockname()[0]}"
    except OSError:
        return host


def disk_free(path: Path) -> str:
    usage = shutil.disk_usage(path)
    return f"{usage.free / 1e9:.0f} GB free of {usage.total / 1e9:.0f} GB"
