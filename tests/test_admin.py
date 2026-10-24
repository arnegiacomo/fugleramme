"""Admin page invariants. The markup, the style and the script are files of
their own now, so only a render proves that the template's slots, the page's
asset links and the values admin.js reads still line up."""

from __future__ import annotations

import html
import json
import re

import pytest
from PIL import features

from fugleramme import fake, languages, modes
from fugleramme.birdweather import BirdWeatherSource
from fugleramme.config import BIRDNET_PORT, DEFAULT_DETECTOR_URL
from fugleramme.languages import namer
from fugleramme.settings import MARGIN_CEILING, Settings, SettingsStore, merged
from fugleramme.source import BIRDNET_GO, BIRDWEATHER, NEEDS_PASSWORD
from fugleramme.status import Status
from fugleramme.web import STATIC_DIR, admin, server

PANEL = (1600, 1200)


def _page(
    tmp_path, source, names_dir=None, detected=True, refused="", stations="", **overrides
) -> str:
    settings = Settings(**overrides)
    ctx = modes.context(
        source,
        tmp_path,
        settings,
        namer("sci", "", tmp_path),
        settings.web_size(PANEL if detected else None),
    )
    return admin.page(
        ctx, settings, Status(), PANEL, detected, names_dir or tmp_path, refused, stations
    )


def _config(page: str) -> dict:
    return json.loads(
        re.search(r'<script id="config"[^>]*>(.*?)</script>', page, re.DOTALL).group(1)
    )


def test_the_page_renders_before_anything_has_written_to_the_data_dir(tmp_path, source):
    # A fresh checkout has no detector/data: nothing has saved settings or
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


def test_the_detector_tab_counts_every_bird_heard_without_art(tmp_path, source):
    heard = source(count=40, seed=0).species_since(0)
    page = _page(tmp_path, source(count=40, seed=0))  # no style folder: nothing has art
    assert f'<dd class="missing">{len(heard)} birds <button' in page
    assert page.count(" detection", page.index('data-copy="')) >= len(heard)


def test_every_asset_the_page_links_is_one_the_server_serves(tmp_path, source):
    linked = set(re.findall(r'(?:href|src)="(/[^"?]*)', _page(tmp_path, source())))
    assert linked == {"/", "/admin.css", "/admin.js", "/favicon.png"}
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


def test_a_bird_without_art_is_a_line_the_issue_form_takes():
    text = admin.missing_text([("Sturnus unicolor", 1204), ("Pica pica", 1)])
    assert text.splitlines() == [
        "Sturnus unicolor (Spotless Starling) - 1204 detections",
        "Pica pica (Eurasian Magpie) - 1 detection",
    ]
    assert admin.missing_text([("Nonexistus birdus", 3)]) == "Nonexistus birdus - 3 detections"


def test_the_issue_carries_the_list_while_github_takes_it():
    short = admin.missing_row([("Sturnus unicolor", 1204)])
    assert short.startswith("1 bird <button") and "species=Sturnus+unicolor" in short

    long = admin.missing_row([(f"Sturnus unicolor{i}", 1204) for i in range(300)])
    assert "species=" not in long
    assert long.count(" detections") == 300  # Copy always has the whole list


def test_a_station_with_art_for_every_bird_says_so():
    assert admin.missing_row([]) == "none"


def test_a_plate_with_a_citation_links_to_it(tmp_path):
    name_of = namer("sci", "", tmp_path)
    linked = admin.species_html([("Pica pica", "gould", "https://example.org/a")], name_of)
    assert '<a href="https://example.org/a" target="_blank" rel="noopener">Gould</a>' in linked
    assert "href" not in admin.species_html([("Pica pica", "gould", "")], name_of)


