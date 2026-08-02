"""Self-update invariants. The network and git are faked: what matters here is
that only a strictly newer tag counts, that a failed check is retried sooner
than a good one, and that the loop installs exactly once per request - a retry
storm against a broken release would restart the frame every five seconds."""

from __future__ import annotations

import io
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import pytest

from fugleramme import server, service, updates
from fugleramme.db import Database
from fugleramme.settings import SettingsStore
from fugleramme.status import Status


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
    with patch.object(updates, "__version__", installed), \
         patch("urllib.request.urlopen", return_value=_ctx(_release(latest))):
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
    with patch.object(service.updates, "available", return_value="v0.2.0"), \
         patch.object(service.updates, "apply") as apply:
        status = Status()
        assert service._update(status, auto=False) is False
        assert status.update_available == "v0.2.0"
        assert not apply.called

        assert service._update(status, auto=True) is True
        apply.assert_called_once_with("v0.2.0")


def test_admin_buttons_drive_the_status_object(tmp_path):
    """The Install button must not install: it asks the loop to, so the process
    never exits from inside a request."""
    status = Status()
    handler = server.make_handler(
        Database(tmp_path / "absent.db"), tmp_path, SettingsStore(tmp_path / "s.json"),
        None, status,
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

        _post(url, "rotation=90&auto_update=on")
        assert SettingsStore(tmp_path / "s.json").get().auto_update is True
        _post(url, "rotation=90")  # unchecked box is simply absent from the form
        assert SettingsStore(tmp_path / "s.json").get().auto_update is False
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
    with patch.object(updates, "_run") as run:
        updates.apply("v0.2.0")
    checkout = next(c.args[0] for c in run.call_args_list if c.args[0][:2] == ["git", "checkout"])
    assert checkout == ["git", "checkout", "--force", "--detach", "v0.2.0"]


def test_a_failed_install_does_not_retry_every_tick():
    with patch.object(service.updates, "available", return_value="v0.2.0"), \
         patch.object(service.updates, "apply", side_effect=RuntimeError("dirty tree")) as apply:
        status = Status()
        assert service._update(status, auto=True) is False
        assert status.update_error == "dirty tree"
        assert status.updating is False

        assert service._update(status, auto=True) is False
        apply.assert_called_once()
