"""Species-name languages: what the admin may offer, and what a name reads as.
BirdNET-Go's API is faked - the invariants are the code mapping, the caching and
the fallbacks, none of which need a container."""

from __future__ import annotations

from datetime import datetime

import pytest

from fugleramme import languages
from fugleramme.languages import NONE, SCIENTIFIC, Namer, catalog, dictionary, namer, ordered
from fugleramme.seed import seed_names
from fugleramme.web.admin import _language_select

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


@pytest.fixture(autouse=True)
def _clean_caches(monkeypatch):
    monkeypatch.setattr(languages, "_catalog", None)
    monkeypatch.setattr(languages, "_dicts", {})


def _api(monkeypatch, locales=LOCALES, names=NAMES, etag="v1"):
    """Stand in for BirdNET-Go. Returns the list of URLs fetched."""
    fetched = []

    def fetch(url, tag=""):
        fetched.append((url, tag))
        if url.endswith("/settings/locales"):
            return (locales, "") if locales is not None else (None, "")
        code = url.rsplit("/", 1)[1]
        if code not in names:
            return None, ""
        return (languages._UNCHANGED, tag) if tag == etag else (names[code], etag)

    monkeypatch.setattr(languages, "_fetch", fetch)
    monkeypatch.setattr(languages, "_has_dictionary", lambda code: code in names)
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
    languages._dicts["nb"] = (0.0, etag, names)  # deadline passed

    assert dictionary("nb", tmp_path) == (names, etag)
    assert fetched[-1] == (f"{languages._API}/species/dictionary/nb", "v1")


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


def test_the_seeded_fixture_reads_back_as_a_cache(monkeypatch, tmp_path):
    # seed.py writes these files by hand, so their shape is a contract.
    _api(monkeypatch, locales=None, names={})
    seed_names(tmp_path)

    assert catalog(tmp_path) == {SCIENTIFIC: "Scientific", "nb": "Norwegian", "en": "English"}
    assert namer("nb", SCIENTIFIC, tmp_path).label("Turdus merula") == "Svarttrost\n(Turdus merula)"


def test_seeding_does_not_clobber_a_fetched_dictionary(monkeypatch, tmp_path):
    _api(monkeypatch)
    dictionary("nb", tmp_path)

    assert seed_names(tmp_path) == ["languages", "en"]  # nb is already there, and better
    assert seed_names(tmp_path, force=True) == ["languages", "nb", "en"]


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
