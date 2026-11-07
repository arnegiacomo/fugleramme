"""`fugleramme-gift`: the form that wraps a working frame as a gift (#355).

    uv run fugleramme-gift          the form
    uv run fugleramme-gift unwrap   undo a wrap, before the frame is unplugged

The form borrows the frame: it stops the frame service, draws on the panel itself, and starts
the service again when it quits. A wrap leaves the service stopped with the splash on the
glass; the next boot brings it back as an ordinary frame. Whatever goes wrong here, a reboot
gives the frame back.

Each field is checked as it is left, with a ✓ or a ✗ and why at the end of its line. ^P draws
the splash with whatever is valid; ^W wraps it. Only ^W changes anything, and it asks twice.
What wrapping does is `gift.py`'s; this module is only the form around it.
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import partial

from prompt_toolkit import Application
from prompt_toolkit.formatted_text import StyleAndTextTuples
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.styles import Style
from prompt_toolkit.widgets import Checkbox, Label, TextArea

from . import gift
from .api import ApiSource
from .config import DEFAULT_PORT, REPO_ROOT
from .languages import namer
from .names import drawable_keys, image_for, resolve
from .panel import Panel, init_panel
from .render.dither import dither
from .render.gift import overflow, splash
from .render.page import Edges, day_ordinal
from .settings import Settings, SettingsStore, from_env
from .source import BIRDWEATHER, Unavailable
from .wifi import Nmcli

ARRIVAL = timedelta(weeks=2)  # the date the form starts with
IMAGES = REPO_ROOT / "assets" / "artwork"
_LABEL = 16
_MARK = 36  # "✗ no match - Red-winged Blackbird?" on an 80-column ssh session

FIELDS = (
    ("place", "Place"),
    ("arrives", "Arrives"),
    ("note1", "Note"),
    ("note2", ""),
    ("note3", ""),
    ("favourites", "Favourites"),
    ("ssid", "Wi-Fi name"),
    ("password", "Wi-Fi password"),
)
_REQUIRED = ("place", "arrives")
_KEYS = "Tab next   Shift-Tab back   ^P draw on frame   ^W wrap it   Esc quit"


@dataclass(frozen=True)
class Frame:
    """What the checks need to know about this frame."""

    paths: gift.Paths
    settings: Settings
    size: tuple[int, int]  # the panel's page as it hangs
    margin: Edges
    names: gift.Names
    drawable: set[str]

    @classmethod
    def here(cls, paths: gift.Paths, panel: tuple[int, int]) -> Frame:
        settings = SettingsStore(paths.settings, from_env()).get()
        return cls(
            paths,
            settings,
            settings.oriented(panel),
            Edges(*(m / 100 for m in settings.margins(True))),
            gift.Names.of(paths.data, settings.primary_language),
            drawable_keys(IMAGES, resolve(settings.style, IMAGES)),
        )


Scores = Callable[[float, float, int], list[tuple[str, float]]]


@dataclass
class Checks:
    """Every field's value and verdict, apart from the screen so it can be tested. A mark is
    (ok, text); a field without one has not been checked or is empty and optional."""

    frame: Frame
    today: date
    scores: Scores
    find_place: Callable[[str], gift.Place | None] = gift.find_place
    marks: dict[str, tuple[bool, str]] = field(default_factory=dict)
    place: gift.Place | None = None
    arrival: date | None = None
    favourites: tuple[str, ...] = ()
    _scored: dict[tuple, dict[str, float]] = field(default_factory=dict)

    def check(self, key: str, text: str) -> None:
        """Set `key`'s mark from `text`. Slow for the place and the favourites: run off the
        screen's thread."""
        text = text.strip()
        if not text and key not in _REQUIRED:
            self.marks.pop(key, None)
            if key == "favourites":
                self.favourites = ()
            return
        checks = {
            "place": self._place,
            "arrives": self._arrives,
            "note1": self._note,
            "note2": self._note,
            "note3": self._note,
            "favourites": self._favourites,
            "ssid": self._ssid,
            "password": self._password,
        }
        problem, shown = checks[key](text)
        self.marks[key] = (not problem, problem or shown)

    def _place(self, text: str) -> tuple[str, str]:
        self.place = None
        try:
            place = self.find_place(text)
        except OSError:
            return "the place search did not answer", ""
        if place is None:
            return f"no place called {text}", ""
        self.place = place
        return "", place.label

    def _arrives(self, text: str) -> tuple[str, str]:
        self.arrival, problem = gift.arrival(text, self.today)
        return problem, ""

    def _note(self, text: str) -> tuple[str, str]:
        frame = self.frame
        over = overflow(text, frame.settings.label_font, frame.size, frame.margin)
        return (f"too long by {over} characters" if over else ""), ""

    def _favourites(self, text: str) -> tuple[str, str]:
        self.favourites = ()
        scores = self.place_scores()
        found = []
        for typed in (part.strip() for part in text.split(",")):
            if not typed:
                continue
            name, problem = gift.favourite(typed, self.frame.names, self.frame.drawable, scores)
            if name is None:
                return problem, ""
            found.append(name)
        self.favourites = tuple(found)
        return "", ""

    def _ssid(self, text: str) -> tuple[str, str]:
        return gift.ssid_problem(text), ""

    def _password(self, text: str) -> tuple[str, str]:
        return gift.password_problem(text), ""

    def place_scores(self) -> dict[str, float]:
        """The range model's scores where and when the frame is going, {} until both are
        known or while the detector does not answer."""
        if self.place is None or self.arrival is None:
            return {}
        where = (self.place.latitude, self.place.longitude, gift.week(self.arrival))
        if where not in self._scored:
            try:
                self._scored[where] = dict(self.scores(*where))
            except Unavailable:
                return {}
        return self._scored[where]

    def problems(self) -> list[str]:
        """What stops a wrap, in field order."""
        named = dict(FIELDS)
        out = [
            f"{named[key] or 'Note'}: {text}" for key, (ok, text) in self.marks.items() if not ok
        ]
        out += [f"{named[key]}: not checked yet" for key in _REQUIRED if key not in self.marks]
        return out

    def splash(self, notes: tuple[str, ...]) -> gift.Splash | None:
        """The splash of whatever is valid, or None without a place and a date."""
        if self.place is None or self.arrival is None:
            return None
        ranked = sorted(self.place_scores().items(), key=lambda item: -item[1])
        birds = gift.splash_birds(ranked, self.favourites, self.frame.drawable)
        good = tuple(
            n for k, n in zip(("note1", "note2", "note3"), notes, strict=True) if n and self.ok(k)
        )
        return gift.Splash(
            self.arrival.strftime("%B"),
            good,
            birds,
            self.favourites[0] if self.favourites else None,
        )

    def ok(self, key: str) -> bool:
        return self.marks.get(key, (True, ""))[0]


