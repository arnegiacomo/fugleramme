"""`fugleramme-gift`: wrap a working frame as a gift (#355).

    uv run fugleramme-gift          ask about the gift, then wrap it
    uv run fugleramme-gift unwrap   undo a wrap, before the frame is unplugged

It borrows the frame: it stops the frame service, draws on the panel itself, and starts the
service again when it quits. A wrap leaves the service stopped with the splash on the glass;
the next boot brings it back as an ordinary frame. Whatever goes wrong here, a reboot gives
the frame back.

One question at a time, each checked as it is answered and asked again, with what is wrong,
until it is right. After the last one the splash is drawn on the frame, and again after any
change, so what the giver confirms is the picture on the glass. Nothing changes until the
final y/N, which says what is deleted for good. What wrapping does is `gift.py`'s.
"""

from __future__ import annotations

import argparse
import signal
import subprocess
import sys
import textwrap
import threading
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field, replace
from datetime import date, timedelta
from functools import partial
from typing import Protocol

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.completion import CompleteEvent, Completer, Completion
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style

from . import gift, languages, taxa
from .api import ApiSource
from .config import DEFAULT_PORT, REPO_ROOT
from .languages import namer
from .names import drawable_keys, image_for, normalize, resolve
from .panel import Panel, init_panel
from .render import fonts, packing
from .render.dither import dither
from .render.gift import overflow, splash
from .render.page import Edges, day_ordinal
from .settings import Settings, SettingsStore, from_env
from .source import BIRDWEATHER, Unavailable
from .wifi import Nmcli

ARRIVAL = timedelta(weeks=2)  # the date offered first
IMAGES = REPO_ROOT / "assets" / "artwork"
WIDTH = 56  # prose wraps here: a phone's ssh app is 40-60 columns
NOTE_LINES = 3
# ANSI's sixteen only, so a theme keeps them readable on light and dark, and NO_COLOR drops
# them; every meaning is in the words or a mark too.
STYLE = Style.from_dict(
    {
        "title": "bold",
        "question": "bold",
        "hint": "dim",
        "good": "ansigreen",
        "bad": "ansired",
        "loss": "ansired bold",
    }
)
_UTF8 = (sys.stdout.encoding or "").lower().replace("-", "") == "utf8"
OK, NO = ("✓", "✗") if _UTF8 else ("ok", "x")


class Io(Protocol):
    def ask(self, default: str = "", label: str = "> ", completer: Completer | None = None) -> str:
        """One line from the giver, `default` already typed. Ctrl-C raises."""
        ...

    def say(self, text: str = "", style: str = "") -> None: ...


class Terminal:
    def __init__(self) -> None:
        self.session: PromptSession[str] = PromptSession(style=STYLE)

    def ask(self, default: str = "", label: str = "> ", completer: Completer | None = None) -> str:
        return self.session.prompt(
            [("class:hint", label)],
            default=default,
            completer=completer,
            complete_while_typing=False,  # Tab asks; a menu at every key is a lot on a phone
        )

    def say(self, text: str = "", style: str = "") -> None:
        print_formatted_text(
            FormattedText([(f"class:{style}" if style else "", text)]), style=STYLE
        )


def para(io: Io, text: str, style: str = "", indent: str = "") -> None:
    for line in textwrap.wrap(text, WIDTH, initial_indent=indent, subsequent_indent=indent):
        io.say(line, style)


def row(io: Io, lead: str, value: str, style: str = "") -> None:
    """`lead`, then `value` wrapped in the column after it."""
    lines = textwrap.wrap(value, WIDTH - len(lead)) or [""]
    io.say(lead + lines[0], style)
    for more in lines[1:]:
        io.say(" " * len(lead) + more, style)


@dataclass(frozen=True)
class Frame:
    """What the questions need to know about this frame."""

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

    def bird_names(self) -> list[str]:
        """The common names Tab completes: every bird with a picture in this style."""
        return sorted(
            {
                taxa.common_of(sci) or sci
                for sci in self.names.by_name.values()
                if normalize(sci) in self.drawable
            }
        )


@dataclass(frozen=True)
class Gift:
    """The answers so far."""

    place: gift.Place | None = None
    arrives: date | None = None
    favourites: tuple[str, ...] = ()  # scientific names, the spotlight first
    notes: tuple[str, ...] = ()
    ssid: str = ""
    password: str = ""
    clear_admin: bool = False


