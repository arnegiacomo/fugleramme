"""Species-name languages: what the admin may offer, and what a name reads as.
BirdNET-Go's API is faked - the invariants are the code mapping, the caching and
the fallbacks, none of which need a container."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime

import pytest

from fugleramme import languages
from fugleramme.api import ApiSource, Configured
from fugleramme.languages import NONE, SCIENTIFIC, Namer, catalog, dictionary, namer, ordered
from fugleramme.settings import Settings, SettingsStore
from fugleramme.web.admin import _language_select

NB = "nb"  # the fake's own dictionary code

# A slice of the real /api/v2/settings/locales: region variants, and "no" for
# the dictionary's "nb".
LOCALES = {
    "el": "Greek",
    "en-uk": "English (UK)",
    "en-us": "English (US)",
    "no": "Norwegian",
    "pt": "Portuguese",
    "pt-br": "Brazilian Portuguese",
    "sv": "Swedish",
}

NAMES = {"nb": {"Turdus merula": "svarttrost", "Acanthis hornemanni": "Arctic Redpoll"}}


def _api(monkeypatch, locales=LOCALES, names=NAMES, etag="v1", status=200):
    """Stand in for BirdNET-Go at the transport, so everything above it - the
    JSON, the ETag, the codes - is the frame's own. `locales=None` is a detector
    that cannot be reached; `status` is what it answers for the locale list.
    Returns the list of (path, If-None-Match) asked for."""
    fetched = []

    def request(path, method="GET", headers=None):
        tag = (headers or {}).get("If-None-Match", "")
        fetched.append((path, tag))
        body = b""
        if path.endswith("/settings/locales"):
            if locales is None:
                return None
            return status, {}, json.dumps(locales).encode()
        code = path.rsplit("/", 1)[1]
        if code not in names:
            return 404, {}, body
        if tag == etag:  # keyed lowercase, as api._open normalises what arrives
            return 304, {"etag": etag}, body
        return 200, {"etag": etag}, json.dumps(names[code]).encode()

    monkeypatch.setattr(languages, "_request", request)
    return fetched


def test_only_locales_with_a_dictionary_are_offered(monkeypatch, tmp_path):
    _api(monkeypatch, names={"nb": {}, "sv": {}})

    # Greek and Portuguese are listed by BirdNET-Go but have no dictionary.
    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific", "nb": "Norwegian", "sv": "Swedish"}


def test_dictionary_codes_are_resolved_from_the_locale_list(monkeypatch, tmp_path):
    _api(monkeypatch, names={"en": {}, "pt": {}})

    # "en-uk"/"en-us" both answer as "en", once, and unqualified; "pt-br" is
    # already covered by "pt".
    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific", "en": "English", "pt": "Portuguese"}


def test_the_frames_own_languages_are_offered_first(monkeypatch, tmp_path):
    _api(monkeypatch, names={"nb": {}, "sv": {}, "en": {}, "pt": {}})

    assert [code for code, _name in ordered(catalog(tmp_path))] == [
        SCIENTIFIC,
        "en",
        "nb",
        "pt",
        "sv",  # then alphabetical by display name
    ]


def test_unreachable_birdnet_go_leaves_only_the_scientific_name(monkeypatch, tmp_path):
    _api(monkeypatch, locales=None, names={})

    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific"}
    assert namer("nb", SCIENTIFIC, tmp_path).label("Turdus merula") == "Turdus merula"


def test_both_caches_survive_a_restart_with_birdnet_go_down(monkeypatch, tmp_path):
    _api(monkeypatch)
    assert "nb" in catalog(tmp_path)
    assert dictionary("nb", tmp_path)[0]["Turdus merula"] == "svarttrost"

    # A fresh process (empty in-memory caches) against a stopped container.
    monkeypatch.setattr(languages, "_catalog", None)
    monkeypatch.setattr(languages, "_dicts", {})
    _api(monkeypatch, locales=None, names={})

    assert "nb" in catalog(tmp_path)
    assert dictionary("nb", tmp_path)[0]["Turdus merula"] == "svarttrost"


def test_an_expired_dictionary_is_revalidated_not_refetched(monkeypatch, tmp_path):
    fetched = _api(monkeypatch)
    names, etag = dictionary("nb", tmp_path)
    languages._dicts["nb"] = (0.0, languages._station(), etag, names)  # deadline passed

    assert dictionary("nb", tmp_path) == (names, etag)
    # Asked again, but with the ETag - so a 304, not the whole dictionary.
    assert fetched[-1] == ("/species/dictionary/nb", "v1")


def test_a_fresh_dictionary_is_served_without_a_request(monkeypatch, tmp_path):
    fetched = _api(monkeypatch)
    dictionary("nb", tmp_path)
    before = len(fetched)

    dictionary("nb", tmp_path)
    assert len(fetched) == before


def test_the_second_language_follows_in_parentheses(monkeypatch, tmp_path):
    _api(monkeypatch)
    name_of = namer("nb", SCIENTIFIC, tmp_path)

    assert name_of.label("Turdus merula") == "Svarttrost\n(Turdus merula)"
    assert name_of.inline("Turdus merula") == "Svarttrost (Turdus merula)"


def test_a_common_name_is_capitalized_for_the_label(monkeypatch, tmp_path):
    _api(monkeypatch)
    # Lowercase in the dictionary, capitalized on the label.
    assert namer("nb", NONE, tmp_path).label("Turdus merula") == "Svarttrost"


def test_a_name_the_dictionary_lacks_falls_back_to_the_scientific_one(monkeypatch, tmp_path):
    _api(monkeypatch)
    name_of = namer("nb", NONE, tmp_path)

    assert name_of.label("Pica pica") == "Pica pica"
    # BirdNET-Go's own English fallback is passed through as it comes.
    assert name_of.label("Acanthis hornemanni") == "Arctic Redpoll"


def test_a_second_language_that_repeats_the_first_is_dropped(monkeypatch, tmp_path):
    _api(monkeypatch)

    assert namer("nb", "nb", tmp_path).label("Turdus merula") == "Svarttrost"
    # Same name for a different reason: nothing in nb, so both read scientific.
    assert namer("nb", SCIENTIFIC, tmp_path).label("Pica pica") == "Pica pica"


def test_no_language_is_a_bare_scientific_name(monkeypatch, tmp_path):
    _api(monkeypatch)
    name_of = namer(SCIENTIFIC, NONE, tmp_path)

    assert name_of.label("Turdus merula") == "Turdus merula"
    assert name_of.key == (SCIENTIFIC, NONE, ())  # nothing to load, nothing to invalidate


def test_the_render_key_changes_when_a_dictionary_does(monkeypatch, tmp_path):
    _api(monkeypatch)
    before = namer("nb", NONE, tmp_path).key

    monkeypatch.setattr(languages, "_dicts", {})
    _api(monkeypatch, names={"nb": {"Turdus merula": "ny svarttrost"}}, etag="v2")

    assert namer("nb", NONE, tmp_path).key != before


def test_a_language_birdnet_go_is_not_serving_stays_selectable():
    # A stopped container must not silently reset the frame's saved language.
    offered = [(SCIENTIFIC, "Scientific")]

    assert 'value="nb" selected>nb (unavailable)' in _language_select(
        "primary_language", offered, "nb"
    )
    assert 'value=""' not in _language_select("primary_language", offered, SCIENTIFIC)
    assert '<option value="" selected>None' in _language_select(
        "secondary_language", offered, NONE, optional=True
    )


def test_names_come_through_the_detectors_own_session(detector, tmp_path):
    """PrivateMode gates the locale list too, so a frame without the session gets
    no names at all - it has to ask through the same source it reads birds from."""
    url, _httpd = detector(password="hunter2")

    languages.use(ApiSource(url))
    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific"}

    languages._catalog = None
    languages.use(ApiSource(url, "birdnet", "hunter2"))
    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific", "nb": "Norwegian", "en": "English"}
    assert namer("nb", SCIENTIFIC, tmp_path).label("Turdus merula") == "Svarttrost\n(Turdus merula)"


def test_an_unreachable_detector_leaves_the_cached_dictionaries(detector, tmp_path):
    url, httpd = detector()
    languages.use(ApiSource(url))
    assert dictionary("nb", tmp_path)[0]["Turdus merula"] == "svarttrost"

    httpd.shutdown()
    httpd.server_close()
    languages._dicts = {}
    assert dictionary("nb", tmp_path)[0]["Turdus merula"] == "svarttrost"  # off disk


def test_namer_needs_no_dictionaries_at_all():
    # The collage's default: no API, no cache dir, no network.
    assert Namer(SCIENTIFIC, NONE, {}, ()).label("Pica pica") == "Pica pica"


# Local noon, so the date reads 16 August wherever the suite runs.
DATE = datetime(2026, 8, 16, 7, 42).astimezone()


@pytest.mark.parametrize(
    ("code", "date", "moment"),
    [
        ("nb", "16. august 2026", "16. august, 07:42"),
        ("en", "August 16, 2026", "August 16, 7:42 AM"),
        ("es", "16 de agosto de 2026", "16 de agosto, 7:42"),
        # More than the month's name: these put the year first, lv adds "gada",
        # and only some of them join the day and the time with a comma.
        ("hu", "2026. augusztus 16.", "augusztus 16. 7:42"),
        ("lv", "2026. gada 16. augusts", "16. augusts 07:42"),
    ],
)
def test_a_plates_date_reads_in_the_primary_language(code, date, moment):
    namer = Namer(code, NONE, {}, ())
    assert namer.date(DATE) == date
    assert namer.moment(DATE) == moment


@pytest.mark.parametrize("code", [SCIENTIFIC, NONE, "zz"])
def test_a_date_with_no_language_is_numeric(code):
    """A language the frame cannot spell must not take the plate down with it."""
    namer = Namer(code, NONE, {}, ())
    assert namer.date(DATE) == "16.08.2026"
    assert namer.moment(DATE) == "16.08 07:42"


def test_a_missing_babel_falls_back_rather_than_crashing(monkeypatch):
    """The self-update checks out before it syncs, so the new code can run for a
    moment without its new dependency."""
    monkeypatch.setattr(languages, "format_date", None)
    monkeypatch.setattr(languages, "format_skeleton", None)
    assert Namer("nb", NONE, {}, ()).date(DATE) == "16.08.2026"


def test_the_second_language_does_not_reach_the_date():
    assert Namer("nb", "en", {}, ()).date(DATE) == Namer("nb", NONE, {}, ()).date(DATE)


def test_no_date_carries_a_space_the_label_faces_cannot_draw():
    """CLDR really does ask for a narrow no-break space before AM/PM, but five of
    the seven faces have no glyph for one and draw a box: "7:42[]AM"."""
    for code in ("en", "fr", "nb"):
        namer = Namer(code, NONE, {}, ())
        assert not {*namer.date(DATE), *namer.moment(DATE)} & set("\u202f\u00a0")


def test_pointing_at_another_station_expires_the_names_rather_than_reusing_them(detector, tmp_path):
    """A dictionary and its ETag are one detector's answer. Cached in the process
    across a swap, the frame would label the new station's birds off the old."""
    first, one = detector()
    second, _two = detector()
    store = SettingsStore(tmp_path / "s.json", Settings(detector_url=first))
    languages.use(Configured(store))

    assert catalog(tmp_path)[NB] == "Norwegian"
    assert dictionary(NB, tmp_path)[0]["Turdus merula"] == "svarttrost"

    one.shutdown()  # only the first station is gone
    one.server_close()
    store.update(detector_url=second)

    assert languages._catalog is not None
    assert first in languages._catalog[1]  # still the old entry
    assert catalog(tmp_path)[NB] == "Norwegian"  # re-asked, of the second station
    assert second in languages._catalog[1]
    # Lazy, per lookup: the dictionary is only re-asked when a label needs it.
    assert first in languages._dicts[NB][1]
    assert dictionary(NB, tmp_path)[0]["Turdus merula"] == "svarttrost"
    assert second in languages._dicts[NB][1]


