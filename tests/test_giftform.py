"""The gift questions: each asked again until it is right, the picture, the reset, the wrap."""

from __future__ import annotations

from dataclasses import replace
from functools import partial

import pytest

from fugleramme import gift, giftform
from fugleramme.config import REPO_ROOT
from fugleramme.names import drawable_keys
from fugleramme.render.page import Edges
from fugleramme.settings import Settings

COLUMBUS = gift.Place("Columbus, Ohio, United States", 39.96, -82.99, "US")
RECORDED = ["Turdus migratorius", "Not avis", "Cardinalis cardinalis", "Zenaida macroura"]
DRAWABLE = drawable_keys(REPO_ROOT / "assets" / "artwork", "classic")
ENTER = None  # takes what is offered


class Script:
    """The giver, as a list of answers; out of answers is Ctrl-D."""

    def __init__(self, *answers: str | None):
        self.answers = list(answers)
        self.said: list[tuple[str, str]] = []
        self.offered: list[str] = []
        self.labels: list[str] = []
        self.searched: list[tuple[str, ...]] = []

    def ask(self, default="", label="> ", choices=()):
        self.offered.append(default)
        self.labels.append(label)
        self.searched.append(tuple(choices))
        if not self.answers:
            raise EOFError
        answer = self.answers.pop(0)
        return default if answer is ENTER else answer

    def say(self, text="", style=""):
        self.said.append((text, style))

    def text(self) -> str:
        """All it said, unwrapped."""
        return " ".join(" ".join(text for text, _style in self.said).split())

    def refused(self) -> list[str]:
        return [text.strip() for text, style in self.said if style == "bad" and "✗" in text]


@pytest.fixture
def frame(tmp_path):
    paths = gift.Paths(data=tmp_path, detector=tmp_path / "detector")
    return giftform.Frame(
        paths,
        Settings(admin_password="secret"),
        (800, 480),
        Edges.even(0.04),
        gift.Names.of(REPO_ROOT / "nonexistent", "sci", DRAWABLE),
        DRAWABLE,
    )


def _questions(frame, io, **changes):
    def find(text):
        return COLUMBUS if text == "columbus" else None

    known = {
        "likely": lambda _place: RECORDED,
        "find_place": find,
        "zone_at": lambda _place: "America/New_York",
    }
    return giftform.Questions(io, frame, **{**known, **changes})


def test_each_answer_is_asked_again_until_it_is_right(frame):
    io = Script(
        "nowhere",  # no such place
        "columbus",
        "2",  # choose the birds
        "stellar jay",  # no such bird
        "Steller's Jay",
        "northern cardinal",
        "",
        "Happy birthday! " * 12,  # too long for the panel
        "Happy birthday!",
        "",
        "Birds you may hear " * 20,  # so is this
        "Birds of Columbus",
    )
    q = _questions(frame, io)
    g = giftform.Gift()
    for _label, step in q.steps():
        g = step(g)

    assert g == giftform.Gift(
        COLUMBUS,
        "America/New_York",
        ("Cyanocitta stelleri", "Cardinalis cardinalis"),
        ("Happy birthday!",),
        "Birds of Columbus",
    )
    assert "Steller's Jay" in io.searched[3]  # what is typed searches the birds with a plate
    assert io.offered[-2] == giftform.TITLE
    refused = io.refused()
    assert len(refused) == 4
    assert refused[0].startswith("✗ Couldn't find nowhere")
    assert refused[1].startswith("✗ No artwork for stellar jay")
    assert "Too long for this panel by" in refused[2] and "Too long" in refused[3]


def test_a_place_search_that_does_not_answer_names_the_way_out(frame):
    def offline(_url):
        raise OSError("down")

    io = Script("columbus", "39.96, -82.99")
    q = _questions(frame, io, find_place=partial(gift.find_place, fetch=offline))
    assert q.place(giftform.Gift()).place == gift.Place("39.96, -82.99", 39.96, -82.99)
    assert "Location search is unavailable. Try again, or enter latitude, longitude." in io.text()


def test_a_timezone_the_lookup_does_not_have_is_asked_for(frame):
    io = Script("columbus", "Mars/Olympus", "America/Chicago")
    q = _questions(frame, io, zone_at=lambda _place: "", zone_here=lambda: "Europe/Oslo")
    assert q.place(giftform.Gift()).zone == "America/Chicago"
    assert io.offered[1] == "Europe/Oslo"  # the Pi's own, offered first
    assert "America/Chicago" in io.searched[1]
    assert "✗ Unknown timezone Mars/Olympus. Pick one from the list." in io.text()