def test_every_species_name_carries_its_scientific_name_for_the_birdnet_link(tmp_path):
    name_of = namer("sci", "", tmp_path)
    html = admin.species_html([("Pica pica", "gould", ""), ("Corvus cornix", None, "")], name_of)
    assert html.count('data-species="') == 2
    assert 'data-species="Corvus cornix"' in html


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
    store.update(layout="voids", spotlight=True)
    saved = store.update(**admin.form_changes({"mode": ["latest"]}))
    assert saved.layout == "voids" and saved.spotlight


def test_the_spotlight_box_saves_both_ways(tmp_path, source):
    page = _page(tmp_path, source())
    assert 'name="spotlight"' in page and "spotlight" in _declared(page)
    store = SettingsStore(tmp_path / "s.json")
    on = {admin.CHECKBOXES: ["spotlight"], "spotlight": ["on"]}
    assert store.update(**admin.form_changes(on)).spotlight
    assert not store.update(**admin.form_changes({admin.CHECKBOXES: ["spotlight"]})).spotlight


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


def test_with_no_panel_the_lock_is_disabled_declaration_and_all(tmp_path, source):
    """admin.js enables it once the external panel is ticked; until then a save
    leaves the stored lock alone."""
    page = _page(tmp_path, source(), detected=False, web_lock=True)
    assert '<input type="checkbox" name="web_lock" checked disabled>' in page
    assert f'name="{admin.CHECKBOXES}" value="web_lock" disabled>' in page
    assert f'aria-label="{html.escape(admin.LOCK_OFF, quote=True)}"' in page
    assert "no panel detected" not in page
    assert _config(page)["detected"] is False  # the preview box takes the web view's shape
    assert _config(page)["webHeights"]["4K"] == 2160  # the Resolution labels follow the form


def test_the_panel_has_a_title_over_its_outputs(tmp_path, source):
    outputs = re.search(r'<div class="field" id="outputs">.*?</div>', _page(tmp_path, source()))
    assert outputs.group(0).startswith('<div class="field" id="outputs"><span>Outputs</span>')
    assert 'name="external_panel"' in outputs.group(0)


def test_every_tab_has_the_pane_admin_js_shows(tmp_path, source):
    page = _page(tmp_path, source())
    for tab in re.findall(r'data-tab="([^"]+)"', page):
        assert f'id="tab-{tab}"' in page


def test_the_margin_offers_each_edge_while_there_is_a_panel(tmp_path, source):
    unlocked = {"margin": 6, "margin_lock": False, "margin_top": 12}
    page = _page(tmp_path, source(), **unlocked)
    assert "margin_lock" in _declared(page) and 'name="margin_lock">' in page
    assert 'name="margin_top" min="0" max="25" step="1" value="12"' in page
    assert 'name="margin_left" min="0" max="25" step="1" value="6"' in page
    assert '<div id="margin-edges">' in page
    # Rendered all the same, for admin.js to offer once the external panel is ticked.
    bare = _page(tmp_path, source(), detected=False, **unlocked)
    assert (
        '<div id="margin-uniform" class="off">' in bare and '<div id="margin-edges" hidden>' in bare
    )
    assert 'name="margin_lock" disabled>' in bare
    assert 'name="margin" min="0"' in bare


def test_unticking_the_margin_lock_is_a_change(tmp_path):
    store = SettingsStore(tmp_path / "s.json")
    post = {admin.CHECKBOXES: ["show_names margin_lock"], "margin_top": ["10"]}
    saved = store.update(**admin.form_changes(post))
    assert not saved.margin_lock and saved.glass_margins()[0] == 10


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


def test_a_public_address_is_linked_as_configured_whatever_the_detector_address():
    public = "https://varquez.cybai.re/birdnet"
    assert admin.birdnet_link("http://127.0.0.1:8090", BIRDNET_GO, public) == (public, None)


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


