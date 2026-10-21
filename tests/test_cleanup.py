"""Cleanup removes what earlier releases left behind, and nothing else."""

from __future__ import annotations

from fugleramme import cleanup


def test_the_leftovers_go_and_the_settings_stay(tmp_path):
    (tmp_path / "artwork.json").write_text("{}")
    (tmp_path / "settings.json").write_text("{}")
    cleanup.run(tmp_path)
    assert [p.name for p in tmp_path.iterdir()] == ["settings.json"]


def test_every_task_is_safe_to_run_again(tmp_path):
    # It runs on every startup, long after the leftover is gone.
    cleanup.run(tmp_path)
    cleanup.run(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_a_failing_task_does_not_stop_the_rest(tmp_path, monkeypatch, caplog):
    ran = []

    def boom(_data_dir):
        raise OSError("read-only file system")

    tasks = (
        cleanup.Task("boom", cleanup.date(2027, 1, 1), boom),
        cleanup.Task("next", cleanup.date(2027, 1, 1), ran.append),
    )
    monkeypatch.setattr(cleanup, "TASKS", tasks)
    cleanup.run(tmp_path)
    assert ran == [tmp_path]
    assert "Cleanup task boom failed" in caplog.text
