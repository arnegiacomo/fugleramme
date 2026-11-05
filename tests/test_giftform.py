"""The gift form: what each field says, what ^P and ^W write, and that Esc leaves no trace."""

from __future__ import annotations

import time
from datetime import date
from types import SimpleNamespace

import pytest
from prompt_toolkit.application import create_app_session
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from fugleramme import gift, giftform
from fugleramme.config import REPO_ROOT
from fugleramme.names import drawable_keys
from fugleramme.render.page import Edges
from fugleramme.settings import Settings
from fugleramme.source import Unavailable

TODAY = date(2026, 11, 5)
COLUMBUS = gift.Place("Columbus, Ohio, United States", 39.96, -82.99)
SCORES = [("Turdus migratorius", 0.9), ("Cardinalis cardinalis", 0.8), ("Zenaida macroura", 0.7)]


@pytest.fixture(scope="module")
def names():
    return gift.Names.of(REPO_ROOT / "nonexistent", "sci")


@pytest.fixture
def frame(tmp_path, names):
    paths = gift.Paths(data=tmp_path, detector=tmp_path / "detector")
    return giftform.Frame(
        paths,
        Settings(admin_password="secret"),
        (800, 480),
        Edges.even(0.04),
        names,
        drawable_keys(REPO_ROOT / "assets" / "artwork", "classic"),
    )


def _checks(frame, scores=lambda *_where: SCORES):
    def find(text):
        return COLUMBUS if text == "columbus" else None

    return giftform.Checks(frame, TODAY, scores, find)


def test_each_field_gets_a_tick_or_a_reason(frame):
    checks = _checks(frame)
    checks.check("place", "columbus")
    checks.check("arrives", "2027-05-12")
    checks.check("note1", "Happy birthday!")
    checks.check("note2", "Happy birthday! " * 8)
    checks.check("favourites", "Steller's Jay, cardnal")
    checks.check("ssid", "x" * 40)
    checks.check("password", "short")
    assert checks.marks == {
        "place": (True, "Columbus, Ohio, United States"),
        "arrives": (True, ""),
        "note1": (True, ""),
        "note2": (False, checks.marks["note2"][1]),
        "favourites": (False, "no match - Northern Cardinal?"),
        "ssid": (False, "too long"),
        "password": (False, "WPA2 needs 8-63"),
    }
    assert checks.marks["note2"][1].startswith("too long by ")


def test_an_empty_optional_field_has_no_mark_and_a_required_one_does(frame):
    checks = _checks(frame)
    checks.check("note1", "")
    checks.check("place", "")
    assert checks.marks == {"place": (False, "no place called ")}


def test_a_place_the_search_cannot_reach_says_so(frame):
    def offline(_text):
        raise OSError("no network")

    checks = giftform.Checks(frame, TODAY, lambda *_w: SCORES, offline)
    checks.check("place", "columbus")
    assert checks.marks["place"] == (False, "the place search did not answer")


def test_a_wrap_needs_the_place_and_the_date(frame):
    checks = _checks(frame)
    assert checks.problems() == ["Place: not checked yet", "Arrives: not checked yet"]
    checks.check("place", "columbus")
    checks.check("arrives", "2026-11-04")
    assert checks.problems() == ["Arrives: in the past"]


def test_the_splash_leads_with_the_favourite_and_leaves_out_what_failed(frame):
    checks = _checks(frame)
    assert checks.splash(("", "", "")) is None
    checks.check("place", "columbus")
    checks.check("arrives", "2027-05-12")
    checks.check("favourites", "Steller's Jay")
    checks.check("note1", "Happy birthday!")
    checks.check("note2", "Happy birthday! " * 8)
    splash = checks.splash(("Happy birthday!", "Happy birthday! " * 8, ""))
    assert splash is not None
    assert splash.spotlight == "Cyanocitta stelleri"
    assert splash.birds[:2] == ("Cyanocitta stelleri", "Turdus migratorius")
    assert splash.notes == ("Happy birthday!",)
    assert splash.month == "May"


def test_a_detector_that_does_not_answer_still_leaves_the_favourites(frame):
    def down(*_where):
        raise Unavailable("stopped")

    checks = _checks(frame, down)
    checks.check("place", "columbus")
    checks.check("arrives", "2027-05-12")
    checks.check("favourites", "Steller's Jay")
    splash = checks.splash(("", "", ""))
    assert splash is not None and splash.birds == ("Cyanocitta stelleri",)


@pytest.fixture
def form(frame):
    nmcli = SimpleNamespace(allowed=lambda: True)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        form = giftform.Form(_checks(frame), nmcli, DRAWN.append)  # type: ignore[arg-type]
        DRAWN.clear()
        yield form


DRAWN: list[gift.Splash] = []


def _fill(form, **texts):
    for key, text in texts.items():
        form.areas[key].text = text
        form.checks.check(key, text)


def _drawn(form):
    while form.drawing:
        time.sleep(0.01)


def test_draw_puts_the_splash_on_the_panel(form):
    form._preview()
    assert "needs a place and a date" in form.status and not DRAWN
    _fill(form, place="columbus", arrives="2027-05-12")
    form._preview()
    _drawn(form)
    assert len(DRAWN) == 1 and DRAWN[0].month == "May"
    assert form.status == "Drawn."


def test_a_draw_that_fails_says_why(form):
    def broken(_splash):
        raise OSError("panel busy")

    form.draw = broken
    _fill(form, place="columbus", arrives="2027-05-12")
    form._preview()
    _drawn(form)
    assert form.status == "Could not draw it: panel busy"


def test_one_draw_at_a_time(form):
    form.drawing = True
    _fill(form, place="columbus", arrives="2027-05-12")
    form._preview()
    assert form.status == "Still drawing the last one." and not DRAWN


def test_wrap_asks_twice_and_typing_disarms_it(form):
    exits = []
    event = SimpleNamespace(app=SimpleNamespace(exit=lambda: exits.append(True)))
    form._wrap(event)
    assert form.status.startswith("Not yet.")
    _fill(form, place="columbus", arrives="2027-05-12", ssid="Their home", password="long enough")
    form._wrap(event)
    assert form.armed and not exits
    form.areas["note1"].text = "Hi"  # a change after the first ^W
    assert not form.armed
    form._wrap(event)
    form._wrap(event)
    assert exits and form.wrapping is not None
    assert (form.wrapping.place, form.wrapping.ssid) == (COLUMBUS, "Their home")
    assert form.wrapping.splash.month == "May"
    assert not form.wrapping.clear_admin


def test_typing_clears_a_fields_mark(form):
    _fill(form, place="columbus")
    form.areas["place"].text = "columbu"
    assert "place" not in form.checks.marks


def test_escape_quits(frame):
    nmcli = SimpleNamespace(allowed=lambda: True)
    with create_pipe_input() as pipe, create_app_session(input=pipe, output=DummyOutput()):
        form = giftform.Form(_checks(frame), nmcli, DRAWN.append)  # type: ignore[arg-type]
        pipe.send_text("columbus\x1b")
        form.app.run()
    assert form.areas["place"].text == "columbus" and form.wrapping is None