@pytest.mark.parametrize(
    ("chosen", "raqm", "noted"),
    [
        ({"primary_language": "station"}, False, True),
        ({"primary_language": "station"}, True, False),
        ({"primary_language": "ja"}, False, False),
        # Not English, which Naskh has too.
        ({"primary_language": "en", "secondary_language": "ar"}, False, True),
        ({}, False, False),  # not while the station's names are unused
    ],
)
def test_the_names_field_says_when_this_pi_cannot_draw_a_chosen_language(
    tmp_path, source, monkeypatch, chosen, raqm, noted
):
    """libfribidi0 is an apt package, which an update never installs."""
    check = features.check
    monkeypatch.setattr(features, "check", lambda name: raqm if name == "raqm" else check(name))
    monkeypatch.setattr(admin, "station_locale", lambda: "ar")
    note = (
        "This Pi can't draw Arabic yet. "
        'Run <code class="cmd">sudo apt install libfribidi0</code> and reboot.'
    )
    assert (note in _page(tmp_path, source(), **chosen)) is noted


@pytest.mark.parametrize(
    ("overrides", "note"),
    [
        (
            {"primary_language": "station"},
            "Gentium Book Plus doesn't support Chinese - using Noto Sans CJK SC instead.",
        ),
        (
            {"primary_language": "sci", "secondary_language": "station"},
            "Gentium Book Plus doesn't support Chinese - using Noto Sans CJK SC instead.",
        ),
        (
            {"primary_language": "el", "label_font": "baskerville"},
            "Libre Baskerville doesn't support Greek - using Gentium Book Plus instead.",
        ),
        (
            {"primary_language": "el", "label_font": "bitter"},
            "Bitter doesn't support Greek - using Gentium Book Plus instead.",
        ),
        ({"primary_language": "el", "label_font": "gentium"}, ""),  # Gentium has Greek
        ({"primary_language": "nb", "label_font": "baskerville"}, ""),
        ({"primary_language": "en", "secondary_language": "sci"}, ""),
    ],
)
def test_the_typeface_warns_of_a_language_it_leaves_to_a_fallback(
    tmp_path, source, monkeypatch, overrides, note
):
    monkeypatch.setattr(admin, "station_locale", lambda: "zh")
    page = _page(tmp_path, source(), **overrides)
    warning = re.search(r'<span class="hint caution" id="face-note"[^>]*>', page).group()
    assert (" hidden" in warning) is not bool(note)
    assert f'aria-label="{html.escape(note)}"' in warning


def test_the_typeface_warning_is_a_triangle_not_the_info_badge(tmp_path, source):
    page = _page(tmp_path, source(), primary_language="zh")
    warning = re.search(r'<span class="hint caution" id="face-note".*?</span>', page).group()
    assert "<svg" in warning  # the info badge is an empty hint
    assert "⚠" not in page  # a colour emoji on some systems


# -- a BirdWeather station ----------------------------------------------------


@pytest.fixture
def station(detector):
    """The fake station's page and a source over it."""

    def start(**kwargs) -> tuple[str, BirdWeatherSource]:
        url, _httpd = detector(birdweather=True, **kwargs)
        page = f"{url}/stations/{fake.STATION_ID}"
        return page, BirdWeatherSource(page)

    return start


@pytest.mark.parametrize(
    ("typed", "saved"),
    [
        ("31086", "https://app.birdweather.com/stations/31086"),
        (" 31086 ", "https://app.birdweather.com/stations/31086"),
        (
            "https://app.birdweather.com/stations/31086/",
            "https://app.birdweather.com/stations/31086",
        ),
        (
            "https://app.birdweather.com/stations/31086?period=day#top",
            "https://app.birdweather.com/stations/31086",
        ),
    ],
)
def test_a_station_is_saved_as_its_page_however_it_is_typed(typed, saved):
    changes = admin.form_changes({"detector_kind": [BIRDWEATHER], "detector_station": [typed]})
    assert admin.refused(changes) == ""
    assert merged(Settings(), **changes).detector_station == saved