Draw = Callable[[gift.Splash], None]


class Form:
    """The screen: one line a field, its mark at the end, the keys along the bottom."""

    def __init__(self, checks: Checks, nmcli: Nmcli, draw: Draw):
        self.checks = checks
        self.nmcli = nmcli
        self.draw = draw
        self.status = ""
        self.armed = False  # ^W pressed once
        self.drawing = False  # a refresh takes up to 30 s; one at a time
        self.wrapping: gift.Wrapping | None = None
        frame = checks.frame
        start = {"arrives": (checks.today + ARRIVAL).isoformat()}
        self.areas = {
            key: TextArea(
                text=start.get(key, ""), multiline=False, password=key == "password", height=1
            )
            for key, _label in FIELDS
        }
        for key, area in self.areas.items():
            area.buffer.on_text_changed += partial(self._typed, key)
        self.admin = Checkbox("Clear the admin password", checked=False)
        rows = [self._row(label, key) for key, label in FIELDS]
        if frame.settings.admin_password:
            rows.append(VSplit([Label("Admin", width=_LABEL), self.admin]))
        body = HSplit(
            [
                Label(" Wrap this frame as a gift", style="class:title"),
                Window(height=1),
                *rows,
                Window(height=1),
                Window(FormattedTextControl(lambda: self.status), height=2, wrap_lines=True),
                Window(FormattedTextControl(_KEYS), height=1, style="class:keys"),
            ]
        )
        self.app: Application[None] = Application(
            layout=Layout(body, focused_element=self.areas["place"]),
            key_bindings=self._keys(),
            style=Style.from_dict(
                {"good": "ansigreen", "bad": "ansired", "title": "bold", "keys": "reverse"}
            ),
            full_screen=True,
        )

    def _row(self, label: str, key: str) -> VSplit:
        return VSplit(
            [
                Label(label, width=_LABEL),
                self.areas[key],
                Window(width=2),
                Window(FormattedTextControl(lambda: self._mark(key)), width=_MARK),
            ]
        )

    def _mark(self, key: str) -> StyleAndTextTuples:
        mark = self.checks.marks.get(key)
        if mark is None:
            return []
        ok, text = mark
        return [("class:good", f"✓ {text}".rstrip())] if ok else [("class:bad", f"✗ {text}")]

    def _typed(self, key: str, _buffer: object) -> None:
        """Typing clears the field's mark, and disarms ^W."""
        self.checks.marks.pop(key, None)
        self.armed = False

    def _check(self, key: str) -> None:
        """Off the screen's thread; a result for text that has changed since is dropped."""
        text = self.areas[key].text

        def run() -> None:
            self.checks.check(key, text)
            if self.areas[key].text != text:
                self.checks.marks.pop(key, None)
            if key in ("place", "arrives") and "favourites" in self.checks.marks:
                self.checks.check("favourites", self.areas["favourites"].text)  # new scores
            self.app.invalidate()

        threading.Thread(target=run, daemon=True).start()

    def _focused(self) -> str | None:
        for key, area in self.areas.items():
            if self.app.layout.has_focus(area):
                return key
        return None

    def _keys(self) -> KeyBindings:
        keys = KeyBindings()

        @keys.add("tab")
        def _next(event: KeyPressEvent) -> None:
            self._leave()
            event.app.layout.focus_next()

        @keys.add("s-tab")
        def _back(event: KeyPressEvent) -> None:
            self._leave()
            event.app.layout.focus_previous()

        @keys.add("c-p")
        def _draw(_event: KeyPressEvent) -> None:
            self._preview()

        @keys.add("c-w")
        def _wrap(event: KeyPressEvent) -> None:
            self._wrap(event)

        @keys.add("escape", eager=True)
        @keys.add("c-c")
        def _quit(event: KeyPressEvent) -> None:
            event.app.exit()

        return keys

    def _leave(self) -> None:
        key = self._focused()
        if key is not None:
            self._check(key)

    def _notes(self) -> tuple[str, ...]:
        return tuple(self.areas[k].text.strip() for k in ("note1", "note2", "note3"))

    def _preview(self) -> None:
        if self.drawing:
            self.status = "Still drawing the last one."
            return
        splash = self.checks.splash(self._notes())
        if splash is None:
            self.status = "^P needs a place and a date with a ✓."
            return
        left = [dict(FIELDS)[k] or "Note" for k, (ok, _t) in self.checks.marks.items() if not ok]
        out = f" Left out: {', '.join(dict.fromkeys(left))}." if left else ""
        self.drawing = True
        self.status = f"Drawing on the frame. A full refresh takes up to 30 seconds.{out}"

        def run() -> None:
            try:
                self.draw(splash)
                self.status = f"Drawn.{out}"
            except Exception as error:
                self.status = f"Could not draw it: {error}"
            finally:
                self.drawing = False
                self.app.invalidate()

        threading.Thread(target=run, daemon=True).start()

    def _wrap(self, event: KeyPressEvent) -> None:
        problems = self.checks.problems()
        if self.areas["ssid"].text.strip() and not self.nmcli.allowed():
            problems.append("Wi-Fi: sudo refuses nmcli here; re-run install.sh")
        if self.drawing:
            problems.append("wait for the drawing to finish")
        if problems:
            self.status = "Not yet. " + "; ".join(problems)
            self.armed = False
            return
        if not self.armed:
            self.armed = True
            self.status = (
                "^W again to wrap: the detector stops and this frame's birds are deleted for good."
            )
            return
        splash = self.checks.splash(self._notes())
        assert splash is not None and self.checks.place is not None  # problems() said so
        self.wrapping = gift.Wrapping(
            place=self.checks.place,
            splash=splash,
            ssid=self.areas["ssid"].text.strip(),
            password=self.areas["password"].text,
            clear_admin=self.admin.checked,
        )
        event.app.exit()


