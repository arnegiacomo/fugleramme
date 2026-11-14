"""`fugleramme-gift`: wrap a working frame as a gift (#355).

    uv run fugleramme-gift                    ask about the gift, then wrap it
    uv run fugleramme-gift --preview OUT.png  ask about the picture and save it, nothing else

It borrows the frame: it stops the frame service, draws on the panel itself, and starts the
service again when it quits. A wrap powers the Pi off with the splash on the glass; the next
boot brings it back as an ordinary frame. Whatever goes wrong here, a reboot gives the frame
back.

One question at a time, each checked as it is answered and asked again, with what is wrong,
until it is right. After the last one the splash is drawn on the frame, and again after any
change, so what the giver wraps is the picture on the glass. Nothing changes before the
wrap, which first asks what else to clear, lists all it will do and asks for a yes. What
wrapping does is `gift.py`'s.
"""

from __future__ import annotations

import argparse
import contextlib
import signal
import subprocess
import sys
import textwrap
import zoneinfo
from collections.abc import Callable, Iterator, Sequence
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Protocol

from PIL import Image, ImageFont
from prompt_toolkit import print_formatted_text, prompt
from prompt_toolkit.completion import FuzzyCompleter, WordCompleter
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style

from . import gift, taxa
from .api import ApiSource
from .config import DEFAULT_PORT, REPO_ROOT
from .languages import namer
from .names import drawable_keys, image_for, resolve
from .panel import Panel, init_panel, resolution_of
from .render.dither import dither
from .render.gift import TITLE, note_font, overflow, smallest_title, splash
from .render.page import Edges, day_ordinal
from .settings import Settings, SettingsStore, from_env
from .source import BIRDWEATHER
from .wifi import Nmcli

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
        "warn": "ansiyellow",
    }
)
_UTF8 = (sys.stdout.encoding or "").lower().replace("-", "") == "utf8"
OK, NO = ("✓", "✗") if _UTF8 else ("ok", "x")


class Io(Protocol):
    def ask(self, default: str = "", label: str = "> ", choices: Sequence[str] = ()) -> str:
        """One line from the giver, `default` already typed. With `choices`, what is typed
        searches them. Ctrl-C raises."""
        ...

    def say(self, text: str = "", style: str = "") -> None: ...