@pytest.mark.parametrize(
    ("field", "typed", "kind"),
    [
        ("detector_url", "https://app.birdweather.com/stations/31086", BIRDNET_GO),
        ("detector_url", "https://app.birdweather.com", BIRDNET_GO),
        ("detector_url", "app.birdweather.com/stations/31086", BIRDNET_GO),
        ("detector_url", "31086", BIRDNET_GO),  # an ID, not http://31086
        ("detector_station", "http://127.0.0.1:8090", BIRDWEATHER),
        ("detector_station", "https://app.birdweather.com", BIRDWEATHER),
        ("detector_station", "not an address", BIRDWEATHER),
    ],
)
def test_an_address_its_type_s_field_cannot_hold_is_refused(field, typed, kind):
    assert admin.refused(admin.form_changes({field: [typed]})) == kind


def test_the_station_rows_are_saved_as_one_list():
    """Empty rows are dropped and a station typed twice is read once."""
    rows = ["31086", "", " https://app.birdweather.com/stations/15982/ ", "31086"]
    changes = admin.form_changes({"detector_kind": [BIRDWEATHER], "detector_station": rows})
    assert admin.refused(changes) == ""
    assert merged(Settings(), **changes).detector_station == (
        "https://app.birdweather.com/stations/31086, https://app.birdweather.com/stations/15982"
    )


@pytest.mark.parametrize(
    ("rows", "short"),
    [
        (["31086", "nest box"], "not a station"),
        ([str(n) for n in range(1, 7)], "too many stations"),
        (["31086", "http://127.0.0.1:8090/stations/1"], "stations on two sites"),
    ],
)
def test_stations_the_frame_cannot_read_as_one_are_refused(rows, short):
    changes = admin.form_changes({"detector_station": rows})
    assert admin.refused(changes) == BIRDWEATHER
    assert admin.refusal(BIRDWEATHER, str(changes["detector_station"]))[0] == short


def test_a_save_without_the_detector_or_with_no_station_is_not_refused():
    assert admin.refused(admin.form_changes({"mode": ["latest"]})) == ""
    assert admin.refused(admin.form_changes({"detector_station": [""]})) == ""


def test_switching_type_keeps_each_type_s_own_address(tmp_path):
    """The other type's fields are disabled, so a save posts nothing for them."""
    store = SettingsStore(tmp_path / "s.json")
    store.update(detector_url="http://pi:8090", detector_password="hunter2")
    page = "https://app.birdweather.com/stations/31086"

    weather = store.update(
        **admin.form_changes({"detector_kind": [BIRDWEATHER], "detector_station": ["31086"]})
    )
    assert weather.detector_address == page
    assert (weather.detector_url, weather.detector_password) == ("http://pi:8090", "hunter2")

    back = store.update(
        **admin.form_changes(
            {
                "detector_kind": [BIRDNET_GO],
                "detector_url": ["http://pi:8090"],
                "detector_password": [admin.PASSWORD_SET],
            }
        )
    )
    assert back.detector_address == "http://pi:8090"
    assert (back.detector_station, back.detector_password) == (page, "hunter2")


def test_the_detector_tab_names_the_station_and_what_it_last_heard(tmp_path, station):
    url, source = station()
    page = _page(tmp_path, source, detector_kind=BIRDWEATHER, detector_station=url)

    assert "$" not in page
    row = re.search(r'<span id="detector-state">(.*?)</span></dd>', page).group(1)
    ((*named, heard),) = _lines(row)
    assert named == [LOGO, fake.STATION_NAME, "·", f"#{fake.STATION_ID}", "·"]
    assert heard.startswith("latest detection ")
    assert f'<a href="{url}">#{fake.STATION_ID}</a>' in row
    assert "<h2>BirdWeather</h2>" in page
    assert 'title="detection &amp; stats">BirdWeather</a>' in page  # the link carries no logo
    assert "<dt>Detector(s)</dt><dd><span id=" in page  # each station's line has its own
    blob = _config(page)
    assert (blob["birdnetUrl"], blob["birdnetPort"], blob["kind"]) == (url, None, BIRDWEATHER)


def _detector_form(page: str) -> str:
    return re.search(r'<form class="block detector".*?</form>', page, re.DOTALL).group(0)