def test_a_preview_has_no_clock_to_set(frame):
    q = _questions(frame, Script("columbus"), zone_at=None)
    assert q.place(giftform.Gift()).zone == ""


def test_a_title_cleared_is_the_one_offered(frame):
    assert _questions(frame, Script("")).title(giftform.Gift()).title == giftform.TITLE


GIFT = giftform.Gift(
    COLUMBUS, "America/New_York", ("Cyanocitta stelleri",), ("Happy birthday!",), "Birds near you"
)


def test_the_picture_holds_the_givers_birds_and_no_others(frame):
    shown = _questions(frame, Script()).splash(GIFT)
    assert shown == gift.Splash("Birds near you", ("Happy birthday!",), ("Cyanocitta stelleri",))


def test_a_picture_with_none_named_holds_the_most_recorded_with_a_plate(frame):
    asked = []

    def likely(place):
        asked.append(place)
        return RECORDED

    io = Script("3", ENTER, "41", "2")  # not a choice, the most common, too many, two
    q = _questions(frame, io, likely=likely)
    g = q.birds(replace(GIFT, birds=()))
    assert (g.birds, g.count) == ((), 2)
    assert io.labels == ["choice [1] > "] * 2 + ["how many, 0-40 [20] > "] * 2
    assert "1) the most common near Columbus this month" in io.text()
    assert "✗ Enter a number from 0 to 40." in io.text()
    assert q.splash(g).birds == ("Turdus migratorius", "Cardinalis cardinalis")
    q.splash(g)
    assert asked == [COLUMBUS]  # once a place


def test_naming_birds_goes_on_until_an_empty_line(frame):
    io = Script("2", "great tit", "parus major", "Pica pica", "eurasian blue tit", "")
    g = _questions(frame, io).birds(giftform.Gift(COLUMBUS))
    assert g.birds == (
        "Parus major",
        "Pica pica",
        "Cyanistes caeruleus",
    )  # a bird named twice is one
    assert io.labels[1:] == ["Bird 1 > ", "Bird 2 > ", "Bird 3 > ", "Bird 4 > ", "Bird 5 > "]


def test_no_birds_at_all_is_said_unless_none_were_asked_for(frame):
    io = Script("q")
    q = _questions(frame, io, likely=lambda _place: [])
    giftform.review(io, q, replace(GIFT, birds=()), lambda _splash: None)
    assert "No birds found for this location." in io.text()

    io = Script("q")
    giftform.review(io, _questions(frame, io), replace(GIFT, birds=(), count=0), lambda _s: None)
    assert "No birds found" not in io.text()
    assert "the 0 most common near Columbus this month" in io.text()


def test_the_picture_is_drawn_once_and_again_after_a_change(frame):
    drawn: list[gift.Splash] = []
    io = Script("x", "3", "Merry Christmas!", "", "w")  # a wrong key, then change the note
    wrapped = giftform.review(
        io, _questions(frame, io), GIFT, drawn.append, lambda _g: giftform.Reset(delete=True)
    )
    assert wrapped == (replace(GIFT, notes=("Merry Christmas!",)), giftform.Reset(delete=True))
    assert [s.notes for s in drawn] == [("Happy birthday!",), ("Merry Christmas!",)]
    assert "Columbus, Ohio, United States, America/New_York" in io.text()
    assert "w wrap: prepare the frame for its new owner, then shut it down" in io.text()
    assert "q quit without wrapping; nothing is changed" in io.text()
    assert "✗ Enter 1-4, w or q." in io.text()


def test_a_wrap_not_confirmed_goes_back_to_the_summary_without_drawing_again(frame):
    drawn: list[gift.Splash] = []
    io = Script("w", "q")
    assert giftform.review(io, _questions(frame, io), GIFT, drawn.append, lambda _g: None) is None
    assert len(drawn) == 1 and io.labels == ["choice > "] * 2


def test_a_draw_that_fails_says_why_and_cannot_be_wrapped(frame):
    def broken(_splash):
        raise RuntimeError("SPI busy")

    def never(_g):
        raise AssertionError("asked to confirm")

    io = Script("w", "q")
    assert giftform.review(io, _questions(frame, io), GIFT, broken, never) is None
    assert "Couldn't draw the picture: SPI busy" in io.text()
    assert "✗ Can't wrap: the picture isn't on the panel." in io.text()


def test_a_preview_offers_no_wrap(frame):
    io = Script("w", "q")
    q = _questions(frame, io)
    assert giftform.review(io, q, GIFT, lambda _splash: None) is None
    assert "wrap" not in io.text()
    assert io.refused() == ["✗ Enter 1-4 or q."]