class Terminal:
    def ask(self, default: str = "", label: str = "> ", choices: Sequence[str] = ()) -> str:
        # The whole line is the search, as a name has spaces: "stlr jay" finds Steller's Jay.
        search = FuzzyCompleter(WordCompleter(list(choices), sentence=True), pattern=r"^.+")
        return prompt(
            [("class:hint", label)],
            default=default,
            style=STYLE,
            completer=search if choices else None,
            complete_while_typing=True,
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


def question(io: Io, text: str, hint: str) -> None:
    io.say()
    io.say(text, "question")
    para(io, hint, "hint")


def banner(io: Io, text: str) -> None:
    """The command's title, ruled off from what sudo and the panel printed above it."""
    rule = ("═" if _UTF8 else "=") * WIDTH
    io.say()
    io.say(rule, "title")
    io.say(f" {text}", "title")
    io.say(rule, "title")
    io.say()


def refuse(io: Io, text: str) -> None:
    para(io, f"{NO} {text}", "bad", "  ")


def yes_or_no(io: Io, default: bool) -> bool:
    label = "[Y/n] > " if default else "[y/N] > "
    while True:
        answer = io.ask(label=label).strip().lower()
        if not answer:
            return default
        if answer in ("y", "yes", "n", "no"):
            return answer.startswith("y")
        refuse(io, "Enter y or n.")


@contextlib.contextmanager
def held(*signals: int) -> Iterator[None]:
    """Ignore these signals through a step that must not stop half way."""
    old = [(number, signal.signal(number, signal.SIG_IGN)) for number in signals]
    try:
        yield
    finally:
        for number, handler in old:
            signal.signal(number, handler)


@dataclass(frozen=True)
class Frame:
    """What the questions and the picture need to know about this frame."""

    paths: gift.Paths
    settings: Settings
    size: tuple[int, int]  # the panel's page as it hangs
    margin: Edges
    names: gift.Names
    drawable: set[str]
    own: bool = True  # this Pi's own BirdNET-Go hears its birds: a place and a history to change

    @classmethod
    def here(cls, paths: gift.Paths, panel: Panel | None) -> Frame:
        settings = SettingsStore(paths.settings, from_env()).get()
        drawable = drawable_keys(IMAGES, resolve(settings.style, IMAGES))
        return cls(
            paths,
            settings,
            settings.oriented(resolution_of(panel, settings.external_panel_size)),
            Edges(*(m / 100 for m in settings.margins(True))),
            gift.Names.of(paths.data, settings.primary_language, drawable),
            drawable,
            gift.bundled(paths) and settings.detector_kind != BIRDWEATHER,
        )


@dataclass(frozen=True)
class Gift:
    """The answers so far."""

    place: gift.Place | None = None
    zone: str = ""  # the place's timezone, "" when nothing looked it up
    birds: tuple[str, ...] = ()  # the giver's own, scientific; none: the most recorded there
    notes: tuple[str, ...] = ()
    title: str = TITLE
    count: int = gift.BIRDS  # how many of the most recorded, when the giver names none


def _common(sci: str) -> str:
    return taxa.common_of(sci) or sci


def _near(g: Gift) -> str:
    """The place in a few words: its town, or the position as typed."""
    label = g.place.label if g.place else ""
    return label if gift.LAT_LON.fullmatch(label) else label.split(",")[0]


def _likely(place: gift.Place) -> list[str]:
    return gift.likely(place, date.today())


@dataclass
class Questions:
    io: Io
    frame: Frame
    likely: Callable[[gift.Place], list[str]] = _likely
    find_place: Callable[[str], gift.Place | None] = gift.find_place
    zone_at: Callable[[gift.Place], str] | None = gift.zone_at  # None: no clock to set
    zone_here: Callable[[], str] = gift.zone_here
    _recorded: dict[gift.Place, list[str]] = field(default_factory=dict)

    def steps(self) -> list[tuple[str, Callable[[Gift], Gift]]]:
        """In the order asked, and numbered so in the summary."""
        return [
            ("Location", self.place),
            ("Birds", self.birds),
            ("Message", self.notes),
            ("Title", self.title),
        ]

    def place(self, g: Gift) -> Gift:
        question(
            self.io,
            "Location",
            "Where the recipient lives: a town, an address, or latitude, longitude.",
        )
        default = g.place.label if g.place else ""
        while True:
            text = self.io.ask(default).strip()
            default = text
            if not text:
                refuse(self.io, "A location is required.")
                continue
            if not gift.LAT_LON.fullmatch(text):
                self.io.say("  Searching...", "hint")
            try:
                place = self.find_place(text)
            except OSError:
                refuse(
                    self.io,
                    "Location search is unavailable. Try again, or enter latitude, longitude.",
                )
                continue
            if place is None:
                refuse(self.io, f"Couldn't find {text}. Try a nearby town, or latitude, longitude.")
                continue
            zone = self._zone(place)
            where = f"{place.label} ({place.latitude:.2f}, {place.longitude:.2f})"
            para(self.io, f"{OK} {where}{f', {zone}' if zone else ''}", "good", "  ")
            return replace(g, place=place, zone=zone)

    def _zone(self, place: gift.Place) -> str:
        """The place's timezone, asked for when the lookup has none."""
        if self.zone_at is None:
            return ""
        zone = self.zone_at(place)
        if zone:
            return zone
        question(
            self.io,
            "Timezone",
            "Couldn't look it up for this location. Type to search, for example oslo.",
        )
        zones = sorted(zoneinfo.available_timezones())
        default = self.zone_here()
        while True:
            text = self.io.ask(default, choices=zones).strip()
            if text in zones:
                return text
            refuse(self.io, f"Unknown timezone {text}. Pick one from the list.")
            default = text

    def birds(self, g: Gift) -> Gift:
        self.io.say()
        self.io.say("Birds on the picture", "question")
        row(self.io, "  1) ", f"the most common near {_near(g)} this month")
        row(self.io, "  2) ", "choose them yourself")
        default = "2" if g.birds else "1"
        while True:
            choice = self.io.ask(label=f"choice [{default}] > ").strip() or default
            if choice in ("1", "2"):
                break
            refuse(self.io, "Enter 1 or 2.")
        if choice == "1":
            most = gift.MOST_BIRDS
            while True:
                text = self.io.ask(label=f"how many, 0-{most} [{g.count}] > ").strip() or str(
                    g.count
                )
                if text.isdigit() and int(text) <= most:
                    return replace(g, birds=(), count=int(text))
                refuse(self.io, f"Enter a number from 0 to {most}.")
        para(
            self.io,
            "Type part of a name, English or scientific, and pick from the list. Leave "
            "empty to finish.",
            "hint",
        )
        names = self.frame.names
        picked: list[str] = []
        default = _common(g.birds[0]) if g.birds else ""
        while len(picked) < gift.MOST_BIRDS:
            text = self.io.ask(default, f"Bird {len(picked) + 1} > ", names.shown).strip()
            if not text:
                break
            found = names.match(text)
            if found is None:
                refuse(self.io, f"No artwork for {text} in this style. Pick one from the list.")
                default = text
                continue
            picked.append(found)
            default = _common(g.birds[len(picked)]) if len(picked) < len(g.birds) else ""
        return replace(g, birds=tuple(dict.fromkeys(picked)))

    def notes(self, g: Gift) -> Gift:
        question(
            self.io,
            "Message",
            f"Shown at the bottom of the picture. Up to {NOTE_LINES} lines; leave a line "
            "empty to finish.",
        )
        font = note_font(self.frame.settings.label_font, min(self.frame.size))
        lines: list[str] = []
        for i in range(NOTE_LINES):
            text = self._fitting(g.notes[i] if i < len(g.notes) else "", f"Line {i + 1} > ", font)
            if not text:
                break
            lines.append(text)
        return replace(g, notes=tuple(lines))

    def title(self, g: Gift) -> Gift:
        question(self.io, "Title", "Shown at the top of the picture. Press Enter to keep it.")
        text = self._fitting(g.title, "> ", smallest_title(min(self.frame.size)))
        return replace(g, title=text or TITLE)

    def _fitting(self, default: str, label: str, font: ImageFont.FreeTypeFont) -> str:
        """A line that fits the picture's width, or "" for none."""
        while True:
            text = self.io.ask(default, label).strip()
            over = overflow(text, font, self.frame.size, self.frame.margin)
            if not over:
                return text
            refuse(self.io, f"Too long for this panel by {over} characters.")
            default = text

    def recorded(self, g: Gift) -> list[str]:
        """The birds most recorded where it is going, asked once a place."""
        if g.place is None:
            return []
        if g.place not in self._recorded:
            self._recorded[g.place] = self.likely(g.place)
        return self._recorded[g.place]

    def splash(self, g: Gift) -> gift.Splash:
        birds = g.birds or gift.top_birds(self.recorded(g), self.frame.drawable, g.count)
        return gift.Splash(g.title, g.notes, birds)


Draw = Callable[[gift.Splash], None]


def _summary(io: Io, q: Questions, g: Gift, shown: gift.Splash, error: str) -> None:
    values = {
        "Location": ", ".join(part for part in (g.place.label if g.place else "", g.zone) if part),
        "Birds": ", ".join(map(_common, g.birds))
        or f"the {g.count} most common near {_near(g)} this month",
        "Message": " / ".join(g.notes) or "none",
        "Title": g.title,
    }
    io.say()
    io.say("Summary", "title")
    for i, (label, _ask) in enumerate(q.steps(), 1):
        row(io, f" {i}  {label:<8}  ", values[label])
    io.say()
    if not shown.birds and g.count:
        para(
            io,
            "No birds found for this location. Change line 2 and choose them yourself.",
            "bad",
        )
    if error:
        para(io, f"{NO} Couldn't draw the picture: {error}", "bad")


@dataclass(frozen=True)
class Reset:
    """What a wrap changes besides the location, as the giver answered."""

    delete: bool = False
    forget_wifi: bool = False
    clear_admin: bool = False
    zone: str = ""  # the timezone to set, "" when it is the Pi's already


Confirm = Callable[[Gift], Reset | None]


def review(
    io: Io, q: Questions, g: Gift, draw: Draw, confirm: Confirm | None = None
) -> tuple[Gift, Reset] | None:
    """The picture, the summary and what to do next: change a line, wrap, or quit. The gift
    and what to clear with it once the giver has confirmed the wrap, or None when they quit.
    Without `confirm` it is a preview, and there is nothing to wrap."""
    steps = q.steps()
    lines = f"1-{len(steps)}"
    shown, error = None, ""
    while True:
        asked = q.splash(g)
        if asked != shown:
            shown, error = asked, ""
            try:
                draw(shown)
            except Exception as failure:
                error = str(failure) or type(failure).__name__
        _summary(io, q, g, shown, error)
        io.say()
        row(io, f"  {lines:<5}", "change that line and redraw the picture")
        if confirm:
            row(io, "  w    ", "wrap: prepare the frame for its new owner, then shut it down")
            row(io, "  q    ", "quit without wrapping; nothing is changed")
        else:
            row(io, "  q    ", "quit")
        choice = io.ask(label="choice > ").strip().lower()
        if choice == "q":
            return None
        if choice.isdigit() and 1 <= int(choice) <= len(steps):
            g = steps[int(choice) - 1][1](g)
        elif choice == "w" and confirm and error:
            refuse(io, "Can't wrap: the picture isn't on the panel.")
        elif choice == "w" and confirm:
            chosen = confirm(g)
            if chosen is not None:
                return g, chosen
        else:
            refuse(io, f"Enter {lines}{', w' if confirm else ''} or q.")


def ask(q: Questions, title: str, intro: str, warning: str = "") -> Gift:
    """The command's opening and its questions, each once."""
    banner(q.io, title)
    para(q.io, intro)
    q.io.say()
    if warning:
        para(q.io, warning, "warn")
        q.io.say()
    para(
        q.io,
        "The picture uses this frame's display settings from the admin: language, label "
        "font, artwork, rotation and margins.",
        "hint",
    )
    g = Gift()
    for _label, step in q.steps():
        g = step(g)
    return g


def reset(
    io: Io, g: Gift, frame: Frame, heard: int | None, networks: Sequence[str], zone_here: str
) -> Reset | None:
    """What else to clear, then everything the wrap will do, to confirm. None when the giver
    says no: nothing has changed, and the summary is still there to go back to."""
    io.say()
    io.say("Wrap", "title")
    answer = ""
    if frame.own:
        count = "" if heard is None else f" {heard:,}"
        question(
            io,
            f"Delete this frame's{count} detections and audio clips?",
            "This can't be undone. Type delete to confirm, or press Enter to keep them.",
        )
        while True:
            answer = io.ask().strip().lower()
            if answer in ("", "delete"):
                break
            refuse(io, "Type delete, or press Enter to keep them.")
    forget_wifi = clear_admin = False
    if networks:
        question(
            io,
            "Forget saved Wi-Fi networks?",
            f"{', '.join(networks)}. The frame then starts Wi-Fi setup the next time it's "
            "plugged in.",
        )
        forget_wifi = yes_or_no(io, True)
    if frame.settings.admin_password:
        question(
            io,
            "Remove the admin password?",
            "The recipient can't change settings without it.",
        )
        clear_admin = yes_or_no(io, True)
    chosen = Reset(
        answer == "delete", forget_wifi, clear_admin, g.zone if g.zone != zone_here else ""
    )
    will = [f"set the location to {g.place.label}"] if frame.own and g.place else []
    will += [f"set the timezone to {chosen.zone}"] if chosen.zone else []
    will += ["delete this frame's detections and audio clips"] if chosen.delete else []
    will += ["forget the saved Wi-Fi networks"] if forget_wifi else []
    will += ["remove the admin password"] if clear_admin else []
    io.say()
    io.say("Wrapping will:", "question")
    for line in [*will, "shut the frame down"]:
        row(io, "  - ", line)
    io.say()
    io.say("Wrap the frame now?", "question")
    if yes_or_no(io, False):
        return chosen
    io.say("Not wrapped. Nothing is changed.")
    return None


def _page(frame: Frame, shown: gift.Splash, textured: bool) -> Image.Image:
    """The splash the way the service would draw a page: the frame's own settings."""
    settings, data = frame.settings, frame.paths.data
    name_of = namer(settings.primary_language, settings.secondary_language, data)
    style, day = resolve(settings.style, IMAGES), day_ordinal()
    return splash(
        [(name, image_for(name, IMAGES, style, day)) for name in shown.birds],
        shown.title,
        shown.notes,
        frame.size,
        frame.margin,
        font_key=settings.label_font,
        label_size=settings.label_size,
        label_text=name_of.label,
        show_names=settings.show_names,
        textured=textured,
        layout=settings.layout,
        name_key=settings.name_key,
    )


def _on_panel(io: Io, frame: Frame, panel: Panel) -> Draw:
    def draw(shown: gift.Splash) -> None:
        para(
            io,
            "Drawing the picture on the panel. This takes up to 30 seconds and the panel "
            "flashes while it updates.",
            "hint",
        )
        page = dither(_page(frame, shown, textured=False))  # flat, as the panel's own page
        # An Inky cut off part way through its waveform is left in a mess.
        with held(signal.SIGINT):
            panel.push(page, frame.settings.rotation)

    return draw


def _to_file(io: Io, frame: Frame, out: Path) -> Draw:
    def draw(shown: gift.Splash) -> None:
        _page(frame, shown, textured=True).save(out)
        io.say(f"Saved to {out}", "hint")

    return draw


def service(action: str) -> bool:
    """Stop or start the frame service."""
    return gift.root("systemctl", action, gift.UNIT)


def wrap(io: Io, frame: Frame, g: Gift, chosen: Reset, nmcli: Nmcli) -> bool:
    """Ctrl-C and a dropped connection are ignored: the steps take seconds, and stopping
    between two leaves a frame half wrapped."""
    assert g.place is not None  # the first question
    place = g.place if frame.own else None
    wrapping = gift.Wrapping(place, chosen.zone, chosen.delete, chosen.clear_admin)
    store = SettingsStore(frame.paths.settings, from_env())
    io.say()
    io.say("Wrapping. Don't unplug the frame.", "hint")
    # Asked now: forgetting the Wi-Fi may leave no connection to ask on before the power-off.
    subprocess.run(["sudo", "-v"], check=False)
    with held(signal.SIGINT, signal.SIGHUP, signal.SIGTERM):
        try:
            gift.wrap(
                frame.paths,
                wrapping,
                lambda: store.update(admin_password=""),
                lambda line: row(io, f"  {OK} ", line, "good"),
            )
        except Exception as error:
            refuse(io, str(error))
            para(
                io,
                f"Wrapping stopped. The steps marked {OK} are done. Fix the problem and run "
                "the command again.",
            )
            return False
        io.say()
        io.say("Done", "title")
        io.say()
        para(
            io,
            "The frame is shutting down. Wait 30 seconds, then unplug it. The picture stays "
            "on the panel without power. The next time it's plugged in, it starts up as "
            "usual.",
        )
        if chosen.forget_wifi:
            nmcli.forget_saved()
        if not gift.root("systemctl", "poweroff"):
            para(io, "Couldn't shut the frame down. You can unplug it now.")
    return True


def _reads(settings: Settings) -> str:
    """Where a frame without a BirdNET-Go of its own gets its birds."""
    if settings.detector_kind == BIRDWEATHER:
        return "BirdWeather"
    return f"the BirdNET-Go at {settings.detector_url}"


def _source(settings: Settings) -> ApiSource:
    return ApiSource(settings.detector_url, settings.detector_username, settings.detector_password)


def _hang_up(signum: int, _frame: object) -> None:
    """A dropped ssh session: out through `main`'s finally, which starts the service."""
    raise SystemExit(128 + signum)


def preview(io: Io, paths: gift.Paths, out: Path) -> None:
    """The questions about the picture and the picture as a file, on any machine."""
    frame = Frame.here(paths, None)
    q = Questions(io, frame, zone_at=None)
    intro = f"The picture is saved to {out}. Nothing else is changed."
    with contextlib.suppress(KeyboardInterrupt, EOFError):
        review(io, q, ask(q, "Gift picture preview", intro), _to_file(io, frame, out))


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="fugleramme-gift", description=__doc__.split("\n")[0])
    parser.add_argument(
        "--preview",
        type=Path,
        metavar="OUT.png",
        help="ask about the picture and save it there; no frame, panel or wrap",
    )
    args = parser.parse_args(argv)
    paths = gift.Paths()
    if not (sys.stdin.isatty() and sys.stdout.isatty()):
        sys.exit("fugleramme-gift needs an interactive terminal. Over ssh, use `ssh -t`.")
    io = Terminal()
    if args.preview:
        preview(io, paths, args.preview)
        return
    if gift.bundled(paths) and not paths.birdnet_config.exists():
        sys.exit(f"no {paths.birdnet_config}: run run.sh first")
    print("Stopping the frame service. sudo may ask for your password.")
    if not service("stop"):
        sys.exit(f"Could not stop {gift.UNIT}.")
    signal.signal(signal.SIGHUP, _hang_up)
    signal.signal(signal.SIGTERM, _hang_up)
    wrapped = False
    try:
        panel = init_panel()
        if panel is None:
            sys.exit("No Inky panel found. It is what keeps the picture without power.")
        frame = Frame.here(paths, panel)
        nmcli = Nmcli(DEFAULT_PORT)
        warning = ""
        if not frame.own:
            warning = (
                "Note: this frame doesn't listen for birds itself. It shows birds from "
                f"{_reads(frame.settings)}, so there is no location to set and no detections "
                "to delete."
            )
        intro = (
            "Draws a gift picture on the panel and prepares the frame for its new owner. "
            "Nothing is changed until you wrap at the end. Press Ctrl-C to quit."
        )

        def confirm(g: Gift) -> Reset | None:
            heard = gift.heard(_source(frame.settings)) if frame.own else None
            return reset(io, g, frame, heard, nmcli.saved(), gift.zone_here())

        q = Questions(io, frame)
        g = ask(q, "Wrap this frame as a gift", intro, warning)
        done = review(io, q, g, _on_panel(io, frame, panel), confirm)
        if done is None:
            io.say("Nothing changed.")
        else:
            wrapped = wrap(io, frame, *done, nmcli)
    except (KeyboardInterrupt, EOFError):
        print("\nNothing changed.")
    finally:
        # Left stopped only by a wrap; a reboot starts it in any case.
        if not wrapped and not service("start"):
            print(f"Couldn't start {gift.UNIT}. Reboot the frame to start it.")