def _drawer(paths: gift.Paths, panel: Panel) -> Draw:
    """Draw a splash on the panel the way the service would draw a page: the frame's own
    settings, dithered, turned by its rotation."""

    def draw(shown: gift.Splash) -> None:
        settings = SettingsStore(paths.settings, from_env()).get()
        name_of = namer(settings.primary_language, settings.secondary_language, paths.data)
        style, day = resolve(settings.style, IMAGES), day_ordinal()
        page = splash(
            [(name, image_for(name, IMAGES, style, day)) for name in shown.birds],
            shown.spotlight,
            shown.month,
            shown.notes,
            settings.oriented(panel.resolution),
            Edges(*(m / 100 for m in settings.margins(True))),
            font_key=settings.label_font,
            label_size=settings.label_size,
            label_text=name_of.label,
            show_names=settings.show_names,
            textured=False,  # flat paper and one-bit words, as the panel's page
        )
        panel.push(dither(page), settings.rotation)

    return draw


def _wifi(nmcli: Nmcli) -> Callable[[str, str], str]:
    def save(ssid: str, password: str) -> str:
        uuid = nmcli.save(nmcli.device(), ssid, password)
        if not uuid:
            raise RuntimeError(f"NetworkManager would not save {ssid}")
        return uuid

    return save


