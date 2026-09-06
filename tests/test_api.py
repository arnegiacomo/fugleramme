"""What the frame reads off BirdNET-Go's API.

The invariant at the top is the one that matters: a detector that will not answer
raises, and only one that answers with nothing reads as no birds. Getting that
wrong empties the page on the first timeout.
"""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import UTC, datetime, time, timedelta, timezone
from urllib.request import urlopen

import pytest

from fugleramme import api, fake
from fugleramme.api import ApiSource
from fugleramme.source import Unavailable

WINDOW = 6
_SUMMARY = "/analytics/species/summary"
BLACKBIRD, TIT = "Turdus merula", "Parus major"


def _raw(url: str, route: str):
    with urlopen(url + api.API + route, timeout=10) as response:
        return json.load(response)


def _asked(source: ApiSource) -> list:
    return [
        source.latest,
        source.life_list,
        source.stats,
        lambda: source.recent(5),
        lambda: source.species_since(WINDOW),
        lambda: source.species_since(24),
        lambda: source.species_since(0),
    ]


def test_a_detector_that_will_not_answer_raises(source):
    for call in _asked(source(down=True)):
        with pytest.raises(Unavailable):
            call()


def test_a_detector_that_is_not_there_raises(detector):
    url, httpd = detector()
    httpd.shutdown()
    httpd.server_close()
    for call in _asked(ApiSource(url)):
        with pytest.raises(Unavailable):
            call()


def test_a_detector_with_no_birds_reads_as_empty(source):
    quiet = source(count=0)
    assert quiet.species_since(24) == []
    assert quiet.species_since(WINDOW) == []
    assert quiet.life_list() == []
    assert quiet.latest() is None


def test_species_are_ranked_by_count_then_name(source):
    counts = [count for _name, count in source().species_since(0)]
    assert counts == sorted(counts, reverse=True)


def test_a_sub_day_window_is_counted_from_the_feed_without_false_positives(detector):
    url, _httpd = detector(count=300, seed=4)
    since = datetime.now(UTC) - timedelta(hours=WINDOW)
    rows = [
        row
        for row in _raw(url, "/detections/recent?limit=1000")
        if datetime.fromisoformat(f"{row['date']}T{row['time']}").astimezone() >= since
    ]
    assert any(row["verified"] == "false_positive" for row in rows)  # else this proves nothing

    heard = Counter(row["scientificName"] for row in rows if row["verified"] != "false_positive")
    assert ApiSource(url).species_since(WINDOW) == sorted(
        heard.items(), key=lambda pair: (-pair[1], pair[0])
    )


def test_a_sub_day_window_holds_less_than_the_day_around_it(source):
    detections = source(count=300, seed=4)
    assert sum(n for _, n in detections.species_since(WINDOW)) < sum(
        n for _, n in detections.species_since(24)
    )


def test_the_station_clock_comes_off_the_summary_not_the_frames(detector, monkeypatch):
    """The feed's date and time carry no offset, so a detector in another
    timezone would land hours out."""
    url, _httpd = detector()
    monkeypatch.setattr(api, "_local", lambda: timezone(timedelta(hours=7)))

    heard = max(datetime.fromisoformat(row["last_heard"]) for row in _raw(url, _SUMMARY))
    newest = ApiSource(url).latest()
    assert newest is not None and newest.detected_at == heard


def test_a_repeated_question_is_answered_without_asking_again(detector):
    url, httpd = detector()
    detections = ApiSource(url)
    first = detections.species_since(0)

    httpd.shutdown()
    httpd.server_close()
    assert detections.species_since(0) == first  # the TTL cache, not a second round trip


def test_a_private_detector_needs_credentials(source):
    with pytest.raises(Unavailable):
        source(password="hunter2").species_since(0)


def test_bad_credentials_fail_rather_than_retry_forever(detector):
    url, _httpd = detector(password="hunter2")
    with pytest.raises(Unavailable):
        ApiSource(url, "birdnet", "wrong").species_since(0)


def _sessions(httpd) -> set:
    """The fake holds its sessions in a closure - expiring one is the only way to
    make a live source meet a 401 mid-run."""
    cells = httpd.RequestHandlerClass._authorized.__closure__
    return next(cell.cell_contents for cell in cells if isinstance(cell.cell_contents, set))


def test_a_lapsed_session_is_renewed_once(detector):
    url, httpd = detector(password="hunter2")
    detections = ApiSource(url, "birdnet", "hunter2")
    assert detections.species_since(0)  # 401, log in, ask again

    _sessions(httpd).clear()  # BirdNET-Go restarted under us
    detections._cache.clear()
    assert detections.species_since(0)