class Birds(Completer):
    """Completes the name after the last comma."""

    def __init__(self, names: Iterable[str]):
        self.names = list(names)

    def get_completions(self, document: Document, _event: CompleteEvent) -> Iterator[Completion]:
        typed = document.text_before_cursor.rsplit(",", 1)[-1].lstrip()
        key = gift.folded(typed)
        if key:
            for name in self.names:
                if gift.folded(name).startswith(key):
                    yield Completion(name, start_position=-len(typed))


Scores = Callable[[float, float, int], list[tuple[str, float]]]


def _day(day: date) -> str:
    return f"{day:%a} {day.day} {day:%b %Y}"


def _common(sci: str) -> str:
    return taxa.common_of(sci) or sci


@dataclass
class Questions:
    io: Io
    frame: Frame
    today: date
    scores: Scores
    find_place: Callable[[str], gift.Place | None] = gift.find_place
    wifi_problem: Callable[[], str] = lambda: ""  # why this Pi cannot save a network
    _scored: dict[tuple, dict[str, float]] = field(default_factory=dict)

    def steps(self) -> list[tuple[str, Callable[[Gift], Gift]]]:
        """In the order asked, and numbered so in the summary."""
        steps: list[tuple[str, Callable[[Gift], Gift]]] = [
            ("Place", self.place),
            ("Arrives", self.arrives),
            ("Favourites", self.favourites),
            ("Note", self.notes),
            ("Wi-Fi", self.wifi),
        ]
        if self.frame.settings.admin_password:
            steps.append(("Admin", self.admin))
        return steps

    def _question(self, text: str, hint: str) -> None:
        self.io.say()
        self.io.say(text, "question")
        para(self.io, f"({hint})", "hint")

    def _yes(self, text: str) -> None:
        para(self.io, f"{OK} {text}", "good", "  ")

    def _no(self, text: str) -> None:
        para(self.io, f"{NO} {text}", "bad", "  ")

    def place(self, g: Gift) -> Gift:
        self._question("Where is it going?", "a town, an address, or latitude, longitude")
        default = g.place.label if g.place else ""
        while True:
            text = self.io.ask(default).strip()
            default = text
            if not text:
                self._no("Needed: the birds on the picture are the ones there.")
                continue
            if not gift.LAT_LON.fullmatch(text):
                self.io.say("  Looking it up...", "hint")
            try:
                place = self.find_place(text)
            except OSError:
                self._no(
                    "The place search did not answer. Try again, or type latitude, "
                    "longitude from a maps app."
                )
                continue
            if place is None:
                self._no(f"No place called {text}. Try a town nearby, or latitude, longitude.")
                continue
            self._yes(f"{place.label} ({place.latitude:.2f}, {place.longitude:.2f})")
            return replace(g, place=place)

    def arrives(self, g: Gift) -> Gift:
        self._question("When does it arrive?", "YYYY-MM-DD; the birds are that month's")
        default = (g.arrives or self.today + ARRIVAL).isoformat()
        while True:
            text = self.io.ask(default).strip()
            day, problem = gift.arrival(text, self.today)
            if day is not None:
                self._yes(f"{_day(day)}, {day:%B}'s birds")
                return replace(g, arrives=day)
            self._no(problem)
            default = text

    def favourites(self, g: Gift) -> Gift:
        self._question(
            "Birds that must be on it?",
            "separated by commas; the first is drawn large in the middle. Tab completes a "
            "name, Enter alone for none",
        )
        default = ", ".join(map(_common, g.favourites))
        completer = Birds(self.frame.bird_names())
        while True:
            text = self.io.ask(default, completer=completer)
            found, problem, default = self._matched(text, g)
            if not problem:
                if found:
                    shown = [_common(sci) for sci in found]
                    self._yes(", ".join([f"{shown[0]} (large)", *shown[1:]]))
                return replace(g, favourites=found)
            self._no(problem)

    def _matched(self, text: str, g: Gift) -> tuple[tuple[str, ...], str, str]:
        """The favourites found, the first problem, and the line to offer again: what was
        typed with each typo swapped for the bird it likely meant."""
        found, problem, offered = [], "", []
        for typed in (part.strip() for part in text.split(",")):
            if not typed:
                continue
            match = gift.favourite(typed, self.frame.names, self.frame.drawable, self.ranked(g))
            if match.name is not None:
                found.append(match.name)
            problem = problem or match.problem
            offered.append(_common(match.name) if match.name else match.guess or typed)
        return tuple(dict.fromkeys(found)), problem, ", ".join(offered)

    def notes(self, g: Gift) -> Gift:
        self._question(
            "A note for the bottom of the picture?",
            f"up to {NOTE_LINES} lines; Enter on an empty line finishes",
        )
        lines: list[str] = []
        for i in range(NOTE_LINES):
            default = g.notes[i] if i < len(g.notes) else ""
            while True:
                text = self.io.ask(default, label=f"Line {i + 1} > ").strip()
                if not text:
                    return replace(g, notes=tuple(lines))
                frame = self.frame
                over = overflow(text, frame.settings.label_font, frame.size, frame.margin)
                if not over:
                    lines.append(text)
                    break
                self._no(f"{over} characters too long for this frame's panel.")
                default = text
        return replace(g, notes=tuple(lines))

    def wifi(self, g: Gift) -> Gift:
        self._question(
            "The Wi-Fi name where it is going?",
            "so it joins by itself; Enter to skip, and it offers its own Wi-Fi setup",
        )
        default = g.ssid
        while True:
            ssid = self.io.ask(default).strip()
            if not ssid:
                return replace(g, ssid="", password="")
            problem = gift.ssid_problem(ssid) or self.wifi_problem()
            if not problem:
                break
            self._no(problem)
            default = ssid
        self._question(
            "And its password?", "shown as you type, so a typo is caught here; Enter if none"
        )
        default = g.password
        while True:
            password = self.io.ask(default)
            problem = gift.password_problem(password)
            if not problem:
                return replace(g, ssid=ssid, password=password)
            self._no(problem)
            default = password

    def admin(self, g: Gift) -> Gift:
        self._question(
            "Clear the admin password?",
            "the admin page has one; without it they could never change a setting",
        )
        return replace(g, clear_admin=yes_or_no(self.io, True))

    def ranked(self, g: Gift) -> dict[str, float]:
        """The range model's scores where and when it is going, {} while the detector does
        not answer."""
        if g.place is None or g.arrives is None:
            return {}
        where = (g.place.latitude, g.place.longitude, gift.week(g.arrives))
        if where not in self._scored:
            try:
                self._scored[where] = dict(self.scores(*where))
            except Unavailable:
                return {}
        return self._scored[where]

    def splash(self, g: Gift) -> gift.Splash:
        ranked = sorted(self.ranked(g).items(), key=lambda item: -item[1])
        return gift.Splash(
            f"{g.arrives:%B}",
            g.notes,
            gift.splash_birds(ranked, g.favourites, self.frame.drawable),
            g.favourites[0] if g.favourites else None,
        )