def test_the_wrap_says_all_it_will_do_and_is_confirmed(frame):
    io = Script("y", "delete", ENTER, "n", "y")  # y is not the word for deleting
    chosen = giftform.reset(io, GIFT, frame, 2847, ("Home", "Cabin"), "Europe/Oslo")
    assert chosen == giftform.Reset(True, True, False, "America/New_York")
    assert "Delete this frame's 2,847 detections and audio clips?" in io.text()
    assert "Home, Cabin" in io.text()
    assert io.refused() == ["✗ Type delete, or press Enter to keep them."]
    assert io.text().endswith(
        "Wrapping will: - set the location to Columbus, Ohio, United States "
        "- set the timezone to America/New_York "
        "- delete this frame's detections and audio clips "
        "- forget the saved Wi-Fi networks - shut the frame down Wrap the frame now?"
    )
    assert io.labels[-1] == "[y/N] > "


def test_a_wrap_is_not_done_without_a_yes(frame):
    io = Script("", "n", "n", ENTER)
    assert giftform.reset(io, GIFT, frame, None, ("Home",), "Europe/Oslo") is None
    assert io.text().endswith("Not wrapped. Nothing is changed.")


def test_only_what_is_there_is_asked_and_listed(frame):
    bare = replace(frame, settings=Settings())
    io = Script("", "y")  # keep the birds, then wrap
    chosen = giftform.reset(io, GIFT, bare, None, (), "America/New_York")
    assert chosen == giftform.Reset()  # in its timezone already, so no clock to set
    assert "Delete this frame's detections and audio clips?" in io.text()
    assert io.text().endswith(
        "Wrapping will: - set the location to Columbus, Ohio, United States "
        "- shut the frame down Wrap the frame now?"
    )
    assert len(io.offered) == 2


def test_a_frame_without_its_own_birdnet_go_is_asked_about_no_birds(frame):
    reads = replace(frame, own=False)
    io = Script(ENTER, ENTER, "y")  # the Wi-Fi, the admin password, wrap
    chosen = giftform.reset(io, GIFT, reads, None, ("Home",), "Europe/Oslo")
    assert chosen == giftform.Reset(False, True, True, "America/New_York")
    assert "Delete" not in io.text() and "the location" not in io.text()
    assert "- set the timezone to America/New_York - forget the saved Wi-Fi" in io.text()


class Network:
    def __init__(self, log: list):
        self.log = log

    def forget_saved(self) -> None:
        self.log.append("forget Wi-Fi")


@pytest.fixture
def pi(monkeypatch) -> list:
    """The Pi's sudo and wrap, recorded rather than run."""
    log: list = []

    def root(*command: str) -> bool:
        log.append(command)
        return True

    monkeypatch.setattr(giftform.subprocess, "run", lambda *_a, **_k: None)
    monkeypatch.setattr(gift, "root", root)
    monkeypatch.setattr(gift, "wrap", lambda _paths, wrapping, *_rest: log.append(wrapping))
    return log


def test_a_wrap_says_it_is_done_before_the_wifi_goes_and_powers_off(frame, pi):
    io = Script()
    said = io.say
    io.say = lambda text="", style="": (
        pi.append("Done") if text == "Done" else None,
        said(text, style),
    )  # type: ignore[method-assign]
    chosen = giftform.Reset(True, True, True, "America/New_York")
    assert giftform.wrap(io, frame, GIFT, chosen, Network(pi))  # type: ignore[arg-type]
    assert pi == [
        gift.Wrapping(COLUMBUS, "America/New_York", delete=True, clear_admin=True),
        "Done",
        "forget Wi-Fi",
        ("systemctl", "poweroff"),
    ]
    assert "The frame is shutting down. Wait 30 seconds, then unplug it." in io.text()


def test_a_frame_without_its_own_birdnet_go_is_wrapped_with_no_place(frame, pi):
    io = Script()
    chosen = giftform.Reset(zone="America/New_York")
    giftform.wrap(io, replace(frame, own=False), GIFT, chosen, Network(pi))  # type: ignore[arg-type]
    assert pi == [gift.Wrapping(None, "America/New_York"), ("systemctl", "poweroff")]
    assert "it starts up as usual." in io.text()


def test_a_wrap_that_fails_keeps_the_wifi_and_the_power(frame, pi, monkeypatch):
    def fails(*_args):
        raise RuntimeError("docker compose stop: no such service")

    monkeypatch.setattr(gift, "wrap", fails)
    io = Script()
    chosen = giftform.Reset(forget_wifi=True)
    assert not giftform.wrap(io, frame, GIFT, chosen, Network(pi))  # type: ignore[arg-type]
    assert pi == []
    assert "✗ docker compose stop: no such service" in io.text()
