"""The admin page: everything at `/admin` that is not HTTP.

The markup is in `templates/`, a template per tab; this works out what each
one shows. A function per tab renders it, so none of it needs a server to test.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup
from PIL.ImageFont import FreeTypeFont

from .. import __version__, birdweather, modes, updates
from ..api import probe
from ..config import (
    BIRDNET_PORT,
    DEFAULT_PANEL_SIZE,
    DOCS_URL,
    NEW_ISSUE_URL,
    PANEL_SIZES,
    SAME_AS_INKY,
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
from . import LOGIN, LOGOUT, TEMPLATES_DIR, hostinfo

CHECKBOXES = "checkboxes"  # hidden field naming the checkboxes a form carries

# No stored password reaches the page; posting this back unchanged means "leave it alone".
PASSWORD_SET = "•" * 8

# The install writes the sudo rule the Wi-Fi setup needs, and is safe to run again.
INSTALL_COMMAND = (
    "curl -fsSL https://raw.githubusercontent.com/arnegiacomo/fugleramme/main/install.sh | bash"
)

_LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")

_ASPECT = {0: "(landscape)", 90: "(portrait)"}

ISSUE_TEMPLATE = "artwork_request.yml"
MAX_URL = 8000  # GitHub refuses longer; past it the form opens empty

# Style and plate names that don't title-case into something readable.
_NAMES = {
    "vonwright": "von Wright",
}


def _flags(**on: bool) -> Markup:
    """Boolean attributes, ` checked disabled`, for the ones that are on."""
    return Markup("".join(f" {name}" for name, value in on.items() if value))


def _duration(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _ago(dt: datetime) -> str:
    return f"{_duration(int((datetime.now(UTC) - dt).total_seconds()))} ago"


def _clock(dt: datetime) -> str:
    local = dt.astimezone()
    today = local.date() == datetime.now().astimezone().date()
    return local.strftime("%H:%M" if today else "%-d %b %H:%M")


# StrictUndefined: a value a template names and nobody passed is an error, not a blank.
_ENV = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=True,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)
_ENV.filters.update(ago=_ago, clock=_clock)
_ENV.globals.update(
    flags=_flags,
    version=__version__,
    BUG_URL=f"{NEW_ISSUE_URL}?{urlencode({'template': 'bug_report.yml', 'version': f'v{__version__}'})}",
    RELEASE_URL=f"https://github.com/arnegiacomo/fugleramme/releases/tag/v{__version__}",
    BIRDNET_GO=BIRDNET_GO,
    BIRDWEATHER=BIRDWEATHER,
    BIRDWEATHER_SITE=BIRDWEATHER_SITE,
    CHECKBOXES=CHECKBOXES,
    CONTAINER_COMMAND=updates.CONTAINER_COMMAND,
    DEFAULT_LIMIT=DEFAULT_LIMIT,
    DOCS_URL=DOCS_URL,
    INSTALL_COMMAND=INSTALL_COMMAND,
    KEY_LIMIT=KEY_LIMIT,
    LIMIT_CEILING=LIMIT_CEILING,
    LOGIN=LOGIN,
    LOGOUT=LOGOUT,
    MARGIN_CEILING=MARGIN_CEILING,
    MOST_STATIONS=MOST_STATIONS,
    PASSWORD_SET=PASSWORD_SET,
)


def _render(template: str, **values: Any) -> Markup:
    return Markup(_ENV.get_template(template).render(**values))


# rows.html's macros, for the rows the server also sends on their own.
_ROWS: Any = _ENV.get_template("rows.html").module


def form_changes(form: dict[str, list[str]]) -> dict:
    """Admin form to settings overrides. Unchecked checkboxes and disabled
    fields are both absent from a post, so a form declares its own checkboxes
    and everything else missing keeps its saved value. Without that declaration
    the System form, which has no `show_names`, would read as switching names
    off. settings._coerce validates the rest."""
    changes: dict[str, str | bool | int] = {k: v[0] for k, v in form.items() if k != CHECKBOXES}
    if "detector_station" in form:  # a row per station
        changes["detector_station"] = ", ".join(form["detector_station"])
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


def _kind_name(kind: str) -> str:
    return KINDS[kind].removesuffix(" station(s)")


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


def issue_url(rows: list[tuple[str, int]]) -> str:
    """The Missing bird issue with `rows` filled in, while GitHub takes a URL
    that long. Past it the issue opens empty; Copy always has the whole list."""
    filled = request_url(missing_text(rows))
    return filled if len(filled) <= MAX_URL else request_url()


def _display_name(name: str) -> str:
    return _NAMES.get(name, name.replace("-", " ").title())


_OUTAGES = {
    "auth": f"detector {NEEDS_PASSWORD}",
    "missing": "no such station",
    "unset": NO_STATION,
}


def _outage(state: str) -> str:
    """What to show where a bird would have been. A detector that answered says
    what it wants; anything else reads as unreachable, which is what the page saw."""
    return _OUTAGES.get(state, "detector unreachable")


def _detector(state: str, version: str, reading: bool, names_failure: str = "") -> tuple[str, str]:
    """The configured BirdNET-Go's state, and the version it reports, as (tone, words).

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
            return "bad", f"running · {NEEDS_PASSWORD}"
        return "bad", "unreachable"
    running = "running" + (f" · {version}" if version else "")
    if names_failure == NEEDS_PASSWORD:  # the settings only: birds yes, names no
        return "warn", f"{running} · {NEEDS_PASSWORD}"
    return "ok", running