def yes_or_no(io: Io, default: bool) -> bool:
    label = "[Y/n] > " if default else "[y/N] > "
    while True:
        answer = io.ask(label=label).strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")
        para(io, f"{NO} Type y or n.", "bad", "  ")


Draw = Callable[[gift.Splash], None]


class Preview:
    """The splash on the glass, drawn behind the questions. One refresh at a time, and a
    refresh is never cut short: an Inky part way through its waveform is left in a mess."""

    def __init__(self, draw: Draw, io: Io):
        self.draw, self.io = draw, io
        self.shown: gift.Splash | None = None
        self._tried: gift.Splash | None = None
        self.error = ""
        self._thread: threading.Thread | None = None

    def show(self, shown: gift.Splash) -> None:
        """Draw it unless it is on the glass, or failed and has not changed since."""
        self.settle()
        if shown in (self.shown, self._tried):
            return
        self._tried, self.error = shown, ""

        def run() -> None:
            try:
                self.draw(shown)
                self.shown = shown
            except Exception as error:
                self.error = str(error) or type(error).__name__

        para(
            self.io,
            "Drawing it on the frame. A full refresh takes up to 30 seconds and the panel "
            "flashes; that is normal.",
            "hint",
        )
        self._thread = threading.Thread(target=run, daemon=True)
        self._thread.start()

    def settle(self) -> None:
        """Wait out a refresh, Ctrl-C included."""
        if self._thread is None or not self._thread.is_alive():
            return
        self.io.say("Finishing this refresh first...", "hint")
        old = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            self._thread.join()
        finally:
            signal.signal(signal.SIGINT, old)

    def final(self, shown: gift.Splash) -> None:
        """Wrapping's draw: only when the glass does not hold it already."""
        self.settle()
        if shown != self.shown:
            self.draw(shown)
            self.shown = shown


