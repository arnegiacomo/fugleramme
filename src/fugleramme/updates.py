"""Release checks and the self-update, driven by GitHub tags.

`Restart=always` on the unit means updating needs no privileges: check out the
tag, sync, exit, and systemd brings the new code up.
"""

from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .config import RELEASES_API, REPO_HTTPS_URL, REPO_ROOT

log = logging.getLogger(__name__)

_OK_TTL = 3600  # unauthenticated GitHub allows 60 requests/hour per IP
_FAIL_TTL = 300
_next_check = 0.0
_result: str | None = None

_STALL_SECONDS = 300  # a big release is slow, not stuck: every progress line resets it
_PROGRESS = re.compile(r"^(?:remote: )?([A-Za-z][A-Za-z ]+):\s+(\d+)%")

Progress = Callable[[str, int | None], None]


def _version(tag: str) -> tuple[int, ...]:
    return tuple(int(part) for part in tag.lstrip("v").split(".")[:3])


def _uv() -> str:
    # systemd's default PATH misses ~/.local/bin, where the uv installer puts it.
    return shutil.which("uv") or str(Path.home() / ".local" / "bin" / "uv")


def _fetch_latest() -> tuple[str | None, bool]:
    """(tag of a newer release or None, whether the check itself succeeded)."""
    request = urllib.request.Request(
        RELEASES_API, headers={"Accept": "application/vnd.github+json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            tag = json.load(response).get("tag_name")
        return (tag if tag and _version(tag) > _version(__version__) else None), True
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        log.warning("Update check failed: %s", exc)
        return None, False


def available(force: bool = False) -> str | None:
    """Tag of a newer release, or None. Cached; a failed check is retried sooner."""
    global _next_check, _result
    now = time.monotonic()
    if force or now >= _next_check:
        _result, ok = _fetch_latest()
        _next_check = now + (_OK_TTL if ok else _FAIL_TTL)
    return _result


def apply(tag: str, progress: Progress | None = None) -> None:
    """Move the checkout onto `tag`. Raises on failure; the caller exits on success."""
    _run(["git", "fetch", "--progress", REPO_HTTPS_URL, "--tags", "--force"],
         "Downloading", progress)
    # --force: `uv sync` rewrites uv.lock in place, and a plain checkout refuses to
    # run against that. Only tracked files are discarded; data/ and config are ignored.
    _run(["git", "checkout", "--progress", "--force", "--detach", tag],
         "Checking out", progress)
    try:
        _run([_uv(), "sync", "--extra", "panel"], "Installing dependencies", progress)
    except RuntimeError:
        # Same fallback as run.sh: no panel driver still leaves a working kiosk.
        _run([_uv(), "sync"], "Installing dependencies", progress)


def _run(cmd: list[str], phase: str, progress: Progress | None = None) -> None:
    if progress:
        progress(phase, None)
    proc = subprocess.Popen(
        cmd, cwd=REPO_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
        text=True, env=_env(),
    )
    last, tail, fatal = time.monotonic(), "", ""

    def pump() -> None:
        nonlocal last, tail, fatal
        for line in proc.stderr:  # git separates progress with \r, a line ending in text mode
            last, line = time.monotonic(), line.strip()
            if not line:
                continue
            tail = line
            if not fatal and line.startswith(("fatal:", "error:")):
                fatal = line
            if progress:
                match = _PROGRESS.match(line)
                if match:
                    progress(match.group(1), int(match.group(2)))
                else:
                    progress(phase, None)

    reader = threading.Thread(target=pump, daemon=True)
    reader.start()
    while True:
        try:
            code = proc.wait(timeout=1)
            break
        except subprocess.TimeoutExpired:
            if time.monotonic() - last > _STALL_SECONDS:
                proc.kill()
                raise RuntimeError(f"{cmd[0]} {cmd[1]}: no progress for {_STALL_SECONDS}s")
    reader.join(timeout=5)
    if code:
        raise RuntimeError(f"{cmd[0]} {cmd[1]}: {fatal or tail or code}")


def _env() -> dict[str, str]:
    return {
        **os.environ,
        "UV_HTTP_TIMEOUT": str(_STALL_SECONDS),  # uv's own default is 30s per request
        "GIT_TERMINAL_PROMPT": "0",
    }
