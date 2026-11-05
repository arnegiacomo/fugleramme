"""`fugleramme-gift`: the form that wraps a working frame as a gift (#355).

    uv run fugleramme-gift          the form
    uv run fugleramme-gift unwrap   undo a wrap, before the frame is unplugged

Each field is checked as it is left, with a ✓ or a ✗ and why at the end of its line. ^P draws
the splash on the frame with whatever is valid; ^W wraps it. Only ^W changes anything, and it
asks twice. What wrapping does is `gift.py`'s; this module is only the form around it.
"""

from __future__ import annotations

import argparse
import sys
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from functools import partial
from pathlib import Path

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
from .names import drawable_keys, resolve
from .panel import external_resolution, glass_size
from .render.gift import overflow
from .render.page import Edges
from .settings import Settings, SettingsStore, from_env
from .source import BIRDWEATHER, Unavailable
from .wifi import Nmcli

ARRIVAL = timedelta(weeks=2)  # the date the form starts with
WAIT_SECONDS = 5 * 60  # for the service to draw the final splash: a 13.3" refresh is ~30 s
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
    def here(cls, paths: gift.Paths, images_dir: Path) -> Frame:
        settings = SettingsStore(paths.settings, from_env()).get()
        native = glass_size() or external_resolution(None, settings.external_panel_size)
        return cls(
            paths,
            settings,
            settings.oriented(native),
            Edges(*(m / 100 for m in settings.margins(True))),
            gift.Names.of(paths.data, settings.primary_language),
            drawable_keys(images_dir, resolve(settings.style, images_dir)),
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

    def splash(self, notes: tuple[str, ...]) -> gift.Gift | None:
        """A preview of whatever is valid, or None without a place and a date."""
        if self.place is None or self.arrival is None:
            return None
        ranked = sorted(self.place_scores().items(), key=lambda item: -item[1])
        birds = gift.splash_birds(ranked, self.favourites, self.frame.drawable)
        good = tuple(
            n for k, n in zip(("note1", "note2", "note3"), notes, strict=True) if n and self.ok(k)
        )
        return gift.Gift(
            gift.PREVIEW,
            self.arrival.strftime("%B"),
            good,
            birds,
            self.favourites[0] if self.favourites else None,
        )

    def ok(self, key: str) -> bool:
        return self.marks.get(key, (True, ""))[0]


class Form:
    """The screen: one line a field, its mark at the end, the keys along the bottom."""

    def __init__(self, checks: Checks, nmcli: Nmcli):
        self.checks = checks
        self.nmcli = nmcli
        self.status = ""
        self.armed = False  # ^W pressed once
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
        current = gift.read(self.checks.frame.paths.gift)
        if current is not None and current.restore is not None:
            self.status = "The frame is being wrapped."
            return
        splash = self.checks.splash(self._notes())
        if splash is None:
            self.status = "^P needs a place and a date with a ✓."
            return
        gift.write(self.checks.frame.paths.gift, splash)
        left = [dict(FIELDS)[k] or "Note" for k, (ok, _t) in self.checks.marks.items() if not ok]
        out = f" Left out: {', '.join(dict.fromkeys(left))}." if left else ""
        self.status = f"Drawing on the frame. A full refresh takes up to 30 seconds.{out}"

    def _wrap(self, event: KeyPressEvent) -> None:
        problems = self.checks.problems()
        if self.areas["ssid"].text.strip() and not self.nmcli.allowed():
            problems.append("Wi-Fi: sudo refuses nmcli here; re-run install.sh")
        if problems:
            self.status = "Not yet. " + "; ".join(problems)
            self.armed = False
            return
        if not self.armed:
            self.armed = True
            self.status = (
                "^W again to wrap: the detector stops and this place's birds are set aside "
                "until it is unwrapped or opened."
            )
            return
        splash = self.checks.splash(self._notes())
        assert splash is not None and self.checks.place is not None  # problems() said so
        self.wrapping = gift.Wrapping(
            place=self.checks.place,
            month=splash.month,
            notes=splash.notes,
            birds=splash.birds,
            spotlight=splash.spotlight,
            ssid=self.areas["ssid"].text.strip(),
            password=self.areas["password"].text,
            clear_admin=self.admin.checked,
        )
        event.app.exit()


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


def _await(paths: gift.Paths) -> str:
    """Wait for the service to draw the splash and sync. "" when it has, else why not."""
    deadline = time.monotonic() + WAIT_SECONDS
    spinner = "|/-\\"
    tick = 0
    while time.monotonic() < deadline:
        present = gift.read(paths.gift)
        if present is not None and present.state == gift.WRAPPED:
            return ""
        if present is not None and present.error:
            return present.error
        print(f"\r  Drawing the splash {spinner[tick % 4]}", end="", flush=True)
        tick += 1
        time.sleep(0.5)
    return "the frame service did not draw it; is it running? (systemctl status fugleramme)"


def _wrap(paths: gift.Paths, wrapping: gift.Wrapping, nmcli: Nmcli) -> int:
    clear, _restore = _admin(paths)
    try:
        gift.wrap(paths, wrapping, _wifi(nmcli), clear, lambda line: print(f"  ✓ {line}"))
    except Exception as error:
        print(f"  ✗ {error}\nNothing is lost: `uv run fugleramme-gift unwrap` puts it back.")
        return 1
    problem = _await(paths)
    print("\r" + " " * 40 + "\r", end="")
    if problem:
        print(f"  ✗ {problem}\n`uv run fugleramme-gift unwrap` puts everything back.")
        return 1
    print(
        "  ✓ Splash drawn and saved\n\n"
        "Wrapped. Unplug it now. The splash stays without power.\n"
        "Don't plug it in again before it's given: the first boot opens it.\n\n"
        "Changed your mind before unplugging? uv run fugleramme-gift unwrap"
    )
    return 0


def unwrap(paths: gift.Paths) -> int:
    present = gift.read(paths.gift)
    if present is None or present.restore is None:
        print("Nothing to unwrap: this frame is not wrapped, or it has been opened already.")
        return 1
    _clear, restore = _admin(paths)
    gift.unwrap(paths, present, Nmcli(DEFAULT_PORT).forget, restore)
    print("Unwrapped: the detector, its birds, the place, the Wi-Fi and the password are back.")
    return 0


def _refusal(paths: gift.Paths) -> str:
    problem = gift.appliance(paths)
    if problem:
        return problem
    if SettingsStore(paths.settings, from_env()).get().detector_kind == BIRDWEATHER:
        return "gift mode is for a frame with its own BirdNET-Go, not a BirdWeather station"
    present = gift.read(paths.gift)
    if present is not None and present.restore is not None:
        return "this frame is wrapped already: `uv run fugleramme-gift unwrap` to start over"
    return ""


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
    frame = Frame.here(paths, REPO_ROOT / "assets" / "artwork")
    settings = frame.settings
    source = ApiSource(
        settings.detector_url, settings.detector_username, settings.detector_password
    )
    nmcli = Nmcli(DEFAULT_PORT)
    form = Form(Checks(frame, date.today(), source.range_scores), nmcli)
    form.app.run()
    if form.wrapping is None:
        present = gift.read(paths.gift)
        if present is not None and present.restore is None:
            paths.gift.unlink(missing_ok=True)  # the preview goes; the birds come back
        return
    sys.exit(_wrap(paths, form.wrapping, nmcli))
