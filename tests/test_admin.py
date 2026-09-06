"""Admin page invariants. The markup, the style and the script are files of
their own now, so only a render proves that the template's slots, the page's
asset links and the values admin.js reads still line up."""

from __future__ import annotations

import json
import re

import pytest

from fugleramme import languages, modes
from fugleramme.config import BIRDNET_PORT
from fugleramme.languages import namer
from fugleramme.picks import Picks
from fugleramme.settings import Settings, SettingsStore
from fugleramme.source import NEEDS_PASSWORD
from fugleramme.status import Status
from fugleramme.web import STATIC_DIR, admin, server

PANEL = (1600, 1200)


def _page(tmp_path, source, names_dir=None, **overrides) -> str:
    settings = Settings(**overrides)
    ctx = modes.context(
        source,
        tmp_path,
        Picks(tmp_path / "artwork.json"),
        settings,
        namer("sci", "", tmp_path),
        settings.web_size(PANEL),
    )
    return admin.page(ctx, settings, Status(), PANEL, True, names_dir or tmp_path)


def _config(page: str) -> dict:
    return json.loads(
        re.search(r'<script id="config"[^>]*>(.*?)</script>', page, re.DOTALL).group(1)
    )


def test_the_page_renders_before_anything_has_written_to_the_data_dir(tmp_path, source):
    # A fresh checkout has no detector/data: nothing has saved settings, picks or
    # a dictionary yet, and the admin is where the frame is first reached (#43).
    assert "$" not in _page(tmp_path, source(), names_dir=tmp_path / "data")


@pytest.mark.parametrize("mode", list(modes.MODES))
def test_every_slot_in_the_template_is_filled(tmp_path, source, mode):
    # substitute raises on a slot with no value; a leftover $ is the other way round.
    assert "$" not in _page(tmp_path, source(), mode=mode)


def test_the_page_still_fills_every_slot_with_the_detector_gone(tmp_path, source):
    page = _page(tmp_path, source(down=True))
    assert "$" not in page
    assert "detector unreachable" in page


def test_every_asset_the_page_links_is_one_the_server_serves(tmp_path, source):
    linked = set(re.findall(r'(?:href|src)="(/[^"?]*)', _page(tmp_path, source())))
    assert linked == {"/", "/admin.css", "/admin.js"}
    assert linked <= set(server.FILES)


def test_the_config_blob_carries_everything_admin_js_reads(tmp_path, source):
    """The script is static, so this blob is its only channel from the frame."""
    blob = _config(_page(tmp_path, source()))
    used = set(re.findall(r"\bcfg\.(\w+)", (STATIC_DIR / "admin.js").read_text()))
    assert used and used <= set(blob)


def test_a_species_with_no_artwork_is_marked_rather_than_dropped(tmp_path):
    name_of = namer("sci", "", tmp_path)
    html = admin.species_html([("Pica pica", "gould"), ("Corvus cornix", None)], name_of)
    assert html.count("<li") == 2
    assert 'class="noart"' in html and "Corvus cornix" in html
    assert admin.species_html([], name_of) == '<li class="empty">none yet</li>'


def test_the_update_row_offers_the_install_only_once_a_release_is_known():
    status = Status()
    assert "Check" in admin._update(status)

    status.update_available = "v9.9.9"
    assert "Install" in admin._update(status)

    status.update_available, status.updating = None, True
    assert "<progress" in admin._update(status)  # no button while it installs


def test_the_detector_row_carries_the_version_it_reports():
    """The version has to survive a detector that answers without one."""
    assert "20260823" in admin._detector("ok", "20260823", True)
    assert admin._detector("ok", "", True) == admin._state(True, "running", "unreachable")
    assert "unreachable" in admin._detector("down", "", False)


def test_the_detector_row_says_a_password_is_wanted_rather_than_unreachable():
    # PrivateMode with no password: /health is gated, and the page read nothing.
    row = admin._detector("auth", "", False)
    assert row == '<span class="bad">running · needs a password</span>'

    # Only the settings gated: /health answers, and the locale list is what did not.
    row = admin._detector("ok", "20260823", True, NEEDS_PASSWORD)
    assert row == '<span class="warn">running · 20260823 · needs a password</span>'
    assert "needs a password" not in admin._detector("ok", "20260823", True)


def test_a_working_password_is_not_reported_as_a_missing_one():
    """/health is asked without credentials, so PrivateMode answers 401 to every
    frame alike - the ones holding a working password included."""
    assert admin._detector("auth", "", True) == '<span class="ok">running</span>'


def test_the_credentials_fold_away_until_there_is_one_to_show(tmp_path, source):
    """PrivateMode is the rare case, so the common form is the address alone."""
    assert '<details id="credentials">' in _page(tmp_path, source())
    assert '<details id="credentials" open>' in _page(
        tmp_path, source(), detector_password="hunter2"
    )


def test_a_stored_password_never_reaches_the_page(tmp_path, source):
    page = _page(tmp_path, source(), detector_password="hunter2")
    assert "hunter2" not in page
    assert admin.PASSWORD_SET in page


def test_the_placeholder_posts_back_as_leave_it_alone():
    kept = admin.form_changes({"detector_password": [admin.PASSWORD_SET]})
    assert "detector_password" not in kept  # so merged() keeps the stored one

    typed = admin.form_changes({"detector_password": ["hunter3"]})
    assert typed["detector_password"] == "hunter3"

    cleared = admin.form_changes({"detector_password": [""]})
    assert cleared["detector_password"] == ""


