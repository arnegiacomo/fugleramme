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
from urllib.parse import urlparse

from .. import __version__, modes
from ..api import probe
from ..config import BIRDNET_PORT, DOCS_URL, WEB_HEIGHTS
from ..languages import NONE, Namer, catalog, ordered
from ..modes import MODES
from ..names import available_styles, image_for, source_of
from ..render.fonts import FONTS, LABEL_SIZES
from ..settings import LOOKBACK_OPTIONS, ROTATIONS, Settings, lookback_order, merged
from ..source import Unavailable
from ..status import Status
from . import STATIC_DIR, hostinfo

CHECKBOXES = "checkboxes"  # hidden field naming the checkboxes a form carries

# The stored detector password never reaches the page; posting this back
# unchanged means "leave it alone".
PASSWORD_SET = "\u2022" * 8

_LOOPBACK = ("127.0.0.1", "localhost", "::1", "0.0.0.0")

_ASPECT = {0: "(landscape)", 90: "(portrait)"}

# Style and plate names that don't title-case into something readable.
_NAMES = {"vonwright": "von Wright", "gould": "Gould"}

_UNREACHABLE = '<li class="empty">detector unreachable</li>'

# A probe's answer in the test's words, then in the status row's: the row is
# about the detector, not about the test just run.
_ANSWERS = {
    "ok": ("connected", "running"),
    "auth": ("authentication required", "authentication required"),
    "unreachable": ("unreachable", "unreachable"),
}


def form_changes(form: dict[str, list[str]]) -> dict:
    """Admin form to settings overrides. Unchecked checkboxes and disabled
    fields are both absent from a post, so a form declares its own checkboxes
    and everything else missing keeps its saved value. Without that declaration
    the System form, which has no `show_names`, would read as switching names
    off. settings._coerce validates the rest."""
    changes: dict[str, str | bool] = {k: v[0] for k, v in form.items() if k != CHECKBOXES}
    for field in form.get(CHECKBOXES, [""])[0].split():
        changes[field] = field in form
    if changes.get("detector_password") == PASSWORD_SET:
        del changes["detector_password"]  # untouched, so the stored one stands
    return changes


def subjects(ctx: modes.Context) -> list[tuple[str, str | None]]:
    """What the current mode's page is about, each with the plate its artwork
    was cut from, or None when it has none to draw."""
    rows = []
    for name in modes.subjects(ctx):
        pick = image_for(name, ctx.images_dir, ctx.style, ctx.picks)
        # Unlisted (a hand-filled style keeps no manifest): name the style itself.
        rows.append((name, source_of(pick) or ctx.style if pick else None))
    return rows


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


def _checkbox(field: str, label: str, checked: bool) -> str:
    return (
        f'<label class="src"><input type="checkbox" name="{field}"'
        f"{' checked' if checked else ''}> {label}</label>"
    )


def _action(action: str, label: str) -> str:
    return (
        f'<form class="inline {action}" method="post" action="/admin">'
        f'<input type="hidden" name="action" value="{action}">'
        f'<button type="submit">{label}</button></form>'
    )


def _state(ok: bool, good: str, bad: str) -> str:
    return f'<span class="{"ok" if ok else "bad"}">{good if ok else bad}</span>'


def _detector(url: str) -> str:
    """The configured BirdNET-Go's state, and the version it reports."""
    running, version = hostinfo.detector(url)
    return _state(running, "running", "unreachable") + (f" · {version}" if version else "")


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


def _species_li(name: str, source: str | None) -> str:
    # Marks species counted in the window but omitted from the collage (#9); else
    # names the plate the artwork was cut from, per the style's manifest.
    if source is None:
        return f'<li class="noart">{name} <small>no art</small></li>'
    return f"<li>{name} <small>{_display_name(source)}</small></li>"