def test_a_station_shows_its_own_field_and_keeps_birdnet_go_s(tmp_path, station):
    url, source = station()
    form = _detector_form(_page(tmp_path, source, detector_kind=BIRDWEATHER, detector_station=url))

    assert '<input type="radio" name="detector_kind" value="birdweather" checked>' in form
    assert f"{admin._logo(BIRDWEATHER)}BirdWeather station(s)</label>" in form
    assert '<div class="field stations" data-kind="birdweather" data-most="5">' in form
    assert "<span>Stations <small>(ID or address)</small></span>" in form
    assert f'<input type="text" name="detector_station" value="{url}">' in form  # an ID is no URL
    # Hidden and disabled, so a save posts nothing and the stored ones stand.
    assert '<label data-kind="birdnet-go" hidden><span>Address' in form
    assert (
        f'<input disabled inputmode="url" type="text" name="detector_url"'
        f' value="{DEFAULT_DETECTOR_URL}">'
    ) in form
    assert '<label data-kind="birdnet-go" hidden><span>Password' in form
    assert '<input disabled type="password" name="detector_password"' in form


def test_birdnet_go_s_detector_form_asks_for_a_url_and_a_password(tmp_path, source):
    page = _page(tmp_path, source())
    form = _detector_form(page)

    assert '<input type="radio" name="detector_kind" value="birdnet-go" checked>' in form
    assert f"{admin._logo(BIRDNET_GO)}BirdNET-Go</label>" in form
    assert '<label data-kind="birdnet-go"><span>Address' in form
    # Text, or the browser would refuse an address typed without http://.
    assert '<input inputmode="url" type="text" name="detector_url"' in form
    assert '<label data-kind="birdnet-go"><span>Password' in form
    assert '<div class="field stations" data-kind="birdweather" data-most="5" hidden>' in form
    assert '<input type="text" name="detector_station" value="" disabled>' in form
    assert "<h2>BirdNET-Go</h2>" in page
    assert 'class="note bad"' not in form


def test_birdweather_s_page_is_linked_as_it_is_even_on_loopback():
    """A station's page is on BirdWeather, not on the Pi's own port."""
    url = "https://app.birdweather.com/stations/31086"
    assert admin.birdnet_link(url, BIRDWEATHER) == (url, None)
    assert admin.birdnet_link("", BIRDWEATHER) == ("https://app.birdweather.com", None)


def test_birdweather_with_no_station_saved_says_so_without_asking(tmp_path, monkeypatch):
    monkeypatch.setattr(admin.hostinfo, "stations", lambda url: pytest.fail("asked BirdWeather"))
    page = _page(tmp_path, BirdWeatherSource(""), detector_kind=BIRDWEATHER)

    assert "$" not in page
    assert '<span id="detector-state"><span class="bad">no station saved</span></span>' in page
    assert "<dd>no station saved</dd>" in page  # the last detection, beside the row


def test_a_refused_save_says_it_was_not_saved(tmp_path, source):
    assert "Not saved." not in _page(tmp_path, source())
    page = _page(tmp_path, source(), refused=BIRDNET_GO)
    assert "Not saved. That is a BirdWeather station. Choose BirdWeather" in page
    page = _page(tmp_path, source(), refused=BIRDWEATHER, stations="31086, nest box")
    assert "Not saved. &quot;nest box&quot; is not a BirdWeather station." in page
    assert "https://app.birdweather.com/stations/&lt;ID&gt;" in page
    page = _page(tmp_path, source(), refused=BIRDWEATHER, stations="1, 2, 3, 4, 5, 6")
    assert "Not saved. The frame reads at most 5 stations." in page


def test_a_refused_save_comes_back_on_the_type_it_was_refused_for(tmp_path, source):
    """The note sits under the field to fix, which must be the one shown."""
    form = _detector_form(_page(tmp_path, source(), refused=BIRDWEATHER, stations="nest box"))
    assert '<input type="radio" name="detector_kind" value="birdweather" checked>' in form
    assert re.search(r'</dialog></div><p class="note bad">', form)