# A probe's answer in the test's own words, and the status row it leaves behind.
# The row comes from `_detector`, so the test and a page load cannot describe one
# detector differently. "auth" leads with nothing: the detail is the whole answer.
_ANSWERS = {
    "ok": ("connected", _detector("ok", "", reading=True)),
    "auth": ("", _detector("auth", "", reading=False)),
    "names": ("connected", _detector("ok", "", reading=True, names_failure=NEEDS_PASSWORD)),
    "unreachable": ("unreachable", _detector("down", "", reading=False)),
}


def _station(page: str, about: dict[str, Any] | None) -> dict[str, Any]:
    """One BirdWeather station's line: its name, #ID and page, and when it last
    heard anything, bird or not - or that BirdWeather does not have it."""
    found = about is not None
    latest = (about or {}).get("latestDetectionAt")
    return {
        "id": station_id(page),
        "page": page,
        "missing": not found,
        "name": str((about or {}).get("name") or ""),
        "heard": datetime.fromisoformat(latest) if latest else None,
    }


def _stations(
    url: str, state: str, about: dict[str, dict[str, Any] | None], reading: bool
) -> Markup:
    """The BirdWeather stations `url` lists, a line each. `state` and `about` are
    `hostinfo.stations`'; `reading` says whether the page's own reads came back,
    which they cannot while BirdWeather has none of the stations."""
    if state == "missing":
        return _ROWS.state("bad", "no such station")
    if state != "ok" or (any(about.values()) and not reading):
        return _ROWS.state("bad", "unreachable")
    return _ROWS.stations([_station(page, about[station_id(page)]) for page in station_pages(url)])


# `_ANSWERS`' leads for BirdWeather. Its row names the stations, so it is built per answer.
_STATION_LEADS = {"ok": "connected", "partial": "connected", "unreachable": "unreachable"}


def _status_row(settings: Settings, reading: bool, names_failure: str) -> tuple[str, Markup]:
    """The saved detector's state and its Detector row. BirdWeather with no
    station saved has nothing to ask, so it says so."""
    if settings.detector_kind != BIRDWEATHER:
        state, version = hostinfo.detector(settings.detector_url)
        return state, _ROWS.state(*_detector(state, version, reading, names_failure))
    if not settings.detector_station:
        return "unset", _ROWS.state("bad", NO_STATION)
    state, about = hostinfo.stations(settings.detector_station)
    row = _stations(settings.detector_station, state, about, reading)
    return ("missing" if state == "ok" and not any(about.values()) else state), row


