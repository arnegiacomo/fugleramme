"""Self-update invariants. The network and git are faked: what matters here is
that only a strictly newer tag counts, that a failed check is retried sooner
than a good one, and that the loop installs exactly once per request - a retry
storm against a broken release would restart the frame every five seconds."""

from __future__ import annotations

import io
import json
import re
import sqlite3
import subprocess
import sys
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import DEFAULT, patch

import pytest

from fugleramme import service, updates
from fugleramme.api import ApiSource
from fugleramme.config import BIRDNET_PORT, DEFAULT_DETECTOR_URL, DEFAULT_PORT, REPO_ROOT
from fugleramme.picks import Picks
from fugleramme.settings import SettingsStore
from fugleramme.status import Status
from fugleramme.web import server


@pytest.fixture(autouse=True)
def _clear_cache():
    updates._next_check, updates._result = 0.0, None
    yield
    updates._next_check, updates._result = 0.0, None


def _release(tag: str):
    return io.BytesIO(json.dumps({"tag_name": tag}).encode())


@pytest.mark.parametrize(
    "latest,installed,expected",
    [
        ("v0.2.0", "0.1.0", "v0.2.0"),
        ("v0.10.0", "0.9.0", "v0.10.0"),
        ("v0.1.0", "0.1.0", None),  # same version is not an update
        ("v0.1.0", "0.2.0", None),  # never downgrade
    ],
)
def test_only_newer_tags_count(latest, installed, expected):
    with (
        patch.object(updates, "__version__", installed),
        patch("urllib.request.urlopen", return_value=_ctx(_release(latest))),
    ):
        assert updates.available() == expected


def _ctx(body):
    class Ctx:
        def __enter__(self):
            return body

        def __exit__(self, *exc):
            return False

    return Ctx()


def test_check_is_cached_until_forced():
    with patch("urllib.request.urlopen", return_value=_ctx(_release("v9.9.9"))) as get:
        updates.available()
        updates.available()
        assert get.call_count == 1
        updates.available(force=True)
        assert get.call_count == 2


def test_failed_check_retries_sooner_than_a_good_one():
    with patch("urllib.request.urlopen", side_effect=OSError("no route")):
        assert updates.available() is None
        failed_at = updates._next_check
    with patch("urllib.request.urlopen", return_value=_ctx(_release("v9.9.9"))):
        updates.available(force=True)
    assert failed_at < updates._next_check


def test_auto_update_installs_and_signals_a_restart():
    with (
        patch.object(service.updates, "available", return_value="v0.2.0"),
        patch.object(service.updates, "apply") as apply,
    ):
        status = Status()
        assert service._update(status, auto=False) is False
        assert status.update_available == "v0.2.0"
        assert not apply.called

        assert service._update(status, auto=True) is True
        assert apply.call_args.args[0] == "v0.2.0"


def test_admin_buttons_drive_the_status_object(tmp_path):
    """The Install button must not install: it asks the loop to, so the process
    never exits from inside a request."""
    status = Status()
    handler = server.make_handler(
        # Nothing here asks the detector anything: the buttons are status writes.
        ApiSource("http://127.0.0.1:1"),
        tmp_path,
        SettingsStore(tmp_path / "s.json"),
        Picks(tmp_path / "artwork.json"),
        None,
        status,
    )
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/admin"
    try:
        with patch.object(server.updates, "available", return_value="v0.2.0") as check:
            _post(url, "action=check")
            assert check.call_args.kwargs == {"force": True}
        assert status.update_available == "v0.2.0"

        _post(url, "action=update")
        assert status.update_requested == "v0.2.0"
        assert status.updating is False  # the loop owns the install, not the handler

        # What the admin page polls: requested counts as busy, so the page keeps
        # saying "installing…" until the loop is done and it can reload.
        state = f"http://127.0.0.1:{httpd.server_address[1]}/update"
        assert _get(state)["updating"] is True
        status.update_requested, status.updating = None, True
        assert _get(state)["updating"] is True
        status.updating = False
        assert _get(state)["updating"] is False

        _post(url, "checkboxes=auto_update&auto_update=on")
        assert SettingsStore(tmp_path / "s.json").get().auto_update is True
        # Unchecked is simply absent, so only the form declaring the box clears it.
        _post(url, "checkboxes=auto_update")
        assert SettingsStore(tmp_path / "s.json").get().auto_update is False

        _post(url, "checkboxes=auto_update&auto_update=on")
        _post(url, "checkboxes=show_names&rotation=90")  # the Display form: not its box
        saved = SettingsStore(tmp_path / "s.json").get()
        assert saved.auto_update is True and saved.show_names is False
    finally:
        httpd.shutdown()


