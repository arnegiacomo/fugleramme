"""The conformance check: the same assertions against the fake or a real station."""

from __future__ import annotations

from fugleramme.check import run


def test_a_healthy_detector_answers_everything(detector, tmp_path, capsys):
    url, _httpd = detector()
    assert run(url, "", "", tmp_path) == 0
    assert "FAIL" not in capsys.readouterr().out


def test_a_detector_that_is_gone_fails_every_query(detector, tmp_path, capsys):
    url, httpd = detector()
    httpd.shutdown()
    httpd.server_close()

    assert run(url, "", "", tmp_path) == 1
    out = capsys.readouterr().out
    assert "FAIL reachable" in out and "failed" in out


def test_a_private_detector_fails_without_credentials(detector, tmp_path):
    url, _httpd = detector(password="hunter2")
    assert run(url, "", "", tmp_path) == 1
    assert run(url, "birdnet", "hunter2", tmp_path) == 0