def _species_rows(
    species: list[tuple[str, str | None, str]], name_of: Namer
) -> list[tuple[str, str, str | None, str]]:
    """`subjects` as rows.species lists them: the plate by its display name."""
    return [
        (name, name_of.inline(name), None if source is None else _display_name(source), url)
        for name, source, url in species
    ]


def species_html(species: list[tuple[str, str | None, str]], name_of: Namer) -> str:
    return str(_ROWS.species(_species_rows(species, name_of)))


def _language_options(
    languages: list[tuple[str, str]], selected: str, optional: bool = False
) -> list[tuple[str, str]]:
    """A language dropdown, BirdNET-Go's offering in preference order. A saved code
    it is not serving stays selectable, so an outage cannot quietly reset the
    frame's language on the next Save."""
    items = [(NONE, "None")] if optional else []
    items += [(code, name) for code, name in languages if code != NONE]
    if selected in dict(items):
        return items
    shown = STATION_NAME if selected == STATION else selected
    return [*items, (selected, f"{shown} (unavailable)")]


# A script is judged on a date in it: the CJK subset holds every date, but not "日本語".
_SAMPLE_DAY = datetime(2026, 10, 6, 12, tzinfo=UTC)


def _unshaped(settings: Settings) -> str:
    """The chosen languages waiting on raqm, as the shaping note names them, or ""."""
    station = station_locale()
    waiting = [
        english_name(station if code == STATION else code)
        for code in (settings.primary_language, settings.secondary_language)
        if code not in (SCIENTIFIC, NONE)
        and needs_shaping(Namer(code, NONE, {}, (), station).date(_SAMPLE_DAY))
    ]
    return " or ".join(waiting)


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


def _typed(page: str) -> str:
    """A saved station as its row shows it: BirdWeather's own by its ID alone,
    which a page that long would scroll out of the input. Saving reads it back."""
    found = station_id(page)
    return found if page == f"{BIRDWEATHER_SITE}/stations/{found}" else page


def login_page(error: str = "") -> str:
    """The door (#52). Rendered by the frame, styled like the admin behind it -
    the browser's own credential prompt is nobody's idea of this product."""
    return _render("login.html", error=error)


def birdnet_link(url: str, kind: str = BIRDNET_GO, public_url: str = "") -> tuple[str, int | None]:
    """The nav link to the detector's own pages: (address, port to substitute
    this page's host on). A loopback address is loopback from the Pi only, so a
    remote browser cannot follow it; anything else, a BirdWeather station's page
    included, is reached exactly as configured. No station yet is BirdWeather's
    own front page, and several are the first's (`_nav_stations` lists them).
    A public address, when one is set, is reached exactly as configured."""
    if kind == BIRDWEATHER:
        return (station_pages(url) or [BIRDWEATHER_SITE])[0], None
    if public_url:
        return public_url, None
    parsed = urlparse(url)
    if parsed.hostname in _LOOPBACK:
        return url, parsed.port or BIRDNET_PORT
    return url, None


def _nav_stations(settings: Settings) -> list[tuple[str, str]]:
    """Each station's page and name, for the nav to list while there are
    several, which have no page between them. Otherwise none: the nav's one
    link is `birdnet_link`'s."""
    pages = (
        station_pages(settings.detector_station) if settings.detector_kind == BIRDWEATHER else []
    )
    if len(pages) < 2:
        return []
    about = hostinfo.stations(settings.detector_station)[1]
    return [
        (page, str((about.get(station_id(page)) or {}).get("name") or station_id(page)))
        for page in pages
    ]


