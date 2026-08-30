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
import sqlite3
import subprocess
import threading
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from . import __version__
from .config import DEFAULT_DB_PATH, RELEASES_API, REPO_HTTPS_URL, REPO_ROOT

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
    # One tag, shallow: a full fetch would pull every past version of the artwork.
    _run(
        ["git", "fetch", "--progress", "--depth", "1", REPO_HTTPS_URL, "tag", tag, "--force"],
        "Downloading",
        progress,
    )
    # --force: `uv sync` rewrites uv.lock in place, and a plain checkout refuses to
    # run against that. Only tracked files are discarded; data/ and config are ignored.
    _run(["git", "checkout", "--progress", "--force", "--detach", tag], "Checking out", progress)
    _drop_stale_tags(tag, progress)
    try:
        _run([_uv(), "sync", "--extra", "panel"], "Installing dependencies", progress)
    except RuntimeError:
        # Same fallback as run.sh: no panel driver still leaves a working kiosk.
        _run([_uv(), "sync"], "Installing dependencies", progress)
    _converge_detector(progress)


def _converge_detector(progress: Progress | None = None) -> None:
    """Bring the container onto the image the new checkout pins. `up -d` pulls a
    tag that is not local yet and recreates only what changed, so a release that
    left the pin alone costs a second. Not fatal: the frame is already on the new
    version, and a detector left on its old container still serves the DB."""
    env_file = REPO_ROOT / "detector" / ".env"
    if not env_file.exists():
        return  # run.sh writes it, so this is a dev checkout, not an appliance
    try:
        _backup_db(progress)
        _run(
            [
                "docker",
                "compose",
                "--env-file",
                str(env_file),
                "-f",
                str(REPO_ROOT / "detector" / "docker-compose.yml"),
                "up",
                "-d",
            ],
            "Updating the detector",
            progress,
        )
    except (RuntimeError, OSError, sqlite3.Error) as exc:
        log.warning("Detector left on its current image: %s", exc)


def _backup_db(progress: Progress | None = None) -> None:
    """A copy beside the original, taken before the new container migrates it in
    place - upstream has shipped migrations that lost the database, and the
    detections are the one thing here that cannot be fetched again. Raising skips
    the swap: an un-backed-up migration is the risk this whole step exists for."""
    if not DEFAULT_DB_PATH.exists():
        return  # the unit runs with no --db, so the appliance's DB is the default one
    if progress:
        progress("Backing up detections", None)
    source = sqlite3.connect(f"file:{DEFAULT_DB_PATH}?mode=ro", uri=True)
    target = sqlite3.connect(DEFAULT_DB_PATH.with_suffix(".db.bak"))
    try:
        source.backup(target)  # consistent under WAL, which copying the file is not
    finally:
        target.close()
        source.close()


def _drop_stale_tags(keep: str, progress: Progress | None = None) -> None:
    """Delete every release tag but the one just checked out: each one pins a whole
    copy of the artwork that `git gc` can never reclaim. The delete goes through
    `_run` like every other git call here - reaching for subprocess directly puts
    it outside the seam the tests patch, and it deletes the developer's own tags."""
    listed = subprocess.run(
        ["git", "tag", "--list"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        env=_env(),
        check=False,
    ).stdout.split()
    if stale := [t for t in listed if t != keep]:
        _run(["git", "tag", "--delete", *stale], "Tidying up", progress)


def _run(cmd: list[str], phase: str, progress: Progress | None = None) -> None:
    if progress:
        progress(phase, None)
    proc = subprocess.Popen(
        cmd,
        cwd=REPO_ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=_env(),
    )
    stderr = proc.stderr
    assert stderr is not None  # stderr=PIPE
    last, tail, fatal = time.monotonic(), "", ""

    def pump() -> None:
        nonlocal last, tail, fatal
        for line in stderr:  # git separates progress with \r, a line ending in text mode
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
                raise RuntimeError(
                    f"{cmd[0]} {cmd[1]}: no progress for {_STALL_SECONDS}s"
                ) from None
    reader.join(timeout=5)
    if code:
        raise RuntimeError(f"{cmd[0]} {cmd[1]}: {fatal or tail or code}")


def _env() -> dict[str, str]:
    return {
        **os.environ,
        "UV_HTTP_TIMEOUT": str(_STALL_SECONDS),  # uv's own default is 30s per request
        "GIT_TERMINAL_PROMPT": "0",
    }