def test_a_missing_station_is_not_called_unreachable(tmp_path, station):
    url, _source = station()
    gone = url.replace(f"/stations/{fake.STATION_ID}", "/stations/404")
    page = _page(
        tmp_path, BirdWeatherSource(gone), detector_kind=BIRDWEATHER, detector_station=gone
    )

    row = re.search(r'<span id="detector-state">(.*?)</span></dd>', page).group(1)
    assert _lines(row) == [[LOGO, "", "", "#404", "·", "no such station"]]
    assert '<li class="problem">no such station. See' in page
    assert "<dd>no such station</dd>" in page  # the last detection, beside the row


def test_the_connection_test_tells_a_station_s_answers_apart(station):
    url, _source = station()
    settings = Settings(detector_kind=BIRDWEATHER, detector_station=url)

    ok = admin.connection({}, settings)
    assert (ok["state"], ok["text"]) == ("ok", f"connected · {fake.STATION_NAME}")
    assert _lines(ok["status"])[0][:4] == [LOGO, fake.STATION_NAME, "·", f"#{fake.STATION_ID}"]

    other = url.replace(f"/stations/{fake.STATION_ID}", "/stations/404")
    missing = admin.connection({"detector_station": [other]}, settings)
    assert missing["state"] == "missing"
    assert missing["text"] == "BirdWeather has no station 404"
    assert _lines(missing["status"]) == [[LOGO, "", "", "#404", "·", "no such station"]]

    wrong = admin.connection({"detector_kind": [BIRDNET_GO], "detector_url": [url]}, settings)
    assert wrong["state"] == "refused"
    assert wrong["text"].startswith("That is a BirdWeather station.")
    assert wrong["status"] == '<span class="bad">a BirdWeather station</span>'

    unset = admin.connection({"detector_station": [""]}, settings)
    assert (unset["state"], unset["text"]) == ("unset", "no station entered")


def test_the_connection_test_takes_a_bare_station_id(monkeypatch):
    """The test reads the form as Save would, ID and all."""
    asked = []
    monkeypatch.setattr(admin, "probe", lambda *args: asked.append(args) or ("unreachable", ""))
    admin.connection({"detector_kind": [BIRDWEATHER], "detector_station": ["31086"]}, Settings())
    assert asked == [("https://app.birdweather.com/stations/31086", "", "", BIRDWEATHER)]


def test_the_connection_test_says_when_a_station_is_unreachable(station):
    url, _source = station(down=True)
    answer = admin.connection({}, Settings(detector_kind=BIRDWEATHER, detector_station=url))
    assert answer["state"] == "unreachable"
    assert answer["status"] == '<span class="bad">unreachable</span>'


def test_the_station_row_asks_birdweather_at_most_once_a_minute(detector):
    """Every admin load asks for the row, and BirdWeather is someone else's service."""
    url, httpd = detector(birdweather=True)
    page = f"{url}/stations/{fake.STATION_ID}"
    state, about = admin.hostinfo.stations(page)
    assert (state, about[fake.STATION_ID]["name"]) == ("ok", fake.STATION_NAME)

    httpd.shutdown()
    httpd.server_close()
    assert admin.hostinfo.stations(page) == (state, about)  # held, not asked again
    assert admin.hostinfo.stations(f"{url}/stations/2")[0] == "down"  # another list is


def test_the_station_row_tells_a_missing_station_from_a_dead_one(detector):
    url, _httpd = detector(birdweather=True)
    assert admin.hostinfo.stations(f"{url}/stations/404") == ("ok", {"404": None})
    assert admin.hostinfo.stations(url) == ("missing", {})  # names no station at all
    assert admin.hostinfo.stations("http://127.0.0.1:1/stations/1") == ("down", {})


# -- several BirdWeather stations ---------------------------------------------


LOGO = "[logo]"