def connection(form: dict[str, list[str]], settings: Settings) -> dict:
    """The connection test, over the values the form is holding rather than the
    saved ones - validated and placeholder-resolved exactly as Save would.

    A working station's row is `hostinfo`'s, which is what a page load shows;
    the script only puts it up for the saved values, and those are the ones
    `hostinfo` holds."""
    changes = form_changes(form)
    wrong = refused(changes)
    if wrong:
        short, said = refusal(wrong, str(changes.get("detector_station", "")))
        return {"state": "refused", "text": said, "status": str(_ROWS.state("bad", short))}
    tried = merged(settings, **changes)
    kind, url = tried.detector_kind, tried.detector_address
    if not url:
        row = _ROWS.state("bad", NO_STATION)
        return {"state": "unset", "text": "no station entered", "status": str(row)}
    state, detail = probe(url, tried.detector_username, tried.detector_password, kind)
    if kind == BIRDWEATHER:
        lead = _STATION_LEADS.get(state, "")
        row = _stations(url, *hostinfo.stations(url), reading=state != "unreachable")
    else:
        lead, answer = _ANSWERS[state]
        row = _ROWS.state(*answer)
    return {
        "state": state,
        "text": " · ".join(part for part in (lead, detail) if part),
        "status": str(row),
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


def _lookbacks(settings: Settings) -> list[tuple[float, str]]:
    # A hand-edited non-preset value stays selectable so Save doesn't drop it.
    labels = dict(LOOKBACK_OPTIONS)
    labels.setdefault(settings.lookback_hours, f"{settings.lookback_hours} hours")
    return [(hours, labels[hours]) for hours in sorted(labels, key=lookback_order)]


def _refreshes(settings: Settings) -> list[tuple[int, str]]:
    labels = dict(REFRESH_OPTIONS)
    labels.setdefault(settings.refresh_minutes, f"At most every {settings.refresh_minutes} minutes")
    return sorted(labels.items())


def _attached(
    settings: Settings, panel_size: tuple[int, int], detected: bool
) -> tuple[int, int] | None:
    """The panel the page is laid out for: an Inky, else the external one, else none."""
    return panel_size if detected or settings.external_panel else None


def display_tab(
    ctx: modes.Context,
    settings: Settings,
    languages: list[tuple[str, str]],
    names_failure: str,
    face_notes: dict[str, dict[str, str]],
) -> Markup:
    """The Display tab. `names_failure` says why the language menu holds nothing
    but the scientific name; `face_notes` is `_face_notes`'."""
    limited = settings.species_limit != NO_LIMIT
    count = settings.species_limit if limited else DEFAULT_LIMIT
    said = face_notes.get(settings.label_font, {})
    return _render(
        "display.html",
        settings=settings,
        modes=[(key, mode.label) for key, mode in MODES.items()],
        windowed=modes.mode_of(settings.mode).windowed,
        lookbacks=_lookbacks(settings),
        limited=limited,
        count=count,
        capped=settings.show_names and settings.name_key and not (limited and count <= KEY_LIMIT),
        rankings=list(RANKINGS.items()),
        layouts=[(key, layout.label) for key, layout in LAYOUTS.items()],
        layout_hint="\n\n".join(f"{layout.label}: {layout.blurb}" for layout in LAYOUTS.values()),
        names_failure=names_failure,
        languages=_language_options(languages, settings.primary_language),
        second_languages=_language_options(languages, settings.secondary_language, optional=True),
        unshaped=_unshaped(settings),
        face_note=said.get(settings.primary_language) or said.get(settings.secondary_language, ""),
        fonts=[(key, font[0]) for key, font in FONTS.items()],
        label_sizes=[(key, size[0]) for key, size in LABEL_SIZES.items()],
        styles=[(style, _display_name(style)) for style in available_styles(ctx.images_dir)],
        style=ctx.style,
    )


def frame_tab(settings: Settings, panel_size: tuple[int, int], detected: bool) -> Markup:
    """The Frame tab."""
    attached = _attached(settings, panel_size, detected)
    sizes = {size: '{}" ({}×{})'.format(size, *PANEL_SIZES[size]) for size in PANEL_SIZES}
    if detected:
        sizes = {SAME_AS_INKY: "Same as this frame's Inky", **sizes}
    picked = (
        settings.external_panel_size
        if detected
        else settings.external_panel_size or DEFAULT_PANEL_SIZE
    )
    resolutions = [
        (r, "{} ({}×{})".format(r, *replace(settings, web_resolution=r).web_size(attached)))
        for r in WEB_HEIGHTS
    ]
    return _render(
        "frame.html",
        settings=settings,
        panel=attached is not None,
        detected=detected,
        edges=list(zip(("top", "right", "bottom", "left"), settings.glass_margins(), strict=True)),
        panel_sizes=list(sizes.items()),
        panel_size=picked,
        rotations=[(r, f"{r}° {_ASPECT[r % 180]}") for r in ROTATIONS],
        refreshes=_refreshes(settings),
        resolutions=resolutions,
        aspects=[(aspect, aspect) for aspect in WEB_ASPECTS],
    )


def detector_tab(
    settings: Settings,
    row: Markup,
    outage: str,
    latest: tuple[str, datetime] | None,
    without: list[tuple[str, int]],
    refused: str = "",
    stations: str = "",
) -> Markup:
    """The Detector tab. `row` is `_status_row`'s, `outage` what the page says in
    place of the birds when the detector could not be read, `latest` the last
    bird heard and when, and `without` `missing`'s. `refused` is the type a save
    was just refused for and `stations` what it held: the form comes back on that
    type, with the note under its address."""
    chosen = refused if refused in DETECTOR_KINDS else settings.detector_kind
    return _render(
        "detector.html",
        settings=settings,
        name=_kind_name(settings.detector_kind),
        row=row,
        outage=outage,
        latest=latest,
        missing=without,
        missing_text=missing_text(without),
        issue_url=issue_url(without),
        chosen=chosen,
        refusal=refusal(refused, stations)[1] if refused in DETECTOR_KINDS else "",
        kinds=list(KINDS.items()),
        station_rows=[_typed(page) for page in station_pages(settings.detector_station)] or [""],
    )


def security_tab(settings: Settings) -> Markup:
    """The Security tab: the switch, the password and what the two add up to."""
    return _render("security.html", settings=settings)


def system_tab(
    settings: Settings, status: Status, panel_size: tuple[int, int], detected: bool, data_dir: Path
) -> Markup:
    """The System tab: updates, the Wi-Fi setup, the machine and the theme."""
    online, iface = hostinfo.online()
    container = updates.in_container()
    return _render(
        "system.html",
        settings=settings,
        status=status,
        container=container,
        pi=updates.can_reboot(),
        panel_size=panel_size,
        detected=detected,
        host=hostinfo.lan_address(container),
        online=online,
        iface=iface,
        disk=hostinfo.disk_free(data_dir),
        web_size=settings.web_size(_attached(settings, panel_size, detected)),
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
        latest, rows, without = None, None, []
    detector_state, detector_row = _status_row(settings, rows is not None, names_failure)
    outage = "" if rows is not None else _outage(detector_state)
    heard = (ctx.namer.inline(latest.scientific_name), latest.detected_at) if latest else None
    birdnet_url, birdnet_port = birdnet_link(
        settings.detector_address, settings.detector_kind, settings.detector_public_url
    )
    return _render(
        "admin.html",
        settings=settings,
        detector_name=_kind_name(settings.detector_kind),
        nav_stations=_nav_stations(settings),
        species=None if rows is None else _species_rows(rows, ctx.namer),
        outage=outage,
        display=display_tab(ctx, settings, languages, names_failure, face_notes),
        frame=frame_tab(settings, panel_size, detected),
        detector=detector_tab(settings, detector_row, outage, heard, without, refused, stations),
        security=security_tab(settings),
        system=system_tab(settings, status, panel_size, detected, names_dir),
        config={
            "birdnetUrl": birdnet_url,
            "birdnetPort": birdnet_port,
            "kind": settings.detector_kind,
            "version": __version__,
            "passwordSet": PASSWORD_SET,
            "windowedModes": [k for k, m in MODES.items() if m.windowed],
            "keyLimit": KEY_LIMIT,
            "webHeights": WEB_HEIGHTS,  # so the Resolution labels follow the form
            # The Inky's, landscape as oriented() reads it; the external panel's
            # size comes from panelSizes instead.
            "panel": [max(panel_size), min(panel_size)],
            "detected": detected,
            "panelSizes": PANEL_SIZES,  # so the page follows the external panel size picked
            "faceNotes": face_notes,  # so the Typeface warning follows the form
        },
    )