def _summary(io: Io, q: Questions, g: Gift, shown: gift.Splash, preview: Preview) -> None:
    password = f", password {g.password}" if g.password else ", no password"
    values = {
        "Place": g.place.label if g.place else "",
        "Arrives": f"{_day(g.arrives)}, {g.arrives:%B}'s birds" if g.arrives else "",
        "Favourites": ", ".join(
            f"{_common(s)} (large)" if i == 0 else _common(s) for i, s in enumerate(g.favourites)
        )
        or "none",
        "Note": " / ".join(g.notes) or "none",
        "Wi-Fi": f"{g.ssid}{password}" if g.ssid else "none; it offers its own setup",
        "Admin": "password cleared" if g.clear_admin else "password kept",
    }
    io.say()
    io.say("The gift", "title")
    for i, (label, _ask) in enumerate(q.steps(), 1):
        row(io, f" {i}  {label:<11}  ", values[label])
    io.say()
    birds = [_common(sci) for sci in shown.birds]
    if not birds:
        para(io, "No birds on it: BirdNET-Go did not say which live there. Add favourites.", "bad")
    else:
        more = f" and {len(birds) - 4} more" if len(birds) > 4 else ""
        para(io, f"On the glass: {', '.join(birds[:4])}{more}.", "hint")
    if preview.error:
        para(io, f"{NO} Could not draw it: {preview.error}", "bad")


def _size(count: int) -> str:
    size = float(count)
    for unit in ("bytes", "KB", "MB"):
        if size < 1000:
            return f"{size:.0f} {unit}" if unit == "bytes" else f"{size:.1f} {unit}"
        size /= 1000
    return f"{size:.1f} GB"


def confirm(io: Io, g: Gift, heard: gift.Heard) -> bool:
    """The last question, and the only one that changes anything."""
    if heard.detections is None:
        birds = "every bird BirdNET-Go heard here"
    else:
        since = f" since {heard.since.day} {heard.since:%b %Y}" if heard.since else ""
        birds = f"{heard.detections:,} detections of {heard.species} species heard here{since}"
    clips = f", and {heard.clips:,} clips ({_size(heard.clip_bytes)})" if heard.clips else ""
    io.say()
    io.say("Wrap it?", "question")
    io.say()
    para(io, f"Deleted for good: {birds}{clips}.", "bad", "  ")
    para(io, "They do not come back.", "loss", "  ")
    para(io, "To keep them, back up BirdNET-Go first and run this again.", "", "  ")
    io.say()
    para(io, "Changed, and put back by `uv run fugleramme-gift unwrap` until it is unplugged:")
    changes = [("Location", g.place.label if g.place else "")]
    if g.ssid:
        changes.append(("Wi-Fi", f"{g.ssid} saved"))
    if g.clear_admin:
        changes.append(("Admin", "password cleared"))
    for label, value in changes:
        row(io, f"  {label:<10}  ", value)
    io.say()
    return yes_or_no(io, False)


def review(
    io: Io, q: Questions, g: Gift, preview: Preview, heard: Callable[[], gift.Heard]
) -> Gift | None:
    """The summary, changes, and the confirm. The gift to wrap, or None to quit."""
    steps = q.steps()
    while True:
        shown = q.splash(g)
        preview.show(shown)
        _summary(io, q, g, shown, preview)
        choice = io.ask(label=f"Change a line (1-{len(steps)}), w to wrap it, q to quit > ")
        choice = choice.strip().lower()
        if choice == "q":
            return None
        if choice == "w":
            preview.settle()
            if confirm(io, g, heard()):
                return g
            continue
        if choice.isdigit() and 1 <= int(choice) <= len(steps):
            g = steps[int(choice) - 1][1](g)
            continue
        para(io, f"{NO} Type a number from 1 to {len(steps)}, w or q.", "bad", "  ")


def look(frame: Frame) -> list[tuple[str, str]]:
    """The admin's settings the splash is drawn with, in the admin's own words."""
    s = frame.settings
    found = languages.catalog(frame.paths.data)

    def language(code: str) -> str:
        return "scientific" if code == languages.SCIENTIFIC else found.get(code, code)

    names = "off"
    if s.show_names:
        names = language(s.primary_language)
        if s.secondary_language != languages.NONE:
            names += f", then {language(s.secondary_language)}"
        if s.name_key:
            names += ", numbered in a key"
    margins = set(s.margins(True))
    margin = (
        f"{margins.pop()}%" if len(margins) == 1 else "{}% {}% {}% {}%".format(*s.margins(True))
    )
    return [
        ("Names", names),
        ("Labels", f"{fonts.FONTS[s.label_font][0]}, {fonts.LABEL_SIZES[s.label_size][0]}"),
        ("Artwork", f"{resolve(s.style, IMAGES)}, {packing.layout_of(s.layout).label} layout"),
        ("Panel", f"turned {s.rotation}°, {margin} margin" if s.rotation else f"{margin} margin"),
    ]