def _row(id_: int, at: datetime, name: str) -> fake.Detection:
    return fake.Detection(id_, at, name, 0.9, False)


def test_a_day_window_drops_a_bird_heard_before_the_cutoff(detector):
    """The summary filters on whole dates, so its range reaches back past the
    cutoff: untrimmed, a bird last heard in the small hours of yesterday would
    sit on a page the frame calls today."""
    now = datetime.now().astimezone()
    stale = datetime.combine(now.date() - timedelta(days=1), time(), now.tzinfo)
    url, _httpd = detector(rows=[_row(2, now - timedelta(hours=1), BLACKBIRD), _row(1, stale, TIT)])

    ranged = _raw(url, f"{_SUMMARY}?start_date={stale:%Y-%m-%d}")
    assert {row["scientific_name"] for row in ranged} == {
        BLACKBIRD,
        TIT,
    }  # the date range holds both

    assert ApiSource(url).species_since(24) == [(BLACKBIRD, 1)]
    assert ApiSource(url).species_since(0) == [(TIT, 1), (BLACKBIRD, 1)]  # all time keeps it


def test_a_window_the_feed_cannot_reach_falls_back_to_the_summary(detector, monkeypatch, caplog):
    """A busy feeder can fill the feed inside the window. Counting what came
    back would drop the species below the cut without saying so, and the
    day-shaped summary is over-inclusive at worst."""
    now = datetime.now().astimezone()
    rows = [_row(4 - i, now - timedelta(minutes=i + 1), BLACKBIRD) for i in range(3)]
    rows.append(_row(1, now - timedelta(minutes=4), TIT))
    url, _httpd = detector(rows=rows)

    with caplog.at_level(logging.WARNING):
        monkeypatch.setattr(api, "_WINDOW_SCAN", 3)  # truncated one row short of the tit
        assert ApiSource(url).species_since(WINDOW) == [(BLACKBIRD, 3), (TIT, 1)]
        assert "do not reach" in caplog.text

        caplog.clear()
        monkeypatch.setattr(api, "_WINDOW_SCAN", 10)  # the whole feed fits, so no alarm
        assert ApiSource(url).species_since(WINDOW) == [(BLACKBIRD, 3), (TIT, 1)]
        assert not caplog.text


def test_an_unreachable_detector_is_only_asked_once_a_tick(detector, monkeypatch):
    """A hostname that will not resolve costs a DNS timeout per call, and one
    admin page makes five. The TTL has to hold the failure, not just the answer."""
    url, httpd = detector()
    httpd.shutdown()
    httpd.server_close()
    detections = ApiSource(url)

    with pytest.raises(Unavailable):
        detections.species_since(0)

    def refuse():
        raise AssertionError("asked the detector again inside the TTL")

    monkeypatch.setattr(detections, "_get", lambda *a, **k: refuse())
    with pytest.raises(Unavailable):
        detections.species_since(0)


def test_the_login_sends_birdnet_gos_own_client_id_when_none_is_configured(detector, monkeypatch):
    """BirdNET-Go prompts for a password alone but its login rejects an empty
    username, matching what it is given against `security.basicauth.clientid`.
    So the admin asks for no username and the frame sends that id."""
    url, _httpd = detector(password="hunter2")
    sent = []
    opened = api.ApiSource._open

    def record(self, url_, method="GET", headers=None, data=None):
        if data:
            sent.append(json.loads(data))
        return opened(self, url_, method, headers, data)

    monkeypatch.setattr(api.ApiSource, "_open", record)
    source = api.ApiSource(url, "", "hunter2")  # a password, no username

    assert source.species_since(24) is not None  # the fake 400s an empty username
    assert [payload["username"] for payload in sent] == [api.CLIENT_ID]


def test_a_rejected_login_leaves_the_401_that_provoked_it(detector, caplog):
    """The connection test reads that 401 as "credentials rejected". The login's
    own words would name a client id the reader never entered, so they go to the
    log instead."""
    url, _httpd = detector(password="hunter2")
    source = api.ApiSource(url, "", "wrong")

    with caplog.at_level(logging.WARNING):
        assert source.request(_SUMMARY)[0] == 401
    assert "401" in caplog.text


def test_a_response_header_is_found_whatever_case_it_arrived_in(detector):
    """BirdNET-Go spells it "Etag". Read off a plain dict keyed as it came, the
    frame would never send If-None-Match and would re-fetch every dictionary."""
    url, _httpd = detector()
    _status, headers, _body = api.ApiSource(url).request("/species/dictionary/nb")
    assert headers["etag"]
