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
from fugleramme.settings import MARGIN_CEILING, Settings, SettingsStore
from fugleramme.source import NEEDS_PASSWORD
from fugleramme.status import Status
from fugleramme.web import STATIC_DIR, admin, server

PANEL = (1600, 1200)


def _page(tmp_path, source, names_dir=None, detected=True, **overrides) -> str:
    settings = Settings(**overrides)
    ctx = modes.context(
        source,
        tmp_path,
        Picks(tmp_path / "artwork.json"),
        settings,
        namer("sci", "", tmp_path),
        settings.web_size(PANEL if detected else None),
    )
    return admin.page(ctx, settings, Status(), PANEL, detected, names_dir or tmp_path)


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
    html = admin.species_html([("Pica pica", "gould", ""), ("Corvus cornix", None, "")], name_of)
    assert html.count("<li") == 2
    assert 'class="noart"' in html and "Corvus cornix" in html
    assert admin.species_html([], name_of) == '<li class="empty">none yet</li>'


def test_a_plate_with_a_citation_links_to_it(tmp_path):
    name_of = namer("sci", "", tmp_path)
    linked = admin.species_html([("Pica pica", "gould", "https://example.org/a")], name_of)
    assert '<a href="https://example.org/a" target="_blank" rel="noopener">Gould</a>' in linked
    assert "<a " not in admin.species_html([("Pica pica", "gould", "")], name_of)


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


def test_the_detector_password_says_what_it_is_for(tmp_path, source):
    """It is BirdNET-Go's Basic Authentication password, not the admin's own."""
    page = _page(tmp_path, source())
    assert "Password <small>(basic authentication)</small>" in page
    access = re.search(r'<form class="block access".*?</form>', page, re.DOTALL).group(0)
    assert "basic authentication" not in access  # the admin's own password is nothing of the sort


def test_a_stored_password_never_reaches_the_page(tmp_path, source):
    page = _page(tmp_path, source(), detector_password="hunter2")
    assert "hunter2" not in page
    assert admin.PASSWORD_SET in page


@pytest.mark.parametrize("field", ["detector_password", "admin_password"])
def test_the_placeholder_posts_back_as_leave_it_alone(field):
    kept = admin.form_changes({field: [admin.PASSWORD_SET]})
    assert field not in kept  # so merged() keeps the stored one

    typed = admin.form_changes({field: ["hunter3"]})
    assert typed[field] == "hunter3"

    cleared = admin.form_changes({field: [""]})
    assert cleared[field] == ""

    # A browser that let the placeholder be typed on the end of would otherwise
    # save the bullets, and for the admin's own password that is a lockout.
    appended = admin.form_changes({field: [admin.PASSWORD_SET + "x"]})
    assert field not in appended


def test_the_form_cannot_set_the_session_secret():
    """It signs the session cookie, so a form that could set it could forge one.
    Nothing in the page posts it; this is about what a hand-made post can reach."""
    changes = admin.form_changes({"session_secret": ["forged"], "admin_password": ["wren-house"]})
    assert "session_secret" not in changes
    assert changes["admin_password"] == "wren-house"


def test_the_sign_out_button_is_only_offered_where_there_is_a_session_to_end(tmp_path, source):
    """Either half of the lock alone leaves the admin open, and an open admin
    signs nobody in."""
    assert "Sign out" in _page(
        tmp_path, source(), require_sign_in=True, admin_password="wren-house"
    )
    assert "Sign out" not in _page(tmp_path, source())
    assert "Sign out" not in _page(tmp_path, source(), require_sign_in=True)
    assert "Sign out" not in _page(tmp_path, source(), admin_password="wren-house")


def test_the_access_note_says_where_the_switch_and_the_password_leave_things(tmp_path, source):
    """Two settings, four states, and only one of them is a shut door."""
    fresh = _page(tmp_path, source())
    assert "Anyone on the network can change the frame" in fresh  # nothing set, nothing to warn of

    half = _page(tmp_path, source(), require_sign_in=True)
    assert "No password saved" in half

    switched_off = _page(tmp_path, source(), admin_password="wren-house")
    assert "Sign-in is off, so anyone on the network can change the frame" in switched_off

    assert "Anyone can still view the kiosk" in _page(
        tmp_path, source(), require_sign_in=True, admin_password="wren-house"
    )


def test_the_access_field_says_whether_the_admin_has_a_password(tmp_path, source):
    assert 'name="admin_password" value=""' in _page(tmp_path, source())

    locked = _page(tmp_path, source(), admin_password="wren-house")
    assert "wren-house" not in locked
    assert f'name="admin_password" value="{admin.PASSWORD_SET}"' in locked


