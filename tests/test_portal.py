"""The captive portal (#308): what a phone on the setup hotspot can pick and post."""

from __future__ import annotations

from fugleramme.web import portal


def test_a_listed_network():
    assert portal.parse({"ssid": ["Home"], "password": ["pw"]}) == ("Home", "pw", False)


def test_a_network_that_was_not_listed_is_hidden():
    form = {"ssid": [portal.OTHER], "other": [" Attic "], "password": [""]}
    assert portal.parse(form) == ("Attic", "", True)


def test_nothing_picked_or_a_name_too_long_for_an_ssid():
    assert portal.parse({}) is None
    assert portal.parse({"ssid": [portal.OTHER], "other": [""]}) is None
    assert portal.parse({"ssid": ["x" * 33]}) is None


def test_names_are_escaped():
    page = portal.choose("Fugleramme-A215", [("<b>Home</b>", True)], "Couldn't join <i>")
    assert "<b>Home</b>" not in page
    assert "&lt;b&gt;Home&lt;/b&gt;" in page
    assert "&lt;i&gt;" in page


def test_the_title_carries_its_own_face():
    assert portal.TITLE in portal.choose("Fugleramme-A215", [])
    page = portal.joining("Home", "http://crow.local:8080", font=b"ttf")
    assert "src:url(data:font/ttf;base64,dHRm)" in page