def test_a_swap_noticed_from_inside_a_name_lookup_does_not_wedge_the_frame(detector, tmp_path):
    """`catalog` holds the module lock across its probe, and the probe is what
    first asks the wrapper for the new source. Expiring the caches by station
    keeps that one-way: a callback the other way deadlocks both threads."""
    url, _httpd = detector()
    store = SettingsStore(tmp_path / "s.json", Settings(detector_url="http://127.0.0.1:1"))
    source = Configured(store)
    languages.use(source)

    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific"}  # nothing answers there
    store.update(detector_url=url)

    done = threading.Event()
    threading.Thread(target=lambda: (catalog(tmp_path), done.set()), daemon=True).start()
    assert done.wait(20), "the name lookup never returned"
    assert source.source.base_url == url  # and the loop's own call is not stuck behind it


def test_an_empty_probe_is_a_failure_not_a_language_list(monkeypatch, tmp_path):
    """The locale list answers and every dictionary HEAD does not. Cached as an
    answer, that one bad moment would hold the menu empty for a day and write
    itself over the good list on disk."""
    _api(monkeypatch)
    assert NB in catalog(tmp_path)
    cached = languages.cache_path(tmp_path, "languages").read_text()

    monkeypatch.setattr(languages, "_catalog", None)
    _api(monkeypatch, names={})

    assert NB in catalog(tmp_path)
    assert languages.cache_path(tmp_path, "languages").read_text() == cached
    assert languages._catalog[0] - time.monotonic() <= languages._RETRY_TTL