def species_html(species: list[tuple[str, str | None]], name_of: Namer) -> str:
    return (
        "".join(_species_li(name_of.inline(name), source) for name, source in species)
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
        items.append((selected, f"{selected} (unavailable)"))
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
        return (
            f'<span class="warn">{status.update_available} available</span>'
            f"{_action('update', 'Install')}"
        )
    return f'<span id="state">up to date</span>{_action("check", "Check")}'


def _names_field(settings: Settings, languages: list[tuple[str, str]]) -> str:
    return (
        f'<div class="field"><span>Species names</span>'
        f"{_checkbox('show_names', 'Display bird names', settings.show_names)}"
        f'<label class="sub"><small>Language</small>'
        f"{_language_select('primary_language', languages, settings.primary_language)}</label>"
        f'<label class="sub"><small>Second language (optional)</small>'
        f"{_language_select('secondary_language', languages, settings.secondary_language, optional=True)}</label>"
        f'<label class="sub"><small>Typeface</small><select name="label_font">'
        f"{_options(FONTS, settings.label_font, lambda k: FONTS[k][0])}</select></label>"
        f'<label class="sub"><small>Text size</small><select name="label_size">'
        f"{_options(LABEL_SIZES, settings.label_size, lambda k: LABEL_SIZES[k][0])}</select></label>"
        f"</div>"
    )


def _text_field(field: str, label: str, value: str, kind: str = "text", hint: str = "") -> str:
    return (
        f"<label><span>{label}{f' <small>{hint}</small>' if hint else ''}</span>"
        f'<input type="{kind}" name="{field}" value="{html.escape(value, quote=True)}"></label>'
    )


def _detector_field(settings: Settings) -> str:
    """Where the frame reads from. Credentials are only for a BirdNET-Go in
    PrivateMode, so they fold away until one is stored - or until a test comes
    back asking for them, which admin.js opens."""
    stored = settings.detector_username or settings.detector_password
    return (
        _text_field("detector_url", "Address", settings.detector_url, "url")
        + f'<details id="credentials"{" open" if stored else ""}>'
        + "<summary>Credentials <small>(PrivateMode only)</small></summary>"
        + _text_field("detector_username", "Username", settings.detector_username)
        + _text_field(
            "detector_password",
            "Password",
            PASSWORD_SET if settings.detector_password else "",
            "password",
        )
        + "</details>"
    )


def birdnet_link(url: str) -> tuple[str, int | None]:
    """The nav link to BirdNET-Go: (address, port to substitute this page's host
    on). A loopback address is loopback from the Pi only, so a remote browser
    cannot follow it; anything else is reached exactly as configured."""
    parsed = urlparse(url)
    if parsed.hostname in _LOOPBACK:
        return url, parsed.port or BIRDNET_PORT
    return url, None


def connection(form: dict[str, list[str]], settings: Settings) -> dict:
    """The connection test, over the values the form is holding rather than the
    saved ones - validated and placeholder-resolved exactly as Save would.

    `status` is the same answer in the BirdNET-Go row's words, so the two can
    never disagree. The row's own probe is /health, which answers under
    PrivateMode, so only the test can tell "running" from "unusable"."""
    tried = merged(settings, **form_changes(form))
    state, detail = probe(tried.detector_url, tried.detector_username, tried.detector_password)
    text, row = _ANSWERS[state]
    return {
        "state": state,
        "text": f"{text} · {detail}" if detail else text,
        "status": f'<span class="{"ok" if state == "ok" else "bad"}">{row}</span>',
    }


def _lookbacks(settings: Settings) -> str:
    # A hand-edited non-preset value stays selectable so Save doesn't drop it.
    labels = dict(LOOKBACK_OPTIONS)
    labels.setdefault(settings.lookback_hours, f"{settings.lookback_hours} hours")
    return _options(sorted(labels, key=lookback_order), settings.lookback_hours, labels.get)


def page(
    ctx: modes.Context,
    settings: Settings,
    status: Status,
    panel_size: tuple[int, int],
    detected: bool,
    names_dir: Path,
) -> str:
    """The admin page. Everything about the frame comes off `ctx`, so the
    listing always describes the page the preview is rendering.

    Renders with the detector down on purpose: this is the page you reach for
    when it is, so the rows that need it say so rather than vanish.
    """
    languages = ordered(catalog(names_dir))
    try:
        latest, rows = ctx.source.latest(), subjects(ctx)
    except Unavailable:
        latest, rows = None, None
    windowed = modes.mode_of(settings.mode).windowed
    online, iface = hostinfo.online()
    rendered = _stamp(status.rendered_at) if status.rendered_at else "not yet"
    if status.push_error:
        rendered += f" · panel push failing ({status.push_error})"
    w, h = settings.web_size(panel_size)
    glass = f"{panel_size[0]}×{panel_size[1]}"
    birdnet_url, birdnet_port = birdnet_link(settings.detector_url)
    return Template((STATIC_DIR / "admin.html").read_text()).substitute(
        version=__version__,
        docs_url=DOCS_URL,
        checkboxes=CHECKBOXES,
        config=json.dumps(
            {
                "birdnetUrl": birdnet_url,
                "birdnetPort": birdnet_port,
                "version": __version__,
                "windowedModes": [k for k, m in MODES.items() if m.windowed],
            }
        ),
        mode_field=(
            f'<div class="field"><span>Mode</span>'
            f"{_radios('mode', [(k, m.label) for k, m in MODES.items()], settings.mode)}</div>"
        ),
        resolutions=_options(
            WEB_HEIGHTS,
            settings.web_resolution,
            lambda r: "{} ({}×{})".format(
                r, *replace(settings, web_resolution=r).web_size(panel_size)
            ),
        ),
        rotations=_options(ROTATIONS, settings.rotation, lambda r: f"{r}° {_ASPECT[r % 180]}"),
        lookback_off="" if windowed else ' class="off"',
        lookback_disabled="" if windowed else " disabled",
        lookbacks=_lookbacks(settings),
        names_field=_names_field(settings, languages),
        style_field=(
            f'<div class="field"><span>Artwork style</span>'
            f"{_radios('style', [(s, _display_name(s)) for s in available_styles(ctx.images_dir)], ctx.style)}</div>"
        ),
        species_count=len(rows) if rows is not None else 0,
        species_rows=species_html(rows, ctx.namer) if rows is not None else _UNREACHABLE,
        update=_update(status),
        auto_update=_checkbox(
            "auto_update", "Install new releases automatically", settings.auto_update
        ),
        panel=f"detected · {glass}" if detected else f"not detected · assuming {glass}",
        birdnet=_detector(settings.detector_url),
        detector_field=_detector_field(settings),
        host=hostinfo.lan_address(),
        online=_state(online, "online", "offline") + (f" · {iface}" if iface else ""),
        disk=hostinfo.disk_free(names_dir),
        started=_stamp(status.started_at),
        kiosk_size=f"{w}×{h}",
        rendered=rendered,
        latest=(
            f"{ctx.namer.inline(latest.scientific_name)} · {_stamp(latest.detected_at)}"
            if latest
            else ("none yet" if rows is not None else "detector unreachable")
        ),
    )
