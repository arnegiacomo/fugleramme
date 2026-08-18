"""The admin page: everything at `/admin` that is not HTTP.

Markup, style and behaviour live in `static/admin.{html,css,js}`; this fills the
template's slots. Pure string builders, so none of it needs a server to test.
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from string import Template

from .. import __version__, modes
from ..config import BIRDNET_PORT, DOCS_URL, WEB_HEIGHTS
from ..languages import NONE, Namer, catalog, ordered
from ..modes import MODES
from ..names import available_styles, image_for, source_of
from ..render.fonts import FONTS, LABEL_SIZES
from ..settings import LOOKBACK_OPTIONS, ROTATIONS, Settings, lookback_order
from ..status import Status
from . import STATIC_DIR, hostinfo

CHECKBOXES = "checkboxes"  # hidden field naming the checkboxes a form carries

_ASPECT = {0: "(landscape)", 90: "(portrait)"}

# Style and plate names that don't title-case into something readable.
_NAMES = {"vonwright": "von Wright", "gould": "Gould"}


def form_changes(form: dict[str, list[str]]) -> dict:
    """Admin form to settings overrides. Unchecked checkboxes and disabled
    fields are both absent from a post, so a form declares its own checkboxes
    and everything else missing keeps its saved value. Without that declaration
    the System form, which has no `show_names`, would read as switching names
    off. settings._coerce validates the rest."""
    changes: dict[str, str | bool] = {k: v[0] for k, v in form.items() if k != CHECKBOXES}
    for field in form.get(CHECKBOXES, [""])[0].split():
        changes[field] = field in form
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
    listing always describes the page the preview is rendering."""
    languages = ordered(catalog(names_dir))
    latest = ctx.db.latest()
    rows = subjects(ctx)
    windowed = modes.mode_of(settings.mode).windowed
    online, iface = hostinfo.online()
    rendered = _stamp(status.rendered_at) if status.rendered_at else "not yet"
    if status.push_error:
        rendered += f" · panel push failing ({status.push_error})"
    w, h = settings.web_size(panel_size)
    glass = f"{panel_size[0]}×{panel_size[1]}"
    return Template((STATIC_DIR / "admin.html").read_text()).substitute(
        version=__version__,
        docs_url=DOCS_URL,
        checkboxes=CHECKBOXES,
        config=json.dumps(
            {
                "birdnetPort": BIRDNET_PORT,
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
        species_count=len(rows),
        species_rows=species_html(rows, ctx.namer),
        update=_update(status),
        auto_update=_checkbox(
            "auto_update", "Install new releases automatically", settings.auto_update
        ),
        panel=f"detected · {glass}" if detected else f"not detected · assuming {glass}",
        birdnet=_state(hostinfo.reachable("127.0.0.1", BIRDNET_PORT), "running", "unreachable"),
        host=hostinfo.lan_address(),
        online=_state(online, "online", "offline") + (f" · {iface}" if iface else ""),
        disk=hostinfo.disk_free(ctx.db.path.parent),
        started=_stamp(status.started_at),
        kiosk_size=f"{w}×{h}",
        rendered=rendered,
        latest=(
            f"{ctx.namer.inline(latest.scientific_name)} · {_stamp(latest.detected_at)}"
            if latest
            else "none yet"
        ),
    )