def ask(q: Questions, preview: Preview, heard: Callable[[], gift.Heard]) -> Gift | None:
    q.io.say("Wrap this frame as a gift", "title")
    q.io.say()
    para(
        q.io,
        "It forgets the birds heard here, sets the place it is going and leaves a picture "
        "on the glass for the box. Nothing changes until you say so at the end. Ctrl-C "
        "quits at any point.",
    )
    q.io.say()
    para(q.io, "The picture is drawn with this frame's admin settings:")
    for label, value in look(q.frame):
        q.io.say(f"  {label:<8}  {value}")
    para(
        q.io,
        "To draw it differently, quit, change them in the admin and run this again.",
        "hint",
    )
    g = Gift()
    for _label, step in q.steps():
        g = step(g)
    return review(q.io, q, g, preview, heard)


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
            layout=settings.layout,
            name_key=settings.name_key,
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


def _wifi_problem(nmcli: Nmcli) -> str:
    if not nmcli.allowed():
        return "sudo will not run nmcli here: run install.sh again, or Enter to skip."
    if not nmcli.device():
        return "This Pi has no Wi-Fi to save it on. Enter to skip."
    return ""


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


def wrap(io: Io, paths: gift.Paths, wrapping: gift.Wrapping, nmcli: Nmcli, draw: Draw) -> bool:
    """Ctrl-C waits: the steps take seconds, and stopping between two leaves a frame half
    wrapped."""
    clear, _restore = _admin(paths)
    io.say()
    io.say("Wrapping it. Ctrl-C waits until it is done.", "hint")
    old = signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        gift.wrap(
            paths,
            wrapping,
            _wifi(nmcli),
            clear,
            draw,
            lambda line: row(io, f"  {OK} ", line, "good"),
        )
    except Exception as error:
        para(io, f"{NO} {error}", "bad", "  ")
        para(io, "`uv run fugleramme-gift unwrap` puts back what it had changed.")
        return False
    finally:
        signal.signal(signal.SIGINT, old)
    town = wrapping.place.label.split(",")[0]
    around = "there" if gift.LAT_LON.fullmatch(wrapping.place.label) else f"around {town}"
    io.say()
    io.say("Wrapped.", "title")
    io.say()
    para(
        io,
        "Unplug it now and box it. The picture stays without power. The next time it is "
        f"plugged in, wherever that is, it wakes as a normal frame and starts listening for "
        f"the birds {around}.",
    )
    io.say()
    io.say("Changed your mind? Before you unplug it:")
    io.say("  uv run fugleramme-gift unwrap")
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
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        return "it asks questions, so it needs a terminal: `ssh -t` when ssh runs it"
    return ""


def _hang_up(signum: int, _frame: object) -> None:
    """A dropped ssh session: out through `main`'s finally, which starts the service."""
    raise SystemExit(128 + signum)


def _wrapping(q: Questions, g: Gift) -> gift.Wrapping:
    assert g.place is not None  # the first question
    return gift.Wrapping(g.place, q.splash(g), g.ssid, g.password, g.clear_admin)


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
    print("Pausing the frame. sudo may ask for your password.")
    if not service("stop"):
        sys.exit(f"Could not stop {gift.UNIT}.")
    signal.signal(signal.SIGHUP, _hang_up)
    signal.signal(signal.SIGTERM, _hang_up)
    io = Terminal()
    preview: Preview | None = None
    tried = False  # a wrap that fails leaves the service to `unwrap`, which starts it
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
        preview = Preview(_drawer(paths, panel), io)
        q = Questions(
            io, frame, date.today(), source.range_scores, wifi_problem=partial(_wifi_problem, nmcli)
        )
        g = ask(q, preview, partial(gift.heard, paths, source))
        if g is None:
            io.say("Nothing changed.")
        else:
            tried = True
            wrap(io, paths, _wrapping(q, g), nmcli, preview.final)
    except (KeyboardInterrupt, EOFError):
        print("\nNothing changed.")
    finally:
        if preview is not None:
            preview.settle()
        # Left stopped only after a wrap; a reboot starts it in any case.
        if not tried and not service("start"):
            print(f"Could not start {gift.UNIT}; a reboot will.")