def _lines(row: str) -> list[list[str]]:
    """A Detector row of stations as text: logo, name, ·, #ID, · and latest
    detection a line. No cell holds a span of its own."""
    cells = re.findall(r"<span[^>]*>(.*?)</span>", row.removeprefix('<span class="stations">'))
    text = [LOGO if cell.startswith("<img") else re.sub(r"<[^>]+>", "", cell) for cell in cells]
    return [text[i : i + 6] for i in range(0, len(text), 6)]


def _two(url: str, other: str = fake.OTHER_STATION_ID) -> str:
    return f"{url}/stations/{fake.STATION_ID}, {url}/stations/{other}"


def test_each_station_has_a_row_and_an_x(tmp_path, detector):
    url, _httpd = detector(birdweather=True)
    stations = _two(url)
    form = _detector_form(
        _page(
            tmp_path,
            BirdWeatherSource(stations),
            detector_kind=BIRDWEATHER,
            detector_station=stations,
        )
    )
    for page in stations.split(", "):
        assert (
            f'<div class="station"><input type="text" name="detector_station" value="{page}">'
            '<button type="button" class="remove" aria-label="Remove station">×</button></div>'
        ) in form
    assert form.count('class="station"') == 2


def test_the_detector_row_has_a_line_per_station(tmp_path, detector):
    url, _httpd = detector(birdweather=True)
    stations = _two(url, "404")
    page = _page(
        tmp_path, BirdWeatherSource(stations), detector_kind=BIRDWEATHER, detector_station=stations
    )
    row = re.search(r'<span id="detector-state">(.*?)</span></dd>', page).group(1)
    ok, missing = _lines(row)
    assert ok[:4] == [LOGO, fake.STATION_NAME, "·", f"#{fake.STATION_ID}"]
    assert missing == [LOGO, "", "", "#404", "·", "no such station"]
    assert "no such station. See" not in page  # the other station still makes the page


def test_several_stations_are_a_list_under_the_nav_link(tmp_path, detector):
    url, _httpd = detector(birdweather=True)
    stations = _two(url)
    page = _page(
        tmp_path, BirdWeatherSource(stations), detector_kind=BIRDWEATHER, detector_station=stations
    )
    assert 'id="birdnet"' not in page
    assert 'popovertarget="stations"' in page
    links = re.search(r'<div id="stations" popover>(.*?)</div>', page).group(1)
    assert links == (
        f'<a href="{url}/stations/{fake.STATION_ID}">{fake.STATION_NAME}</a>'
        f'<a href="{url}/stations/{fake.OTHER_STATION_ID}">'
        f"{fake.STATIONS[fake.OTHER_STATION_ID][0]}</a>"
    )


def test_the_connection_test_names_every_station(detector):
    url, _httpd = detector(birdweather=True)
    settings = Settings(detector_kind=BIRDWEATHER)
    other = fake.STATIONS[fake.OTHER_STATION_ID][0]

    both = admin.connection({"detector_station": _two(url).split(", ")}, settings)
    assert (both["state"], both["text"]) == ("ok", f"connected · {fake.STATION_NAME}, {other}")
    assert [line[1] for line in _lines(both["status"])] == [fake.STATION_NAME, other]

    one = admin.connection({"detector_station": _two(url, "404").split(", ")}, settings)
    assert (one["state"], one["text"]) == (
        "partial",
        f"connected · {fake.STATION_NAME}, 404: no such station",
    )
    assert _lines(one["status"])[1] == [LOGO, "", "", "#404", "·", "no such station"]


def test_a_station_on_birdweather_is_shown_by_its_id(tmp_path, source):
    """Its page is too long for the input, and the ID is what tells two apart."""
    stations = "https://app.birdweather.com/stations/31086, http://127.0.0.1:8090/stations/1"
    form = _detector_form(_page(tmp_path, source(), detector_station=stations))
    assert 'name="detector_station" value="31086"' in form
    assert 'name="detector_station" value="http://127.0.0.1:8090/stations/1"' in form
