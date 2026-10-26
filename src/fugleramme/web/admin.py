"""The admin page: everything at `/admin` that is not HTTP.

Markup, style and behaviour live in `static/admin.{html,css,js}`; this fills the
template's slots. Pure string builders, so none of it needs a server to test.
"""

from __future__ import annotations

import html
import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from string import Template
from typing import Any
from urllib.parse import urlencode, urlparse

from PIL.ImageFont import FreeTypeFont

from .. import __version__, birdweather, modes, updates
from ..api import probe
from ..config import (
    BIRDNET_PORT,
    DOCS_URL,
    NEW_ISSUE_URL,
    WEB_ASPECTS,
    WEB_HEIGHTS,
)
from ..languages import (
    NONE,
    SCIENTIFIC,
    STATION,
    STATION_NAME,
    Namer,
    catalog,
    catalog_failure,
    english_name,
    ordered,
    station_locale,
)
from ..modes import MODES
from ..names import available_styles, image_for, normalize, origin_of, source_of
from ..render.collage import KEY_LIMIT, NO_LIMIT, RANKINGS
from ..render.fonts import FONTS, LABEL_SIZES, face, load, needs_shaping
from ..render.packing import LAYOUTS
from ..settings import (
    DEFAULT_LIMIT,
    LIMIT_CEILING,
    LOOKBACK_OPTIONS,
    MARGIN_CEILING,
    REFRESH_OPTIONS,
    ROTATIONS,
    Settings,
    lookback_order,
    merged,
)
from ..source import (
    BIRDNET_GO,
    BIRDWEATHER,
    BIRDWEATHER_SITE,
    DETECTOR_KINDS,
    MOST_STATIONS,
    NEEDS_PASSWORD,
    Unavailable,
    station_fault,
    station_id,
    station_pages,
    with_scheme,
)
from ..status import Status
from ..taxa import common_of
from . import LOGIN, LOGOUT, STATIC_DIR, hostinfo

CHECKBOXES = "checkboxes"  # hidden field naming the checkboxes a form carries

# No stored password reaches the page; posting this back unchanged means "leave it alone".
PASSWORD_SET = "\u2022" * 8

_LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")

_ASPECT = {0: "(landscape)", 90: "(portrait)"}

ISSUE_TEMPLATE = "artwork_request.yml"
MAX_URL = 8000  # GitHub refuses longer; past it the form opens empty

# Style and plate names that don't title-case into something readable.
_NAMES = {
    "vonwright": "von Wright",
}


def form_changes(form: dict[str, list[str]]) -> dict:
    """Admin form to settings overrides. Unchecked checkboxes and disabled
    fields are both absent from a post, so a form declares its own checkboxes
    and everything else missing keeps its saved value. Without that declaration
    the System form, which has no `show_names`, would read as switching names
    off. settings._coerce validates the rest."""
    changes: dict[str, str | bool | int] = {k: v[0] for k, v in form.items() if k != CHECKBOXES}
    if "detector_station" in form:  # a row per station
        changes["detector_station"] = ", ".join(form["detector_station"])
    # Each block declares its own boxes: a dimmed block posts neither.
    for field in " ".join(form.get(CHECKBOXES, [])).split():
        changes[field] = field in form
    if changes.pop("limit_mode", None) == "all":
        changes["species_limit"] = NO_LIMIT  # the box is disabled, so it posts nothing
    changes.pop("session_secret", None)  # the cookie key is minted, never posted
    for field in ("detector_password", "admin_password"):
        # Typing on the end of the placeholder would save the bullets, a lockout.
        if str(changes.get(field, "")).startswith(PASSWORD_SET):
            del changes[field]  # untouched, so the stored one stands
    return changes


# The Detector form's type, as the reader knows each one.
KINDS = {BIRDNET_GO: "BirdNET-Go", BIRDWEATHER: "BirdWeather station(s)"}


def _logo(kind: str) -> str:
    """The detector's own favicon. admin.js loads it and shows it once it has
    arrived, so one that cannot load leaves nothing."""
    return f'<img class="logo" data-kind="{kind}" alt="" referrerpolicy="no-referrer" hidden>'


NO_STATION = "no station saved"
_BIRDWEATHER_HOST = urlparse(BIRDWEATHER_SITE).hostname


def refusal(kind: str, stations: str) -> tuple[str, str]:
    """What the test and the form say about what a type's field cannot hold, as
    (Detector row, note), or ("", "") when it can: BirdNET-Go's address holding
    a station, or BirdWeather's `stations` anything `source.station_fault` names."""
    if kind == BIRDNET_GO:
        return (
            "a BirdWeather station",
            "That is a BirdWeather station. Choose BirdWeather as the type and enter it there.",
        )
    pages = station_pages(stations)
    fault = station_fault(pages)
    wrong = next((page for page in pages if not station_id(page)), "")
    notes = {
        "": "",
        "not a station": (
            f'"{wrong}" is not a BirdWeather station. Enter the station\'s ID, '
            f"or its page: {BIRDWEATHER_SITE}/stations/<ID>."
        ),
        "too many stations": f"The frame reads at most {MOST_STATIONS} stations.",
        "stations on two sites": "The stations must all be on the same site.",
    }
    return fault, notes[fault]


def refused(changes: dict) -> str:
    """The type whose address a save is refused for, or "". Each type has its own
    field, so only one typed into the wrong one is refused: a station's page or
    bare ID as BirdNET-Go's address, or anything `refusal` names as BirdWeather's.
    Settings would otherwise drop the station silently, or save it as a BirdNET-Go."""
    typed = str(changes.get("detector_url", "")).strip()
    url = with_scheme(typed)
    if typed.isdigit() or station_id(url) or urlparse(url).hostname == _BIRDWEATHER_HOST:
        return BIRDNET_GO
    if station_fault(station_pages(str(changes.get("detector_station", "")))):
        return BIRDWEATHER
    return ""


