"""The gift questions: each asked again until it is right, the summary, the confirm."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from functools import partial

import pytest
from prompt_toolkit.document import Document

from fugleramme import gift, giftform
from fugleramme.config import REPO_ROOT
from fugleramme.names import drawable_keys
from fugleramme.render.page import Edges
from fugleramme.settings import Settings

TODAY = date(2026, 11, 5)
COLUMBUS = gift.Place("Columbus, Ohio, United States", 39.96, -82.99)
SCORES = [("Turdus migratorius", 0.9), ("Cardinalis cardinalis", 0.8), ("Zenaida macroura", 0.7)]
HEARD = gift.Heard(2847, 61, date(2026, 9, 14), 412, 1_300_000_000)
ENTER = None  # takes what is offered


class Script:
    """The giver, as a list of answers; out of answers is Ctrl-D."""

    def __init__(self, *answers: str | None):
        self.answers = list(answers)
        self.said: list[tuple[str, str]] = []
        self.offered: list[str] = []

    def ask(self, default="", label="> ", completer=None):
        self.offered.append(default)
        if not self.answers:
            raise EOFError
        answer = self.answers.pop(0)
        return default if answer is ENTER else answer

    def say(self, text="", style=""):
        self.said.append((text, style))

    def text(self) -> str:
        """All it said, unwrapped."""
        return " ".join(" ".join(text for text, _style in self.said).split())


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


def _questions(frame, io, scores=lambda *_where: SCORES):
    def find(text):
        return COLUMBUS if text == "columbus" else None

    return giftform.Questions(io, frame, TODAY, scores, find)


def test_each_answer_is_asked_again_until_it_is_right(frame):
    io = Script(
        "nowhere",  # no such place
        "columbus",
        "24/12/2026",  # not YYYY-MM-DD
        "2026-12-24",
        "Stellers jay, cardnal",  # a typo: offered back as Northern Cardinal
        ENTER,
        "Happy birthday! " * 12,  # too long for the panel
        "Happy birthday!",
        "",
        "Their home",
        "short",  # not a WPA2 password
        "their-password",
        ENTER,  # clear the admin password: yes
    )
    q = _questions(frame, io)
    g = giftform.Gift()
    for _label, step in q.steps():
        g = step(g)

    assert g == giftform.Gift(
        COLUMBUS,
        date(2026, 12, 24),
        ("Cyanocitta stelleri", "Cardinalis cardinalis"),
        ("Happy birthday!",),
        "Their home",
        "their-password",
        clear_admin=True,
    )
    assert "Steller's Jay, Northern Cardinal" in io.offered
    marks = [text for text, style in io.said if style == "bad" and "✗" in text]
    assert len(marks) == 5
    for mark, start in zip(
        marks,
        ["No place called nowhere", "Use YYYY-MM-DD", "No bird called cardnal", "", "A Wi-Fi"],
        strict=True,
    ):
        assert mark.startswith(f"  ✗ {start}")
    assert "characters too long" in marks[3]


def test_a_place_search_that_does_not_answer_names_the_way_out(frame):
    def offline(_text):
        raise OSError("down")

    io = Script("columbus", "39.96, -82.99")
    find = partial(gift.find_place, fetch=offline)
    q = giftform.Questions(io, frame, TODAY, lambda *_w: SCORES, find)
    assert q.place(giftform.Gift()).place == gift.Place("39.96, -82.99", 39.96, -82.99)
    assert "latitude, longitude from a maps app" in io.text()


def test_the_admin_question_is_asked_only_where_there_is_a_password(frame):
    bare = giftform.Questions(Script(), replace(frame, settings=Settings()), TODAY, lambda *_w: [])
    assert [label for label, _s in bare.steps()][-1] == "Wi-Fi"


GIFT = giftform.Gift(COLUMBUS, date(2026, 12, 24), ("Cyanocitta stelleri",), ("Happy birthday!",))


def test_the_splash_leads_with_the_favourite_then_the_likeliest_there(frame):
    shown = _questions(frame, Script()).splash(GIFT)
    assert shown.month == "December" and shown.spotlight == "Cyanocitta stelleri"
    assert shown.birds[:2] == ("Cyanocitta stelleri", "Turdus migratorius")


def test_the_summary_draws_once_and_redraws_after_a_change(frame):
    drawn: list[gift.Splash] = []
    io = Script("4", "Merry Christmas!", "", "w", ENTER, "q")  # change the note, then back out
    q = _questions(frame, io)
    preview = giftform.Preview(drawn.append, io)
    assert giftform.review(io, q, GIFT, preview, lambda: HEARD) is None
    preview.settle()
    assert [s.notes for s in drawn] == [("Happy birthday!",), ("Merry Christmas!",)]


def test_the_confirm_says_what_is_deleted_in_red_and_defaults_to_no(frame):
    io = Script(ENTER)
    assert not giftform.confirm(io, GIFT, HEARD)
    said = {style: text for text, style in io.said if style in ("bad", "loss")}
    assert "2,847 detections of 61 species heard here since 14 Sep" in io.text()
    assert "412 clips (1.3 GB)" in io.text()
    assert said["loss"].strip() == "They do not come back."
    assert giftform.confirm(Script("y"), GIFT, HEARD)


def test_a_detector_that_does_not_answer_still_says_the_birds_go(frame):
    io = Script("n")
    giftform.confirm(io, GIFT, gift.Heard(None, None, None, 0, 0))
    assert "every bird BirdNET-Go heard here." in io.text()


def test_wrapping_does_not_draw_again_what_the_glass_holds():
    drawn: list[gift.Splash] = []
    preview = giftform.Preview(drawn.append, Script())
    shown = gift.Splash("May", (), ("Cyanocitta stelleri",), None)
    preview.show(shown)
    preview.final(shown)
    assert drawn == [shown]


def test_a_draw_that_fails_says_why(frame):
    def broken(_splash):
        raise RuntimeError("SPI busy")

    io = Script("x", "q")  # a wrong key shows the summary again, after the draw
    giftform.review(io, _questions(frame, io), GIFT, giftform.Preview(broken, io), lambda: HEARD)
    assert "Could not draw it: SPI busy" in io.text()
    assert io.text().count("Drawing it on the frame") == 1  # not tried again unchanged


def test_tab_completes_the_name_after_the_last_comma():
    birds = giftform.Birds(["Eurasian Hoopoe", "European Robin", "Northern Cardinal"])
    found = birds.get_completions(Document("Northern Cardinal, eur"), None)  # type: ignore[arg-type]
    assert [c.text for c in found] == ["Eurasian Hoopoe", "European Robin"]


def test_the_start_says_which_admin_settings_draw_it(frame, monkeypatch):
    monkeypatch.setattr(giftform.languages, "catalog", lambda _dir: {"en": "English"})
    named = replace(
        frame, settings=Settings(primary_language="en", name_key=True, rotation=90, margin=6)
    )
    assert dict(giftform.look(named)) == {
        "Names": "English, numbered in a key",
        "Labels": "Gentium Book Plus, Medium",
        "Artwork": f"{giftform.resolve('', giftform.IMAGES)}, Spiral layout",
        "Panel": "turned 90°, 6% margin",
    }
    bare = dict(giftform.look(replace(frame, settings=Settings(show_names=False))))
    assert bare["Names"] == "off"