def _get(url: str):
    with urllib.request.urlopen(url, timeout=5) as response:
        return json.load(response)


def _post(url: str, body: str):
    request = urllib.request.Request(url, data=body.encode(), method="POST")
    with urllib.request.urlopen(request, timeout=5) as response:
        return response.status


def test_checkout_is_forced_past_a_dirty_tree():
    """`uv sync` rewrites uv.lock on every run, so the Pi's checkout is always
    dirty; a plain checkout would abort and strand the frame on its old version."""
    checkout = next(c.args[0] for c in _apply_calls() if c.args[0][:2] == ["git", "checkout"])
    assert "--force" in checkout and checkout[-2:] == ["--detach", "v0.2.0"]


def test_git_progress_reaches_the_admin_page():
    """git writes progress to stderr, \\r-separated and only under --progress."""
    assert all(
        "--progress" in c.args[0]
        for c in _apply_calls()
        if c.args[0][:2] in (["git", "fetch"], ["git", "checkout"])
    )

    seen = []
    updates._run(
        [
            sys.executable,
            "-c",
            (
                r"import sys; sys.stderr.write("
                r"'Receiving objects:  45% (450/1000), 12.35 MiB | 3.40 MiB/s\rdone\n')"
            ),
        ],
        "Downloading",
        lambda phase, percent: seen.append((phase, percent)),
    )
    assert ("Receiving objects", 45) in seen
    assert seen[0] == ("Downloading", None)  # a phase is shown before any output
    assert seen[-1] == ("Downloading", None)  # a line without a percent keeps the label


def test_a_stalled_download_fails_but_a_slow_one_does_not(monkeypatch):
    monkeypatch.setattr(updates, "_STALL_SECONDS", 0)
    with pytest.raises(RuntimeError, match="no progress"):
        updates._run([sys.executable, "-c", "import time; time.sleep(30)"], "Downloading")


def test_stale_tags_are_pruned_through_the_patched_seam():
    """Every git call in apply() must go through _run. A tag delete issued straight
    to subprocess escapes this patch and deletes the tags of whoever runs the tests."""
    listing = subprocess.CompletedProcess([], 0, stdout="v0.1.0\nv0.2.0\nv0.3.0\n")
    with (
        patch.object(updates, "_run") as run,
        patch.object(updates.subprocess, "run", return_value=listing),
        patch.object(updates, "_converge_detector"),
    ):
        updates.apply("v0.2.0")
    deletes = [c.args[0] for c in run.call_args_list if c.args[0][:2] == ["git", "tag"]]
    assert deletes == [["git", "tag", "--delete", "v0.1.0", "v0.3.0"]]


def _apply_calls():
    with patch.object(updates, "_run") as run, patch.object(updates, "_converge_detector"):
        updates.apply("v0.2.0")
    return run.call_args_list


def test_a_failed_install_does_not_retry_every_tick():
    with (
        patch.object(service.updates, "available", return_value="v0.2.0"),
        patch.object(service.updates, "apply", side_effect=RuntimeError("dirty tree")) as apply,
    ):
        status = Status()
        assert service._update(status, auto=True) is False
        assert status.update_error == "dirty tree"
        assert status.updating is False

        assert service._update(status, auto=True) is False
        apply.assert_called_once()


def _converged(tmp_path, **patches):
    """A checkout run.sh has converged: `.env` beside the compose file is what
    tells the update this is an appliance and not somebody's dev tree."""
    (tmp_path / "detector").mkdir(exist_ok=True)
    (tmp_path / "detector" / ".env").write_text("BIRDNET_UID=1000\n")
    return patch.multiple(updates, REPO_ROOT=tmp_path, **patches)


