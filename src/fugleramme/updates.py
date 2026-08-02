"""Release checks and the self-update, driven by GitHub tags.

`Restart=always` on the unit means updating needs no privileges: check out the
tag, sync, exit, and systemd brings the new code up.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import __version__
from .config import RELEASES_API, REPO_HTTPS_URL, REPO_ROOT

log = logging.getLogger(__name__)

_OK_TTL = 3600  # unauthenticated GitHub allows 60 requests/hour per IP
_FAIL_TTL = 300
_next_check = 0.0
_result: str | None = None


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


def apply(tag: str) -> None:
    """Move the checkout onto `tag`. Raises on failure; the caller exits on success."""
    _run(["git", "fetch", REPO_HTTPS_URL, "--tags", "--force"])
    # --force: `uv sync` rewrites uv.lock in place, and a plain checkout refuses to
    # run against that. Only tracked files are discarded; data/ and config are ignored.
    _run(["git", "checkout", "--force", "--detach", tag])
    try:
        _run([_uv(), "sync", "--extra", "panel"])
    except RuntimeError:
        # Same fallback as setup.sh: no panel driver still leaves a working kiosk.
        _run([_uv(), "sync"])


def _run(cmd: list[str]) -> None:
    result = subprocess.run(
        cmd, cwd=REPO_ROOT, capture_output=True, text=True, timeout=600
    )
    if result.returncode:
        tail = result.stderr.strip().splitlines()
        raise RuntimeError(f"{cmd[0]} {cmd[1]}: {tail[-1] if tail else result.returncode}")