@pytest.mark.parametrize("field", ["require_sign_in", "behind_proxy"])
def test_the_access_switches_are_declared_so_unticking_one_is_a_change(tmp_path, source, field):
    """An unticked box posts nothing at all, so the form has to name its own
    boxes - undeclared, turning a switch off would read as leaving it alone."""
    page = _page(tmp_path, source(), **{field: True})
    form = re.search(r'<form class="block access".*?</form>', page, re.DOTALL).group(0)
    assert f'name="{field}" checked' in form
    declared = re.search(rf'name="{admin.CHECKBOXES}" value="([^"]*)"', form).group(1)
    assert field in declared.split()
    assert admin.form_changes({admin.CHECKBOXES: [declared]})[field] is False


def test_saving_the_form_untouched_leaves_the_password_standing(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    store.update(detector_url="http://pi:8090", detector_password="hunter2")
    form = {
        "detector_url": ["http://pi:8090"],
        "detector_username": [""],
        "detector_password": [admin.PASSWORD_SET],
    }
    assert store.update(**admin.form_changes(form)).detector_password == "hunter2"


def test_the_collage_fields_render_and_a_plate_mode_save_leaves_the_layout_alone(tmp_path, source):
    page = _page(tmp_path, source())
    assert f'name="margin" min="0" max="{MARGIN_CEILING}"' in page and 'name="layout"' in page

    # admin.js disables the collage-only fields outside the collage mode, so a
    # plate-mode post carries no layout - and a field that is absent keeps its value.
    store = SettingsStore(tmp_path / "s.json")
    store.update(layout="voids")
    assert store.update(**admin.form_changes({"mode": ["latest"]})).layout == "voids"


def _declared(html: str) -> list[str]:
    return re.findall(rf'name="{admin.CHECKBOXES}" value="([^"]*)"', html)


def test_the_resolution_names_the_size_the_kiosk_renders_locked_or_not(tmp_path, source):
    locked = _page(tmp_path, source(), web_resolution="4K", web_aspect="16:9")
    unlocked = _page(tmp_path, source(), web_resolution="4K", web_aspect="16:9", web_lock=False)
    assert '<option value="4K" selected>4K (2880×2160)</option>' in locked
    assert '<option value="4K" selected>4K (3840×2160)</option>' in unlocked
    assert '<option value="16:9" selected>16:9</option>' in unlocked


def test_the_kiosk_shape_switches_are_declared_so_unticking_one_is_a_change(tmp_path, source):
    page = _page(tmp_path, source(), web_lock=True, web_portrait=True)
    form = re.search(r'<form class="settings".*?</form>', page, re.DOTALL).group(0)
    assert 'name="web_lock" checked' in form and 'name="web_portrait" checked' in form
    declared = _declared(form)
    changes = admin.form_changes({admin.CHECKBOXES: declared})
    assert changes["web_lock"] is False and changes["web_portrait"] is False


def test_a_dimmed_portrait_box_keeps_its_saved_value(tmp_path):
    """Locked, admin.js disables the shape block, its declaration included, so
    the portrait box posts nothing and is not read as unticked."""
    store = SettingsStore(tmp_path / "s.json")
    store.update(web_lock=False, web_portrait=True)
    post = {admin.CHECKBOXES: ["show_names", "web_lock"], "show_names": ["on"]}
    saved = store.update(**admin.form_changes(post))
    assert saved.web_lock is False and saved.web_portrait is True


def test_with_no_panel_the_lock_is_off_and_undeclared(tmp_path, source):
    page = _page(tmp_path, source(), detected=False, web_lock=True)
    assert '<input type="checkbox" name="web_lock" disabled>' in page
    assert "no panel detected" in page
    assert not any("web_lock" in value.split() for value in _declared(page))
    assert _config(page)["panel"] is None  # the preview box takes the web view's shape
    assert _config(page)["webHeights"]["4K"] == 2160  # the Resolution labels follow the form


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


def test_the_page_carries_the_link_for_a_detector_on_another_machine(tmp_path, source, monkeypatch):
    # The page probes whatever detector it is pointed at, and a name nothing on
    # this network answers to is seconds of resolver timeout per run.
    monkeypatch.setattr(admin.hostinfo, "detector", lambda url: ("down", ""))
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
    assert '<a href="#detector" data-tab="detector">' in page


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