def test_nothing_to_offer_and_nothing_cached_says_why(monkeypatch, tmp_path):
    _api(monkeypatch, names={})

    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific"}
    assert languages.catalog_failure() == "detector serves none"
    assert not languages.cache_path(tmp_path, "languages").exists()


def test_a_gated_locale_list_says_so_rather_than_offering_one_language(monkeypatch, tmp_path):
    _api(monkeypatch, status=401)

    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific"}
    assert languages.catalog_failure() == "needs a password"


def test_a_list_off_the_disk_cache_is_not_a_failure(monkeypatch, tmp_path):
    """The menu works, whatever the probe behind it just did - so there is
    nothing for the admin to complain about."""
    _api(monkeypatch)
    assert NB in catalog(tmp_path)

    monkeypatch.setattr(languages, "_catalog", None)
    _api(monkeypatch, locales=None)

    assert NB in catalog(tmp_path)
    assert languages.catalog_failure() == ""


def test_credentials_the_locale_list_was_waiting_for_expire_the_empty_catalog(detector, tmp_path):
    """Keyed on the address alone, entering the password would leave the menu
    empty until the retry TTL ran out - which reads as the fix not working."""
    url, _httpd = detector(password="hunter2", private=False)
    store = SettingsStore(tmp_path / "s.json", Settings(detector_url=url))
    languages.use(Configured(store))

    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific"}
    assert languages.catalog_failure() == "needs a password"

    store.update(detector_password="hunter2")
    assert NB in catalog(tmp_path)
    assert languages.catalog_failure() == ""