def _admin(paths: gift.Paths) -> tuple[Callable[[], str], Callable[[str], None]]:
    store = SettingsStore(paths.settings, from_env())

    def clear() -> str:
        old = store.get().admin_password
        store.update(admin_password="")
        return old

    def restore(password: str) -> None:
        store.update(admin_password=password)

    return clear, restore


def service(action: str) -> bool:
    """Stop or start the frame service. Without a password where sudo allows it, else asking
    for one where there is a terminal to ask on."""
    command = ["systemctl", action, gift.UNIT]
    if subprocess.run(["sudo", "-n", *command], capture_output=True, check=False).returncode == 0:
        return True
    if not sys.stdin.isatty():
        return False
    return subprocess.run(["sudo", *command], check=False).returncode == 0


def _wrap(paths: gift.Paths, wrapping: gift.Wrapping, nmcli: Nmcli, draw: Draw) -> bool:
    clear, _restore = _admin(paths)
    print("Wrapping. The last step draws the splash, which takes up to 30 seconds.")
    try:
        gift.wrap(paths, wrapping, _wifi(nmcli), clear, draw, lambda line: print(f"  ✓ {line}"))
    except Exception as error:
        print(f"  ✗ {error}\n`uv run fugleramme-gift unwrap` puts back what it had changed.")
        return False
    print(
        "\nWrapped. Unplug it now. The splash stays without power.\n"
        "Don't plug it in again before it's given: the first boot opens it.\n\n"
        "Changed your mind before unplugging? uv run fugleramme-gift unwrap"
    )
    return True


def unwrap(paths: gift.Paths) -> int:
    _clear, restore = _admin(paths)
    if not gift.unwrap(paths, Nmcli(DEFAULT_PORT).forget, restore):
        print("Nothing to unwrap: this frame is not wrapped, or it has been unplugged since.")
        return 1
    service("start")
    print("Unwrapped: the place, the Wi-Fi, the password and the frame are back.")
    return 0


def _refusal(paths: gift.Paths) -> str:
    problem = gift.appliance(paths)
    if problem:
        return problem
    if SettingsStore(paths.settings, from_env()).get().detector_kind == BIRDWEATHER:
        return "gift mode is for a frame with its own BirdNET-Go, not a BirdWeather station"
    if gift.read_undo(paths.undo) is not None:
        return "this frame is wrapped already: `uv run fugleramme-gift unwrap` to start over"
    return ""


def _hang_up(signum: int, _frame: object) -> None:
    """A dropped ssh session: out through `main`'s finally, which starts the service."""
    raise SystemExit(128 + signum)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fugleramme-gift", description=__doc__.split("\n")[0])
    parser.add_argument("action", nargs="?", choices=["unwrap"], help="undo a wrap")
    args = parser.parse_args(argv)
    paths = gift.Paths()
    if args.action == "unwrap":
        sys.exit(unwrap(paths))
    refusal = _refusal(paths)
    if refusal:
        sys.exit(refusal)
    print("The frame service stops while you set up the gift. sudo may ask for your password.")
    if not service("stop"):
        sys.exit(f"Could not stop {gift.UNIT}.")
    signal.signal(signal.SIGHUP, _hang_up)
    signal.signal(signal.SIGTERM, _hang_up)
    wrapped = False
    try:
        panel = init_panel()
        if panel is None:
            sys.exit("No Inky panel here: nothing would hold the splash without power.")
        frame = Frame.here(paths, panel.resolution)
        settings = frame.settings
        source = ApiSource(
            settings.detector_url, settings.detector_username, settings.detector_password
        )
        nmcli = Nmcli(DEFAULT_PORT)
        draw = _drawer(paths, panel)
        form = Form(Checks(frame, date.today(), source.range_scores), nmcli, draw)
        form.app.run()
        if form.wrapping is not None:
            wrapped = _wrap(paths, form.wrapping, nmcli, draw)
    finally:
        # Left stopped only with the splash on the glass; a reboot starts it in any case.
        if not wrapped and not service("start"):
            print(f"Could not start {gift.UNIT}; a reboot will.")