def subjects(ctx: modes.Context) -> list[tuple[str, str | None, str]]:
    """What the current mode's page is about, each with the plate its artwork
    was cut from - None when it has none to draw - and the plate's citation."""
    rows: list[tuple[str, str | None, str]] = []
    for name in modes.subjects(ctx):
        pick = image_for(name, ctx.images_dir, ctx.style, ctx.day)
        if not pick:
            rows.append((name, None, ""))
            continue
        # Unlisted (a hand-filled style keeps no manifest): name the style itself.
        rows.append((name, source_of(pick) or ctx.style, origin_of(pick)))
    return rows


def missing(ctx: modes.Context) -> list[tuple[str, int]]:
    """Every species the station has ever heard that this style cannot draw,
    with its detection count, most heard first."""
    keys = ctx.drawable()
    return [(name, n) for name, n in ctx.source.species_since(0) if normalize(name) not in keys]


def missing_text(rows: list[tuple[str, int]]) -> str:
    """One line per species, as the Missing bird issue's Species field takes them."""
    lines = []
    for name, count in rows:
        common = common_of(name)
        named = f"{name} ({common})" if common else name
        lines.append(f"{named} - {count} detection{'' if count == 1 else 's'}")
    return "\n".join(lines)


def request_url(species: str = "") -> str:
    """A new Missing bird issue, its Species field holding `species`."""
    query = {"template": ISSUE_TEMPLATE} | ({"species": species} if species else {})
    return f"{NEW_ISSUE_URL}?{urlencode(query)}"


def bug_url() -> str:
    query = {"template": "bug_report.yml", "version": f"v{__version__}"}
    return f"{NEW_ISSUE_URL}?{urlencode(query)}"


MISSING = "Birds your station has heard (all time) that have no artwork yet"


def missing_row(rows: list[tuple[str, int]]) -> str:
    """The Without art row: a count, a copy of the list, and the issue with it filled in."""
    if not rows:
        return "none"
    text = missing_text(rows)
    filled = request_url(text)
    url = filled if len(filled) <= MAX_URL else request_url()
    return (
        f"{len(rows)} bird{'' if len(rows) == 1 else 's'} "
        f'<button type="button" class="copy" data-copy="{html.escape(text)}">Copy</button> · '
        f'<a href="{html.escape(url)}" target="_blank" rel="noopener">Create GitHub issue</a>'
    )


def _display_name(name: str) -> str:
    return _NAMES.get(name, name.replace("-", " ").title())


def _options(values, selected, label=str) -> str:
    return "".join(
        f'<option value="{v}"{" selected" if v == selected else ""}>{label(v)}</option>'
        for v in values
    )


def _radios(field: str, options: list[tuple[str, str]], active: str) -> str:
    return "".join(
        f'<label class="src"><input type="radio" name="{field}" value="{value}"'
        f"{' checked' if value == active else ''}> {label}</label>"
        for value, label in options
    )


def _checkbox(field: str, label: str, checked: bool, disabled: bool = False) -> str:
    return (
        f'<label class="src"><input type="checkbox" name="{field}"'
        f"{' checked' if checked else ''}{' disabled' if disabled else ''}> {label}</label>"
    )


def _action(action: str, label: str) -> str:
    return (
        f'<form class="inline {action}" method="post" action="/admin">'
        f'<input type="hidden" name="action" value="{action}">'
        f'<button type="submit">{label}</button></form>'
    )


def _state(ok: bool, good: str, bad: str) -> str:
    return f'<span class="{"ok" if ok else "bad"}">{good if ok else bad}</span>'


def _fix(problem: str) -> str:
    """A problem and the tab that fixes it, worded the same wherever it turns up."""
    return (
        f'{html.escape(problem)}. See <a href="#detector" data-tab="detector">the Detector tab</a>.'
    )


_OUTAGES = {
    "auth": f"detector {NEEDS_PASSWORD}",
    "missing": "no such station",
    "unset": NO_STATION,
}


def _outage(state: str) -> str:
    """What to show where a bird would have been. A detector that answered says
    what it wants; anything else reads as unreachable, which is what the page saw."""
    return _OUTAGES.get(state, "detector unreachable")


def _detector(state: str, version: str, reading: bool, names_failure: str = "") -> str:
    """The configured BirdNET-Go's state, and the version it reports.

    `state` is `/health` asked without credentials, so under PrivateMode it is
    401 for every frame alike - the ones holding a working password included.
    Only `reading`, whether the page's own calls came back, tells those apart.
    Miss that and a frame with everything configured is told to fix it.

    A detector that answers and holds something back is not unreachable either,
    so the row says what it wants instead: a locale list refusing us is
    BirdNET-Go's settings behind authentication while the detections stay open.
    """
    if not reading:
        if state == "auth":
            return f'<span class="bad">running · {NEEDS_PASSWORD}</span>'
        return '<span class="bad">unreachable</span>'
    running = "running" + (f" · {version}" if version else "")
    if names_failure == NEEDS_PASSWORD:  # the settings only: birds yes, names no
        return f'<span class="warn">{running} · {NEEDS_PASSWORD}</span>'
    return f'<span class="ok">{running}</span>'


# A probe's answer in the test's own words, and the status row it leaves behind.
# The row comes from `_detector`, so the test and a page load cannot describe one
# detector differently. "auth" leads with nothing: the detail is the whole answer.
_ANSWERS = {
    "ok": ("connected", _detector("ok", "", reading=True)),
    "auth": ("", _detector("auth", "", reading=False)),
    "names": ("connected", _detector("ok", "", reading=True, names_failure=NEEDS_PASSWORD)),
    "unreachable": ("unreachable", _detector("down", "", reading=False)),
}


