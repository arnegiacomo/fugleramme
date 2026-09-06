"""The fake BirdNET-Go: the API shapes the frame will read, and the states it
has to survive - a private-mode install and an unreachable one."""

from __future__ import annotations

import gzip
import json
import urllib.error
import urllib.request
from datetime import datetime, timedelta

import pytest

from fugleramme import fake


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """The callback's 302 is the response under test - following it loses the cookie."""

    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def _fetch(url: str, method: str = "GET", headers: dict | None = None, body: bytes | None = None):
    request = urllib.request.Request(url, method=method, headers=headers or {}, data=body)
    try:
        with _opener.open(request, timeout=10) as response:
            raw = response.read()
            if response.headers.get("Content-Encoding") == "gzip":
                raw = gzip.decompress(raw)
            return response.status, dict(response.headers), raw
    except urllib.error.HTTPError as error:
        return error.status, dict(error.headers), error.read()


def _json(url: str, **kwargs):
    status, _headers, body = _fetch(url, **kwargs)
    return status, json.loads(body)


@pytest.fixture
def api():
    """The fake on an OS-assigned port; the factory takes the same flags as the CLI."""
    servers = []

    def start(count: int = 40, seed: int = 1, **kwargs):
        httpd = fake.serve(fake.generate(count, seed), "127.0.0.1", 0, **kwargs)
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}{fake.API}"

    yield start
    for httpd in servers:
        httpd.shutdown()


def test_summary_windows_the_range_and_drops_false_positives(api):
    base = api()
    today = datetime.now().astimezone()
    week = (today - timedelta(days=7)).strftime("%Y-%m-%d")

    status, all_time = _json(f"{base}/analytics/species/summary")
    assert status == 200
    _status, windowed = _json(f"{base}/analytics/species/summary?start_date={week}")

    counts = [row["count"] for row in all_time]
    assert counts == sorted(counts, reverse=True)
    assert sum(row["count"] for row in windowed) < sum(counts)

    _status, recent = _json(f"{base}/detections/recent?limit=100")
    kept = sum(1 for row in recent if row["verified"] != "false_positive")
    assert sum(counts) == kept  # analytics exclude what recent still shows

    # first/last_heard are RFC3339 with an offset, not the bare dates the
    # detections carry.
    assert datetime.fromisoformat(all_time[0]["first_heard"]).tzinfo is not None


def test_summary_limit_keeps_the_busiest(api):
    base = api()
    _status, full = _json(f"{base}/analytics/species/summary")
    _status, capped = _json(f"{base}/analytics/species/summary?limit=3")
    assert capped == full[:3]


def test_recent_is_newest_first_and_respects_limit(api):
    base = api()
    status, rows = _json(f"{base}/detections/recent?limit=5")
    assert status == 200
    assert len(rows) == 5

    moments = [f"{row['date']} {row['time']}" for row in rows]
    assert moments == sorted(moments, reverse=True)
    assert rows[0]["scientificName"] in fake.SPECIES
    assert rows[0]["commonName"]


def test_only_listed_locales_with_a_dictionary_answer(api):
    base = api()
    status, listed = _json(f"{base}/settings/locales")
    assert status == 200
    # BirdNET-Go's own disagreement: listed as "no", answers as "nb".
    assert "no" in listed and "nb" not in listed

    assert _fetch(f"{base}/species/dictionary/nb", method="HEAD")[0] == 200
    assert _fetch(f"{base}/species/dictionary/no", method="HEAD")[0] == 404
    assert _fetch(f"{base}/species/dictionary/el", method="HEAD")[0] == 404


def test_a_dictionary_revalidates_by_etag(api):
    base = api()
    status, headers, body = _fetch(f"{base}/species/dictionary/nb")
    assert status == 200
    assert json.loads(body)["Turdus merula"] == "svarttrost"

    # "Etag", as BirdNET-Go spells it: the frame has to find it whatever the case.
    etag = headers["Etag"]
    assert _fetch(f"{base}/species/dictionary/nb", headers={"If-None-Match": etag})[0] == 304


def test_auth_gates_everything_until_login(api):
    base = api(password="hunter2")
    assert _fetch(f"{base}/ping")[0] == 401
    assert _fetch(f"{base}/settings/locales")[0] == 401

    login = json.dumps({"username": "birdnet", "password": "hunter2"}).encode()
    assert _json(f"{base}/auth/login", method="POST", body=json.dumps({}).encode())[0] == 400
    assert (
        _json(
            f"{base}/auth/login",
            method="POST",
            body=json.dumps({"username": "birdnet", "password": "wrong"}).encode(),
        )[0]
        == 401
    )

    status, response = _json(f"{base}/auth/login", method="POST", body=login)
    assert status == 200 and response["success"]

    # The login only hands out a code; the callback is what sets the session cookie.
    status, headers, _body = _fetch(base.removesuffix(fake.API) + response["redirectUrl"])
    assert status == 302
    cookie = headers["Set-Cookie"].split(";")[0]
    assert _json(f"{base}/ping", headers={"Cookie": cookie}) == (200, {"status": "ok"})


def test_a_down_detector_answers_503_not_an_empty_page(api):
    base = api(down=True)
    for route in ("/ping", "/detections/recent", "/analytics/species/summary"):
        assert _fetch(base + route)[0] == 503