def test_saving_the_form_untouched_leaves_the_password_standing(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    store.update(detector_url="http://pi:8090", detector_password="hunter2")
    form = {
        "detector_url": ["http://pi:8090"],
        "detector_username": [""],
        "detector_password": [admin.PASSWORD_SET],
    }
    assert store.update(**admin.form_changes(form)).detector_password == "hunter2"


@pytest.mark.parametrize(
    "url,expected",
    [
        ("http://127.0.0.1:8090", ("http://127.0.0.1:8090", 8090)),
        ("http://localhost:9000", ("http://localhost:9000", 9000)),
        ("http://127.0.0.1", ("http://127.0.0.1", BIRDNET_PORT)),
        ("http://birdnet.local:8080", ("http://birdnet.local:8080", None)),
        ("http://192.168.1.9:8080", ("http://192.168.1.9:8080", None)),
    ],
)
def test_the_birdnet_link_only_substitutes_this_host_for_a_loopback_one(url, expected):
    """A remote browser cannot follow the Pi's own 127.0.0.1, and must not have
    its own hostname put in front of a detector on another machine."""
    assert admin.birdnet_link(url) == expected


def test_the_page_carries_the_link_for_a_detector_on_another_machine(tmp_path, source):
    blob = _config(_page(tmp_path, source(), detector_url="http://birdnet.local:8080"))
    assert blob["birdnetUrl"] == "http://birdnet.local:8080"
    assert blob["birdnetPort"] is None


def test_the_connection_test_tells_the_three_answers_apart(detector):
    url, httpd = detector(password="hunter2")
    settings = Settings(detector_url=url)

    def try_(password: str) -> str:
        return admin.connection({"detector_password": [password]}, settings)["state"]

    assert admin.connection({}, settings)["state"] == "auth"  # no credentials at all
    assert try_("wrong") == "auth"
    assert try_("hunter2") == "ok"

    httpd.shutdown()
    httpd.server_close()
    assert admin.connection({}, settings)["state"] == "unreachable"


def test_the_connection_test_reads_the_stored_password_behind_the_placeholder(detector):
    url, _httpd = detector(password="hunter2")
    settings = Settings(detector_url=url, detector_password="hunter2")
    assert admin.connection({"detector_password": [admin.PASSWORD_SET]}, settings)["state"] == "ok"


def test_the_connection_test_answers_in_the_status_row_s_words_too(detector):
    """The row and the test must never disagree, so the test carries the row -
    and the page renders the same words on load."""
    url, httpd = detector(password="hunter2")
    settings = Settings(detector_url=url, detector_password="hunter2")
    assert admin.connection({}, settings)["status"] == admin._state(True, "running", "unreachable")

    bad = admin.connection({"detector_password": ["wrong"]}, settings)
    assert bad["status"] == f'<span class="bad">running · {NEEDS_PASSWORD}</span>'
    # PrivateMode gates /health too, so a page that read nothing reaches the same
    # answer - with no version, since that is what /health would have carried.
    assert admin._detector(*admin.hostinfo.detector(url), False) == (
        f'<span class="bad">running · {NEEDS_PASSWORD}</span>'
    )

    httpd.shutdown()
    httpd.server_close()
    assert admin.connection({}, settings)["status"] == '<span class="bad">unreachable</span>'


def test_the_connection_test_catches_a_detector_that_only_gates_the_names(detector):
    """The failure behind #45: BirdNET-Go serves its detections to anyone and
    puts /settings/* behind authentication, so a frame with no credentials shows
    birds and nothing but scientific names. Testing the detections alone would
    call that connected."""
    url, _httpd = detector(password="hunter2", private=False)
    settings = Settings(detector_url=url)

    answer = admin.connection({}, settings)
    assert answer["state"] == "names"
    assert answer["text"] == "connected · needs a password"
    # The detector itself is running, and the row is about the detector.
    assert answer["status"] == '<span class="warn">running · needs a password</span>'

    assert admin.connection({"detector_password": ["hunter2"]}, settings)["state"] == "ok"


def test_the_credentials_ask_for_a_password_and_no_username(tmp_path, source):
    page = _page(tmp_path, source())
    assert 'name="detector_password"' in page
    assert "detector_username" not in page


def test_the_names_field_says_why_it_has_only_the_scientific_name(tmp_path, source, monkeypatch):
    monkeypatch.setattr(admin, "catalog_failure", lambda: "needs a password")
    page = _page(tmp_path, source())

    assert "No languages: needs a password." in page
    # The fix is on the other tab, so the note carries the reader there.
    assert '<a href="#detector" data-tab="system">' in page


def test_the_display_tab_names_the_password_rather_than_calling_it_unreachable(tmp_path, source):
    """PrivateMode empties the page as thoroughly as an outage does, and the
    Display tab is where that is noticed - so it must not send the reader off to
    check an address that is answering fine."""
    private = source(password="hunter2")
    languages.use(private)  # as the service wires it, so the names note agrees
    page = _page(tmp_path, private, detector_url=private.base_url)

    assert "detector unreachable" not in page
    assert f'<li class="problem">detector {NEEDS_PASSWORD}. See <a href="#detector"' in page
    assert f"<dd>detector {NEEDS_PASSWORD}</dd>" in page  # beside the row that says it too