def _station(page: str, about: dict[str, Any] | None) -> str:
    """One BirdWeather station's line, worded like BirdNET-Go's: its logo, name
    and #ID, linked to its page, and when it last heard anything, bird or not,
    or that BirdWeather does not have it. A cell each, dots included, so the
    lines' columns line up; the logo in a cell of its own, since one that
    cannot load is hidden and would shift the rest."""
    id_ = f"#{html.escape(station_id(page))}"
    if about is None:
        tone, name, heard = "bad", "", "no such station"
    else:
        latest = about.get("latestDetectionAt")
        tone, name = "ok", html.escape(str(about.get("name") or ""))
        id_ = f'<a href="{html.escape(page, quote=True)}">{id_}</a>'
        heard = f"latest detection {_stamp(datetime.fromisoformat(latest))}" if latest else ""
    cells = (name, "·" if name else "", id_, "·", heard or "nothing heard yet")
    return f"<span>{_logo(BIRDWEATHER)}</span>" + "".join(
        f'<span class="{tone}">{cell}</span>' for cell in cells
    )


def _stations(url: str, state: str, about: dict[str, dict[str, Any] | None], reading: bool) -> str:
    """The BirdWeather stations `url` lists, a line each. `state` and `about` are
    `hostinfo.stations`'; `reading` says whether the page's own reads came back,
    which they cannot while BirdWeather has none of the stations."""
    if state == "missing":
        return '<span class="bad">no such station</span>'
    if state != "ok" or (any(about.values()) and not reading):
        return '<span class="bad">unreachable</span>'
    lines = "".join(_station(page, about[station_id(page)]) for page in station_pages(url))
    return f'<span class="stations">{lines}</span>'


# `_ANSWERS`' leads for BirdWeather. Its row names the stations, so it is built per answer.
_STATION_LEADS = {"ok": "connected", "partial": "connected", "unreachable": "unreachable"}


def _status_row(settings: Settings, reading: bool, names_failure: str) -> tuple[str, str]:
    """The saved detector's state and its Detector row. BirdWeather with no
    station saved has nothing to ask, so it says so."""
    if settings.detector_kind != BIRDWEATHER:
        state, version = hostinfo.detector(settings.detector_url)
        return state, _detector(state, version, reading, names_failure)
    if not settings.detector_station:
        return "unset", f'<span class="bad">{NO_STATION}</span>'
    state, about = hostinfo.stations(settings.detector_station)
    row = _stations(settings.detector_station, state, about, reading)
    return ("missing" if state == "ok" and not any(about.values()) else state), row