def test_the_detector_is_brought_onto_the_pin_the_release_carries(tmp_path):
    """An update that changes docker-compose.yml has to reach the container, or
    the pin is decorative: the frame moves and the detector stays where it was."""
    with _converged(tmp_path, _run=DEFAULT, _backup_db=DEFAULT) as patched:
        updates._converge_detector()
    command = patched["_run"].call_args.args[0]
    assert command[:2] == ["docker", "compose"] and command[-2:] == ["up", "-d"]
    assert str(tmp_path / "detector" / ".env") in command  # UID/GID/ALSA_CARD
    # No --force-recreate: an unchanged pin must not bounce a working detector.
    assert "--force-recreate" not in command


def test_a_dev_checkout_never_touches_docker(tmp_path):
    with patch.multiple(updates, REPO_ROOT=tmp_path, _run=DEFAULT) as patched:
        updates._converge_detector()
    assert not patched["_run"].called


def test_a_detector_that_will_not_update_does_not_fail_the_frame_update(tmp_path):
    """The frame is already checked out and synced by this point. A missing docker,
    a denied socket or a failed pull must leave it on the new version anyway."""
    for failure in (RuntimeError("pull failed"), FileNotFoundError("docker")):
        with _converged(tmp_path, _backup_db=DEFAULT, _run=DEFAULT) as patched:
            patched["_run"].side_effect = failure
            updates._converge_detector()


def test_the_container_is_left_alone_when_the_backup_fails(tmp_path):
    """The new container migrates the DB in place on first start. With no copy to
    fall back on, the old container is the safe place to stay."""
    with _converged(tmp_path, _run=DEFAULT, _backup_db=DEFAULT) as patched:
        patched["_backup_db"].side_effect = sqlite3.OperationalError("disk full")
        updates._converge_detector()
    assert not patched["_run"].called


def test_the_backup_captures_the_detections(tmp_path):
    db = tmp_path / "birdnet.db"
    with sqlite3.connect(db) as conn:
        conn.execute("CREATE TABLE detections (id INTEGER)")
        conn.execute("INSERT INTO detections VALUES (1), (2)")
    with patch.object(updates, "DEFAULT_DB_PATH", db):
        updates._backup_db()
    with sqlite3.connect(tmp_path / "birdnet.db.bak") as backup:
        assert backup.execute("SELECT count(*) FROM detections").fetchone()[0] == 2


def test_a_missing_database_is_not_a_backup_failure(tmp_path):
    """First boot: BirdNET-Go has not created it yet, and there is nothing to lose."""
    with patch.object(updates, "DEFAULT_DB_PATH", tmp_path / "absent.db"):
        updates._backup_db()


# The self-update never re-runs run.sh, so an appliance keeps the unit, the
# detector/.env and the settings.json it was installed with: every default
# introduced later has to reproduce what it already runs on.


def _run_sh() -> str:
    return (REPO_ROOT / "run.sh").read_text()


def _default(name: str) -> str:
    return re.search(rf'^{name}="?([^"\n]*)"?$', _run_sh(), re.MULTILINE).group(1)


def test_a_checkout_with_no_frame_env_converges_onto_todays_layout():
    assert _default("FRAME_PORT") == str(DEFAULT_PORT)
    assert _default("BIRDNET_PORT") == str(BIRDNET_PORT)
    assert _default("DETECTOR_MODE") == "bundled"
    assert _default("DETECTOR_URL") == DEFAULT_DETECTOR_URL
    # Read only when it is there, so an existing checkout takes the block above.
    assert '[[ -f "$REPO_ROOT/frame.env" ]]' in _run_sh()


def test_a_detector_env_from_before_the_port_was_a_choice_still_publishes_8090():
    """`updates._converge_detector` runs compose against the .env the Pi already
    has, which carries no BIRDNET_PORT - the inline default is what holds it."""
    compose = (REPO_ROOT / "detector" / "docker-compose.yml").read_text()
    assert f'"${{BIRDNET_PORT:-{BIRDNET_PORT}}}:8080"' in compose