def _duration(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _ago(dt: datetime) -> str:
    return f"{_duration(int((datetime.now(UTC) - dt).total_seconds()))} ago"


def _stamp(dt: datetime) -> str:
    local = dt.astimezone()
    fmt = "%H:%M" if local.date() == datetime.now().astimezone().date() else "%-d %b %H:%M"
    return f'<time title="{_ago(dt)}">{local.strftime(fmt)}</time>'


def _species_li(scientific: str, label: str, source: str | None, url: str) -> str:
    # Marks species counted in the window but omitted from the collage (#9); else
    # names the plate the artwork was cut from, per the style's manifest.
    # admin.js adds the href: only the browser knows BirdNET-Go's address.
    name = f'<a data-species="{html.escape(scientific)}" target="_blank" rel="noopener">{label}</a>'
    if source is None:
        return f'<li class="noart">{name} <small>no art</small></li>'
    plate = _display_name(source)
    if url:
        plate = f'<a href="{html.escape(url)}" target="_blank" rel="noopener">{plate}</a>'
    return f"<li>{name} <small>{plate}</small></li>"


def species_html(species: list[tuple[str, str | None, str]], name_of: Namer) -> str:
    return (
        "".join(
            _species_li(name, name_of.inline(name), source, url) for name, source, url in species
        )
        or '<li class="empty">none yet</li>'
    )


def _language_select(
    field: str, languages: list[tuple[str, str]], selected: str, optional: bool = False
) -> str:
    """A language dropdown, BirdNET-Go's offering in preference order. A saved code
    it is not serving stays selectable, so an outage cannot quietly reset the
    frame's language on the next Save."""
    items = [(NONE, "None")] if optional else []
    items += [(code, name) for code, name in languages if code != NONE]
    if selected not in dict(items):
        shown = STATION_NAME if selected == STATION else selected
        items.append((selected, f"{shown} (unavailable)"))
    labels = dict(items)
    codes = [code for code, _ in items]
    return f'<select name="{field}">{_options(codes, selected, labels.get)}</select>'


def _update(status: Status) -> str:
    # `requested` counts as installing: the loop only picks it up a tick later.
    if status.updating or status.update_requested:
        # A phase with no percent leaves the bar valueless, which renders indeterminate.
        label, value = status.update_phase or "installing…", ""
        if status.update_percent is not None:
            label, value = f"{label} {status.update_percent}%", f' value="{status.update_percent}"'
        return f'<span id="phase">{label}</span><progress id="bar" max="100"{value}></progress>'
    if status.update_error:
        return f'<span class="bad">{status.update_error}</span>{_action("check", "Retry")}'
    if status.update_available:
        # The command stands in for the button: the image is the host's to replace.
        install = (
            f'·<pre class="cmd">{html.escape(updates.CONTAINER_COMMAND)}</pre>'
            if updates.in_container()
            else _action("update", "Install")
        )
        return f'<span class="warn">{status.update_available} available</span>{install}'
    return f'<span id="state">up to date</span>{_action("check", "Check")}'


def _reboot(status: Status) -> str:
    """The Reboot button beside when the frame started, on the Pi alone
    (`updates.can_reboot`)."""
    if not updates.can_reboot():
        return ""
    failed = (
        f'<span class="bad">{html.escape(status.reboot_error)}</span>'
        if status.reboot_error
        else ""
    )
    return f"{_action('reboot', 'Reboot')}{failed}"


def _auto_update(settings: Settings) -> str:
    """The auto-install toggle, shown disabled in a container: nothing in here can
    pull an image, and a switch that does nothing is worse than no switch."""
    if updates.in_container():
        label = "Install new releases automatically <small>· disabled in container mode</small>"
        return f'<div class="block off">{_checkbox("auto_update", label, False, True)}</div>'
    return (
        '<form class="block" method="post" action="/admin">'
        f'<input type="hidden" name="{CHECKBOXES}" value="auto_update">'
        f"{_checkbox('auto_update', 'Install new releases automatically', settings.auto_update)}"
        '<button type="submit">Save</button></form>'
    )


NAME_KEY = (
    "Number the birds and list their names beside or below them, like a poster. "
    f"Shows at most {KEY_LIMIT} birds, and the list's text shrinks to fit when there are many."
)


def _names_field(
    settings: Settings,
    languages: list[tuple[str, str]],
    failure: str,
    face_notes: dict[str, dict[str, str]],
) -> str:
    """The names block. `failure` says why the menu holds nothing but the
    scientific name, so a detector that will not serve its locale list reads as
    one to fix rather than as all the frame can do."""
    note = f'<p class="note bad">{_fix(f"No languages: {failure}")}</p>' if failure else ""
    said = face_notes.get(settings.label_font, {})
    face_note = said.get(settings.primary_language) or said.get(settings.secondary_language, "")
    return (
        f'<div class="field" id="names"><span>Labels</span>'
        f"{_checkbox('show_names', 'Display bird names', settings.show_names)}"
        f"{note}"
        f'<div class="sub" id="name-key"><input type="hidden" name="{CHECKBOXES}" value="name_key">'
        f"{_checkbox('name_key', f'<span>Numbered key {_hint(NAME_KEY)}</span>', settings.name_key)}</div>"
        f'<label class="sub"><small>Language</small>'
        f"{_language_select('primary_language', languages, settings.primary_language)}</label>"
        f'<label class="sub"><small>Second language (optional)</small>'
        f"{_language_select('secondary_language', languages, settings.secondary_language, optional=True)}</label>"
        f"{_shaping_note(settings)}"
        f'<label class="sub"><small>Typeface {_warning(face_note)}</small><select name="label_font">'
        f"{_options(FONTS, settings.label_font, lambda k: FONTS[k][0])}</select></label>"
        f'<label class="sub"><small>Text size</small><select name="label_size">'
        f"{_options(LABEL_SIZES, settings.label_size, lambda k: LABEL_SIZES[k][0])}</select></label>"
        f"</div>"
    )


# A script is judged on a date in it: the CJK subset holds every date, but not "日本語".
_SAMPLE_DAY = datetime(2026, 10, 6, 12, tzinfo=UTC)


def _shaping_note(settings: Settings) -> str:
    """Said while a chosen language waits on raqm, which an update cannot install."""
    station = station_locale()
    waiting = [
        english_name(station if code == STATION else code)
        for code in (settings.primary_language, settings.secondary_language)
        if code not in (SCIENTIFIC, NONE)
        and needs_shaping(Namer(code, NONE, {}, (), station).date(_SAMPLE_DAY))
    ]
    if not waiting:
        return ""
    return (
        f'<p class="note warn">This Pi can\'t draw {html.escape(" or ".join(waiting))} yet. '
        'Run <code class="cmd">sudo apt install libfribidi0</code> and reboot.</p>'
    )


def _face_notes(codes: set[str]) -> dict[str, dict[str, str]]:
    """Per typeface, the Typeface warning for each of `codes` it leaves to a
    fallback face."""
    station = station_locale()
    languages = {code: english_name(station if code == STATION else code) for code in codes}
    samples = {code: Namer(code, NONE, {}, (), station).date(_SAMPLE_DAY) for code in codes}
    typefaces = {key: load(key, 20) for key in FONTS}
    set_in = {
        key: {code: name for code, sample in samples.items() if (name := _fallback(sample, font))}
        for key, font in typefaces.items()
    }
    return {
        key: {
            code: f"{FONTS[key][0]} doesn't support {languages[code]} - using {name} instead."
            for code, name in fallbacks.items()
        }
        for key, fallbacks in set_in.items()
    }


def _fallback(sample: str, font: FreeTypeFont) -> str:
    """The fallback face's name for a line `font` cannot set, or ""."""
    used = face(sample, font)
    return "" if used is font else str(used.getname()[0])


def _text_field(field: str, label: str, value: str, kind: str = "text", hint: str = "") -> str:
    return (
        f"<label><span>{label}{f' <small>{hint}</small>' if hint else ''}</span>"
        f'<input type="{kind}" name="{field}" value="{html.escape(value, quote=True)}"></label>'
    )


def _shown(field: str, kind: str, shown: bool) -> str:
    """A `_text_field` belonging to one type, hidden and disabled while the other
    is chosen: it posts nothing, so a save leaves its stored value alone."""
    field = field.replace("<label>", f'<label data-kind="{kind}"{"" if shown else " hidden"}>', 1)
    return field if shown else field.replace("<input ", "<input disabled ", 1)


def _stations_field(settings: Settings, shown: bool) -> str:
    """BirdWeather's stations, a row each with an × to remove it, a button
    adding one up to `MOST_STATIONS`, and a dialog listing the stations nearest
    a place (admin.js). With none saved, one empty row. Text inputs, since a
    bare ID is no URL. The search posts nothing: its field has no name."""
    off = "" if shown else " disabled"
    rows = "".join(
        f'<div class="station"><input type="text" name="detector_station"'
        f' value="{html.escape(_typed(page), quote=True)}"{off}>'
        '<button type="button" class="remove" aria-label="Remove station">×</button></div>'
        for page in station_pages(settings.detector_station) or [""]
    )
    return (
        f'<div class="field stations" data-kind="{BIRDWEATHER}" data-most="{MOST_STATIONS}"'
        f"{'' if shown else ' hidden'}><span>Stations <small>(ID or address)</small></span>"
        f'{rows}<button type="button" class="add">+ Add station</button>'
        '<button type="button" class="find">Find stations…</button>'
        '<dialog class="near"><header><strong>Find stations</strong>'
        '<button type="button" class="close" aria-label="Close">×</button></header>'
        '<input type="search" placeholder="Type a place" aria-label="Place" autofocus>'
        '<ul class="places"></ul><p class="note"></p><ul class="found"></ul>'
        f'<a href="{BIRDWEATHER_SITE}" target="_blank" rel="noopener">'
        "Browse BirdWeather's map ↗</a></dialog></div>"
    )


def _typed(page: str) -> str:
    """A saved station as its row shows it: BirdWeather's own by its ID alone,
    which a page that long would scroll out of the input. Saving reads it back."""
    found = station_id(page)
    return found if page == f"{BIRDWEATHER_SITE}/stations/{found}" else page


def _detector_field(settings: Settings, refused: str, stations: str) -> str:
    """Which kind of detector the frame reads, and each kind's own fields:
    BirdNET-Go's address and password, BirdWeather's stations. Only the chosen
    kind's are shown; admin.js swaps them as the type changes. `refused` is the
    type a save was just refused for and `stations` what it held: the form
    comes back on that type, with the note under its address, since that is
    the field to fix.

    A password only: the username BirdNET-Go's API insists on is a fixed client
    id (`api.CLIENT_ID`). An install that changed `security.basicauth.clientid`
    sets `detector_username` in settings.json instead.
    """
    chosen = refused if refused in DETECTOR_KINDS else settings.detector_kind
    birdnet = chosen == BIRDNET_GO
    said = refusal(refused, stations)[1] if refused in DETECTOR_KINDS else ""
    note = f'<p class="note bad">{html.escape(f"Not saved. {said}")}</p>' if said else ""
    kinds = [(kind, f"{_logo(kind)}{KINDS[kind]}") for kind in DETECTOR_KINDS]
    # Text, not a url input: the browser would refuse an address with no scheme,
    # which settings read as http://.
    address = _text_field("detector_url", "Address", settings.detector_url).replace(
        "<input ", '<input inputmode="url" ', 1
    )
    public = _text_field(
        "detector_public_url",
        "Public address",
        settings.detector_public_url,
        hint="(optional, for links to BirdNET-Go)",
    ).replace("<input ", '<input inputmode="url" ', 1)
    password = _text_field(
        "detector_password",
        "Password",
        PASSWORD_SET if settings.detector_password else "",
        "password",
        "(basic authentication)",
    )
    return (
        _radio_field("Type", "detector_kind", kinds, chosen)
        + _shown(address, BIRDNET_GO, birdnet)
        + (note if birdnet else "")
        + _shown(public, BIRDNET_GO, birdnet)
        + _stations_field(settings, not birdnet)
        + ("" if birdnet else note)
        + _shown(password, BIRDNET_GO, birdnet)
    )


def _access_note(settings: Settings) -> str:
    """What the switch and the password add up to, in the state they are in."""
    if not settings.require_sign_in and settings.admin_password:
        return '<p class="note warn">Sign-in is off, so anyone on the network can change the frame.</p>'
    if not settings.require_sign_in:
        return '<p class="note">Anyone on the network can change the frame.</p>'
    if not settings.admin_password:
        return '<p class="note warn">No password saved, so the admin is still open.</p>'
    return '<p class="note">Anyone can still view the kiosk - password used only by the admin page.</p>'


# Said where the password is typed, because it is the only place the answer
# changes what someone types.
EXPOSED = (
    "If the frame can be reached from the internet, use a strong password "
    "that you use nowhere else."
)


# Keep short, the rest is in the docs
PROXY = (
    "A proxy hands every visitor to the frame the same address, so a stranger's "
    "wrong passwords could block you too. With this on, the frame tells visitors apart "
    "by the address the proxy passes on."
)


def _access_field(settings: Settings) -> str:
    """The door (#52): the switch, the password behind it, and where that leaves things."""
    field = _text_field(
        "admin_password",
        f"Admin password {_hint(EXPOSED)}",
        PASSWORD_SET if settings.admin_password else "",
        "password",
    )
    return (
        _checkbox("require_sign_in", "Require sign-in for the admin page", settings.require_sign_in)
        + field
        # Filled in by admin.js as it is typed; the stored password never reaches here.
        + '<p class="strength" id="strength" hidden><span></span><small></small></p>'
        + _access_note(settings)
        # The bubble hangs off a span of its own, as it does on a text field's label.
        + _checkbox(
            "behind_proxy",
            f"<span>The frame is behind a reverse proxy {_hint(PROXY)}</span>",
            settings.behind_proxy,
        )
    )


def _signout(settings: Settings) -> str:
    """Only worth offering where there is a session to end."""
    if not settings.admin_locked:
        return ""
    # The class keeps admin.js out: signing out is not a save, so unsaved edits
    # still have to be warned about.
    return (
        f'<form class="inline signout" method="post" action="{LOGOUT}">'
        f'<button type="submit">Sign out</button></form>'
    )


def login_page(error: str = "") -> str:
    """The door (#52). Rendered by the frame, styled like the admin behind it -
    the browser's own credential prompt is nobody's idea of this product."""
    note = f'<p class="note bad">{html.escape(error)}</p>' if error else ""
    return Template((STATIC_DIR / "login.html").read_text()).substitute(
        version=__version__, action=LOGIN, error=note
    )


def birdnet_link(url: str, kind: str = BIRDNET_GO, public_url: str = "") -> tuple[str, int | None]:
    """The nav link to the detector's own pages: (address, port to substitute
    this page's host on). A loopback address is loopback from the Pi only, so a
    remote browser cannot follow it; anything else, a BirdWeather station's page
    included, is reached exactly as configured. No station yet is BirdWeather's
    own front page, and several are the first's (`_detector_link` lists them).
    A public address, when one is set, is reached exactly as configured."""
    if kind == BIRDWEATHER:
        return (station_pages(url) or [BIRDWEATHER_SITE])[0], None
    if public_url:
        return public_url, None
    parsed = urlparse(url)
    if parsed.hostname in _LOOPBACK:
        return url, parsed.port or BIRDNET_PORT
    return url, None


def _detector_link(settings: Settings) -> str:
    """The nav link to the detector's own pages, which admin.js points at
    `birdnet_link`. Several stations have no page between them, so the link
    opens a list of them instead."""
    name = KINDS[settings.detector_kind].removesuffix(" station(s)")
    pages = (
        station_pages(settings.detector_station) if settings.detector_kind == BIRDWEATHER else []
    )
    if len(pages) < 2:
        return f'<a id="birdnet" href="#" title="detection &amp; stats">{name}</a>'
    about = hostinfo.stations(settings.detector_station)[1]
    named = {
        page: (about.get(station_id(page)) or {}).get("name") or station_id(page) for page in pages
    }
    links = "".join(
        f'<a href="{html.escape(page, quote=True)}">{html.escape(str(name))}</a>'
        for page, name in named.items()
    )
    return (
        '<button type="button" class="link" popovertarget="stations" title="detection &amp; stats">'
        f'{name}</button><div id="stations" popover>{links}</div>'
    )


def connection(form: dict[str, list[str]], settings: Settings) -> dict:
    """The connection test, over the values the form is holding rather than the
    saved ones - validated and placeholder-resolved exactly as Save would.

    `status` is the row `_detector` would render for the same answer, so a test
    and a page load can never describe one detector differently. A working
    station's row is `hostinfo`'s, which is what a page load shows; JS only
    puts it up for the saved values, and those are the ones `hostinfo` holds."""
    changes = form_changes(form)
    wrong = refused(changes)
    if wrong:
        short, said = refusal(wrong, str(changes.get("detector_station", "")))
        return {"state": "refused", "text": said, "status": f'<span class="bad">{short}</span>'}
    tried = merged(settings, **changes)
    kind, url = tried.detector_kind, tried.detector_address
    if not url:
        row = f'<span class="bad">{NO_STATION}</span>'
        return {"state": "unset", "text": "no station entered", "status": row}
    state, detail = probe(url, tried.detector_username, tried.detector_password, kind)
    if kind == BIRDWEATHER:
        lead = _STATION_LEADS.get(state, "")
        row = _stations(url, *hostinfo.stations(url), reading=state != "unreachable")
    else:
        lead, row = _ANSWERS[state]
    return {
        "state": state,
        "text": " · ".join(part for part in (lead, detail) if part),
        "status": row,
    }


def stations_near(lat: float, lon: float) -> dict:
    """The station search's answer for a place: the nearest stations, or why
    there are none."""
    try:
        found = birdweather.nearest(lat, lon)
    except Unavailable as error:
        return {"stations": [], "text": str(error)}
    text = "" if found else f"No active stations within {birdweather.RADII_KM[-1]} km."
    return {"stations": [station._asdict() for station in found], "text": text}


def _lookbacks(settings: Settings) -> str:
    # A hand-edited non-preset value stays selectable so Save doesn't drop it.
    labels = dict(LOOKBACK_OPTIONS)
    labels.setdefault(settings.lookback_hours, f"{settings.lookback_hours} hours")
    return _options(sorted(labels, key=lookback_order), settings.lookback_hours, labels.get)


def _refreshes(settings: Settings) -> str:
    labels = dict(REFRESH_OPTIONS)
    labels.setdefault(settings.refresh_minutes, f"At most every {settings.refresh_minutes} minutes")
    return _options(sorted(labels), settings.refresh_minutes, labels.get)


def _hint(text: str) -> str:
    """The note beside a field label. A span, not a button: a <label> may hold
    only one labelable element and that is the select. admin.css draws the
    bubble from `aria-label`, so one attribute is both the text and the name."""
    note = html.escape(text, quote=True)
    return f'<span class="hint" tabindex="0" role="img" aria-label="{note}"></span>'


# Drawn rather than the warning sign character, which some systems set as a colour emoji.
_TRIANGLE = (
    '<svg viewBox="0 0 16 16" width="100%" height="100%" aria-hidden="true">'
    '<path d="M8 1 15.5 15H.5z" fill="currentColor"/>'
    '<path d="M8 6v4.5M8 12.6v.1" stroke="#fff" stroke-width="1.8" stroke-linecap="round"/></svg>'
)


def _warning(text: str) -> str:
    """The Typeface warning, hidden while empty. admin.js updates it as the form changes."""
    note = html.escape(text, quote=True)
    hidden = "" if text else " hidden"
    return (
        f'<span class="hint caution" id="face-note" tabindex="0" role="img" aria-label="{note}"'
        f"{hidden}>{_TRIANGLE}</span>"
    )


def _panel_hint(id: str, on: str, off: str, panel: bool) -> str:
    """A hint admin.js swaps between `on` and `off` as the form gains or loses a panel."""
    texts = {"on": on, "off": off}
    data = "".join(f' data-{k}="{html.escape(v, quote=True)}"' for k, v in texts.items())
    return _hint(on if panel else off).replace('class="hint"', f'class="hint" id="{id}"{data}', 1)


LOCK = "The web view takes the panel's shape and rotation."
LOCK_OFF = (
    f"{LOCK} Only available with an Inky Impression panel connected "
    "or the external e-ink panel enabled."
)


EDGES = "The same margin on every edge of the panel"


EXTERNAL = (
    "Serves the panel's page at /frame.e6 and /frame.png for external e-ink panels, "
    "and takes their button presses at /press. "
    'Without an Inky Impression, the page is laid out for a 13.3" panel. Anyone who can '
    "reach the frame can access these endpoints."
)


def _output_field(settings: Settings, detected: bool) -> str:
    # Only the external panel is a setting; the disabled rows post nothing, so declare none.
    inky = (
        "Always enabled as an Inky Impression panel is currently connected."
        if detected
        else "Only enabled when an Inky Impression panel is connected and detected."
    )
    return (
        '<div class="field" id="outputs"><span>Outputs</span>'
        + _checkbox(
            "inky_impression_enable",
            f"<span>Inky Impression panel {_hint(inky)}</span>",
            checked=detected,
            disabled=True,
        )
        + f'<input type="hidden" name="{CHECKBOXES}" value="external_panel">'
        + _checkbox(
            "external_panel",
            f"<span>External e-ink panel {_hint(EXTERNAL)}</span>",
            checked=settings.external_panel,
        )
        + _checkbox(
            "web_enable",
            f"<span>Browser kiosk {_hint('Web access is always enabled.')}</span>",
            checked=True,
            disabled=True,
        )
        + "</div>"
    )


def _slider(field: str, caption: str, value: int) -> str:
    return (
        f'<label><span><span class="caption">{caption}</span> <small>{value}%</small></span>'
        f'<input type="range" name="{field}" min="0" max="{MARGIN_CEILING}" step="1" value="{value}">'
        "</label>"
    )


def _margin_field(settings: Settings, panel: bool) -> str:
    """One margin, and one per edge of the glass (#184). The edges are always
    rendered: admin.js offers them while the form has a panel."""
    one = f'<div id="margin-one">{_slider("margin", "All edges", settings.margin)}</div>'
    edges = "".join(
        _slider(f"margin_{edge}", edge.title(), value)
        for edge, value in zip(
            ("top", "right", "bottom", "left"), settings.glass_margins(), strict=True
        )
    )
    lock = _checkbox(
        "margin_lock", f"<span>Uniform {_hint(EDGES)}</span>", settings.margin_lock, not panel
    )
    off = "" if panel else " disabled"
    dimmed = "" if panel else ' class="off"'
    return (
        f'<div id="margin-uniform"{dimmed}>'
        f'<input type="hidden" name="{CHECKBOXES}" value="margin_lock"{off}>{lock}</div>'
        f'<div id="margin-edges"{"" if panel else " hidden"}>{edges}</div>{one}'
    )


def _web_field(settings: Settings, panel: tuple[int, int] | None) -> str:
    """The web view's size and, once unlocked from the panel, its own shape (#147).
    The lock is always declared: admin.js enables it, declaration and all, while
    the form has a panel, so ticking the external panel offers it before a save."""
    off = "" if panel else " disabled"
    hint = _panel_hint("lock-hint", LOCK, LOCK_OFF, bool(panel))
    lock = _checkbox("web_lock", f"<span>Lock to panel {hint}</span>", settings.web_lock, not panel)
    resolutions = _options(
        WEB_HEIGHTS,
        settings.web_resolution,
        lambda r: "{} ({}×{})".format(r, *replace(settings, web_resolution=r).web_size(panel)),
    )
    return (
        f'<div class="field" id="web-view"><span>Resolution</span>'
        f'<select name="web_resolution" aria-label="Resolution">{resolutions}</select>'
        f'<div class="sub{"" if panel else " off"}" id="web-lock">'
        f'<input type="hidden" name="{CHECKBOXES}" value="web_lock"{off}>{lock}</div>'
        f'<div class="sub" id="web-shape">'
        f'<input type="hidden" name="{CHECKBOXES}" value="web_portrait">'
        f'<label><small>Aspect</small><select name="web_aspect">'
        f"{_options(WEB_ASPECTS, settings.web_aspect)}</select></label>"
        f"{_checkbox('web_portrait', 'Portrait', settings.web_portrait)}"
        f"</div></div>"
    )


def _species_field(settings: Settings) -> str:
    """How many species the collage shows, and which ones it keeps (#53).

    The count is disabled under "Show all", so it posts nothing - `form_changes`
    reads the radio instead.
    """
    limited = settings.species_limit != NO_LIMIT
    count = settings.species_limit if limited else DEFAULT_LIMIT
    capped = settings.show_names and settings.name_key and not (limited and count <= KEY_LIMIT)
    return (
        f'<div class="field" id="limit">'
        f"<span>Species on the page "
        f"{_hint(f'More than {DEFAULT_LIMIT} make the page very crowded')}</span>"
        f'<div class="src"><label class="src"><input type="radio" name="limit_mode"'
        f' value="some"{" checked" if limited else ""}> At most</label>'
        f'<input type="number" name="species_limit" min="1" max="{LIMIT_CEILING}"'
        f' value="{count}"{"" if limited else " disabled"}'
        f' aria-label="How many species"></div>'
        f'<label class="src"><input type="radio" name="limit_mode" value="all"'
        f"{'' if limited else ' checked'}> Show all</label>"
        f'<div class="sub" id="ranking"><small>Which ones to keep</small>'
        f"{_radios('ranking', list(RANKINGS.items()), settings.ranking)}</div>"
        f'<p class="note" id="key-cap"{"" if capped else " hidden"}>'
        f"The numbered key shows at most {KEY_LIMIT} birds.</p>"
        f"</div>"
    )


def _radio_field(
    label: str, name: str, options: list[tuple[str, str]], active: str, id: str = ""
) -> str:
    tag = f' id="{id}"' if id else ""
    return f'<div class="field"{tag}><span>{label}</span>{_radios(name, options, active)}</div>'


SPOTLIGHT = "Showcase the latest heard bird in the middle."


def _layout_field(settings: Settings) -> str:
    """How the collage packs its birds (#47), and whether one takes the middle
    (#185). Dimmed with the lookback for the modes that draw one bird."""
    hint = "\n\n".join(f"{layout.label}: {layout.blurb}" for layout in LAYOUTS.values())
    options = [(k, layout.label) for k, layout in LAYOUTS.items()]
    spotlight = _checkbox(
        "spotlight",
        f"<span>Spotlight mode {_hint(SPOTLIGHT)}</span>",
        settings.spotlight,
    )
    return (
        f'<div class="field" id="layout"><span>Layout {_hint(hint)}</span>'
        f"{_radios('layout', options, settings.layout)}"
        f'<input type="hidden" name="{CHECKBOXES}" value="spotlight">{spotlight}</div>'
    )


def page(
    ctx: modes.Context,
    settings: Settings,
    status: Status,
    panel_size: tuple[int, int],
    detected: bool,
    names_dir: Path,
    refused: str = "",
    stations: str = "",
) -> str:
    """The admin page. Everything about the frame comes off `ctx`, so the
    listing always describes the page the preview is rendering.

    Renders with the detector down on purpose: this is the page you reach for
    when it is, so the rows that need it say so rather than vanish. `refused` is
    the detector type a save was just refused for (`refused()`) and `stations`
    the stations it held, both carried across the redirect.
    """
    languages = ordered(catalog(names_dir))
    face_notes = _face_notes(
        {code for code, _ in languages} | {settings.primary_language, settings.secondary_language}
    )
    names_failure = catalog_failure()
    try:
        latest, rows, without = ctx.source.latest(), subjects(ctx), missing(ctx)
    except Unavailable:
        latest, rows, without = None, None, None
    detector_state, detector_row = _status_row(settings, rows is not None, names_failure)
    windowed = modes.mode_of(settings.mode).windowed
    online, iface = hostinfo.online()
    rendered = _stamp(status.rendered_at) if status.rendered_at else "not yet"
    if status.push_error:
        rendered += f" · panel push failing ({status.push_error})"
    # Without an Inky Impression connected, the external e-ink panel is the
    # one the page is laid out for.
    paneled = detected or settings.external_panel
    attached = panel_size if paneled else None
    w, h = settings.web_size(attached)
    glass = f"{panel_size[0]}×{panel_size[1]}"
    birdnet_url, birdnet_port = birdnet_link(
        settings.detector_address, settings.detector_kind, settings.detector_public_url
    )
    return Template((STATIC_DIR / "admin.html").read_text()).substitute(
        version=__version__,
        docs_url=DOCS_URL,
        bug_url=html.escape(bug_url()),
        checkboxes=CHECKBOXES,
        config=json.dumps(
            {
                "birdnetUrl": birdnet_url,
                "birdnetPort": birdnet_port,
                "kind": settings.detector_kind,
                "version": __version__,
                "passwordSet": PASSWORD_SET,
                "windowedModes": [k for k, m in MODES.items() if m.windowed],
                "keyLimit": KEY_LIMIT,
                "webHeights": WEB_HEIGHTS,  # so the Resolution labels follow the form
                # Landscape, as oriented() reads it: the Inky's while one is detected,
                # else the external panel's.
                "panel": [max(panel_size), min(panel_size)],
                "detected": detected,
                "faceNotes": face_notes,  # so the Typeface warning follows the form
            }
        ),
        mode_field=_radio_field(
            "Mode", "mode", [(k, m.label) for k, m in MODES.items()], settings.mode
        ),
        web_field=_web_field(settings, attached),
        rotations=_options(ROTATIONS, settings.rotation, lambda r: f"{r}° {_ASPECT[r % 180]}"),
        output_field=_output_field(settings, detected),
        margin_field=_margin_field(settings, paneled),
        refreshes=_refreshes(settings),
        lookback_off="" if windowed else ' class="off"',
        lookback_disabled="" if windowed else " disabled",
        lookbacks=_lookbacks(settings),
        limit_field=_species_field(settings),
        layout_field=_layout_field(settings),
        names_field=_names_field(settings, languages, names_failure, face_notes),
        style_field=_radio_field(
            "Artwork style",
            "style",
            [(s, _display_name(s)) for s in available_styles(ctx.images_dir)],
            ctx.style,
        ),
        species_count=len(rows) if rows is not None else 0,
        species_rows=(
            species_html(rows, ctx.namer)
            if rows is not None
            else f'<li class="problem">{_fix(_outage(detector_state))}</li>'
        ),
        update=_update(status),
        auto_update=_auto_update(settings),
        panel=f"detected · {glass}" if detected else "not detected",
        detector_name=KINDS[settings.detector_kind].removesuffix(" station(s)"),
        detector_link=_detector_link(settings),
        # Each station's line carries its own.
        detector_logo="" if settings.detector_kind == BIRDWEATHER else _logo(BIRDNET_GO),
        detector_label="Detector(s)" if settings.detector_kind == BIRDWEATHER else "Detector",
        birdnet=detector_row,
        detector_field=_detector_field(settings, refused, stations),
        access_field=_access_field(settings),
        signout=_signout(settings),
        host=hostinfo.lan_address(updates.in_container()),
        online=_state(online, "online", "offline") + (f" · {iface}" if iface else ""),
        disk=hostinfo.disk_free(names_dir),
        started=_stamp(status.started_at),
        reboot=_reboot(status),
        kiosk_size=f"{w}×{h}",
        rendered=rendered,
        latest=(
            f"{ctx.namer.inline(latest.scientific_name)} · {_stamp(latest.detected_at)}"
            if latest
            else ("none yet" if rows is not None else _outage(detector_state))
        ),
        missing_hint=_hint(MISSING),
        missing=missing_row(without) if without is not None else _outage(detector_state),
    )
