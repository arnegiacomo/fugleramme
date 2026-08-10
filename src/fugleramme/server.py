"""HTTP server for the kiosk and admin views.

The kiosk (`/`) serves one thing: a full-color collage of the species seen in
the recent window, full-screen. It never reloads; instead it polls `/state` and
swaps the image only when the collage actually changed, so a new bird appears
within one poll interval with no flash. Presentation settings live at `/admin`
(#2) - rotation, lookback window, poll interval - and are read per request
from the shared SettingsStore, so a change takes effect without a restart. No
auth: both views are open on the LAN.

Stdlib http.server only, but threaded with a socket timeout: a serial server is
one silent client away from a dead kiosk, since a connection that never sends a
request blocks the accept loop forever. The server opens its own SQLite
connection; WAL lets it coexist with the render loop's connection.
"""

from __future__ import annotations

import hashlib
import json
import logging
import shutil
import socket
import time
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, modes, updates
from .config import BIRDNET_PORT, DOCS_URL, WEB_RESOLUTIONS
from .db import Database, Detection
from .featured import Featured
from .fonts import FONTS, LABEL_SIZES
from .languages import NONE, Namer, catalog, namer, ordered
from .modes import MODES
from .names import available_styles, image_for, resolve, source_of
from .panel import Panel
from .picks import Picks
from .settings import (
    LOOKBACK_OPTIONS,
    ROTATIONS,
    Settings,
    SettingsStore,
    lookback_order,
    merged,
)
from .status import Status

log = logging.getLogger(__name__)

REQUEST_TIMEOUT = 15


def _kiosk_html(refresh_seconds: int) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fugleramme</title>
<style>
  html, body {{ margin: 0; height: 100%; background: #faf9f6; }}
  body {{ display: flex; align-items: center; justify-content: center; }}
  img {{ max-width: 100%; max-height: 100vh; object-fit: contain; }}
</style>
</head>
<body>
<img id="collage" src="/collage.png" alt="Birds seen recently">
<script>
  // The interval comes from /state: without a reload, nothing else picks up an admin change.
  let token = null, delay = {refresh_seconds};
  async function tick() {{
    try {{
      const state = await (await fetch("/state", {{cache: "no-store"}})).json();
      delay = state.refresh;
      if (state.token !== token) {{
        token = state.token;
        const next = new Image();  // decode before swapping, so the frame never blanks
        next.onload = () => {{ document.getElementById("collage").src = next.src; }};
        next.src = "/collage.png?v=" + encodeURIComponent(token);
      }}
    }} catch (e) {{}}  // transient: retry next tick
    setTimeout(tick, delay * 1000);
  }}
  tick();
</script>
</body>
</html>
"""


def _options(values, selected, label=str) -> str:
    return "".join(
        f'<option value="{v}"{" selected" if v == selected else ""}>{label(v)}</option>'
        for v in values
    )


def _duration(seconds: int) -> str:
    for unit, size in (("d", 86400), ("h", 3600), ("m", 60)):
        if seconds >= size:
            return f"{seconds // size}{unit}"
    return f"{seconds}s"


def _ago(dt: datetime) -> str:
    return f"{_duration(int((datetime.now(timezone.utc) - dt).total_seconds()))} ago"


_ONLINE_TTL = 60
_online_cache: tuple[float, bool] | None = None


def _reachable(host: str, port: int) -> bool:
    try:
        socket.create_connection((host, port), timeout=1).close()
        return True
    except OSError:
        return False


def _state(ok: bool, good: str, bad: str) -> str:
    return f'<span class="{"ok" if ok else "bad"}">{good if ok else bad}</span>'


def _default_iface() -> str:
    """Interface holding the default route. Linux only; other dev hosts get nothing."""
    try:
        rows = Path("/proc/net/route").read_text().splitlines()[1:]
    except OSError:
        return ""
    # Columns are Iface, Destination (hex, all-zero for the default route).
    return next((f[0] for r in rows if len(f := r.split()) > 1 and f[1] == "00000000"), "")


def _online() -> str:
    """Cached, so a page load never waits out a dead link twice in a minute."""
    global _online_cache
    now = time.monotonic()
    if _online_cache is None or now - _online_cache[0] >= _ONLINE_TTL:
        # Cloudflare by IP - no name lookup to hang on; 443 since some networks filter 53.
        _online_cache = (now, _reachable("1.1.1.1", 443))
    ok = _online_cache[1]
    iface = _default_iface()
    return _state(ok, "online", "offline") + (f" · {iface}" if iface else "")


def _stamp(dt: datetime) -> str:
    local = dt.astimezone()
    fmt = "%H:%M" if local.date() == datetime.now().astimezone().date() else "%-d %b %H:%M"
    return f'<time title="{_ago(dt)}">{local.strftime(fmt)}</time>'


def _disk_free(path: Path) -> str:
    usage = shutil.disk_usage(path)
    return f"{usage.free / 1e9:.0f} GB free of {usage.total / 1e9:.0f} GB"


def _species_li(name: str, source: str | None) -> str:
    # Marks species counted in the window but omitted from the collage (#9); else
    # names the plate the artwork was cut from, read from the file's own metadata.
    if source is None:
        return f'<li class="noart">{name} <small>no art</small></li>'
    return f'<li>{name} <small>{_display_name(source)}</small></li>'


def _species_html(species: list[tuple[str, str | None]], name_of: Namer) -> str:
    return "".join(
        _species_li(name_of.inline(name), source) for name, source in species
    ) or '<li class="empty">none yet</li>'


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


def _lan_address() -> str:
    host = socket.gethostname()
    if "." not in host:
        host += ".local"  # avahi publishes it; the Pi's bare hostname does not resolve off-box
    try:
        # Connecting a UDP socket sends nothing; it just picks the outbound interface.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.0.2.1", 1))
            return f"{host} · {s.getsockname()[0]}"
    except OSError:
        return host


_ASPECT = {0: "(landscape)", 90: "(portrait)"}

# Style and plate names that don't title-case into something readable.
_NAMES = {"vonwright": "von Wright", "gould": "Gould"}


def _display_name(name: str) -> str:
    return _NAMES.get(name, name.replace("-", " ").title())


def _action(action: str, label: str) -> str:
    return (
        f'<form class="inline {action}" method="post" action="/admin">'
        f'<input type="hidden" name="action" value="{action}">'
        f'<button type="submit">{label}</button></form>'
    )


def _update_dd(status: Status) -> str:
    # `requested` counts as installing: the loop only picks it up a tick later.
    if status.updating or status.update_requested:
        # A phase with no percent leaves the bar valueless, which renders indeterminate.
        label, value = status.update_phase or "installing…", ""
        if status.update_percent is not None:
            label, value = f"{label} {status.update_percent}%", f' value="{status.update_percent}"'
        return (
            f'<span id="phase">{label}</span>'
            f'<progress id="bar" max="100"{value}></progress>'
        )
    if status.update_error:
        return f'<span class="bad">{status.update_error}</span>{_action("check", "Retry")}'
    if status.update_available:
        return (
            f'<span class="warn">{status.update_available} available</span>'
            f'{_action("update", "Install")}'
        )
    return f'<span id="state">up to date</span>{_action("check", "Check")}'


def _radios(field: str, options: list[tuple[str, str]], active: str) -> str:
    return "".join(
        f'<label class="src"><input type="radio" name="{field}" value="{value}"'
        f'{" checked" if value == active else ""}> {label}</label>'
        for value, label in options
    )


CHECKBOXES = "checkboxes"  # hidden field naming the checkboxes a form carries


def _checkbox(field: str, label: str, checked: bool) -> str:
    return (
        f'<label class="src"><input type="checkbox" name="{field}"'
        f'{" checked" if checked else ""}> {label}</label>'
    )


def _form_changes(form: dict[str, list[str]]) -> dict:
    """Admin form to settings overrides. Unchecked checkboxes and disabled
    fields are both absent from a post, so a form declares its own checkboxes
    and everything else missing keeps its saved value. Without that declaration
    the System form, which has no `show_names`, would read as switching names
    off. _coerce validates the rest."""
    changes = {k: v[0] for k, v in form.items() if k != CHECKBOXES}
    for field in form.get(CHECKBOXES, [""])[0].split():
        changes[field] = field in form
    return changes


def _admin_html(
    settings: Settings,
    species: list[tuple[str, str | None]],
    latest: Detection | None,
    panel_size: tuple[int, int] | None,
    available: list[str],
    active: str,
    status: Status,
    data_dir: Path,
    languages: list[tuple[str, str]],
    name_of: Namer,
) -> str:
    resolutions = _options(
        WEB_RESOLUTIONS,
        settings.web_resolution,
        lambda r: f"{r} ({WEB_RESOLUTIONS[r][0]}×{WEB_RESOLUTIONS[r][1]})",
    )
    rotations = _options(ROTATIONS, settings.rotation, lambda r: f"{r}° {_ASPECT[r % 180]}")
    # A hand-edited non-preset value stays selectable so Save doesn't drop it.
    labels = dict(LOOKBACK_OPTIONS)
    labels.setdefault(settings.lookback_hours, f"{settings.lookback_hours} hours")
    lookbacks = _options(sorted(labels, key=lookback_order), settings.lookback_hours, labels.get)
    windowed = MODES[settings.mode].windowed if settings.mode in MODES else True
    windowed_modes = json.dumps([k for k, m in MODES.items() if m.windowed])
    mode_field = (
        f'<div class="field"><span>Mode</span>'
        f'{_radios("mode", [(k, m.label) for k, m in MODES.items()], settings.mode)}</div>'
    )
    style_field = (
        f'<div class="field"><span>Artwork style</span>'
        f'{_radios("style", [(s, _display_name(s)) for s in available], active)}</div>'
    )
    names_field = (
        f'<div class="field"><span>Species names</span>'
        f'{_checkbox("show_names", "Display bird names", settings.show_names)}'
        f'<label class="sub"><small>Language</small>'
        f'{_language_select("primary_language", languages, settings.primary_language)}</label>'
        f'<label class="sub"><small>Second language (optional)</small>'
        f'{_language_select("secondary_language", languages, settings.secondary_language, optional=True)}</label>'
        f'<label class="sub"><small>Typeface</small><select name="label_font">'
        f'{_options(FONTS, settings.label_font, lambda k: FONTS[k][0])}</select></label>'
        f'<label class="sub"><small>Text size</small><select name="label_size">'
        f'{_options(LABEL_SIZES, settings.label_size, lambda k: LABEL_SIZES[k][0])}</select></label>'
        f"</div>"
    )
    w, h = settings.web_size()
    panel_status = (
        f"detected · {panel_size[0]}×{panel_size[1]}" if panel_size
        else "not detected (web-only)"
    )
    last = (
        f"{name_of.inline(latest.scientific_name)} · {_stamp(latest.detected_at)}"
        if latest else "none yet"
    )
    rendered = _stamp(status.rendered_at) if status.rendered_at else "not yet"
    if status.push_error:
        rendered += f" · panel push failing ({status.push_error})"
    rows = _species_html(species, name_of)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fugleramme admin</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width: 56rem; margin: 3rem auto; padding: 0 1rem; }}
  header {{ display: flex; justify-content: space-between; align-items: baseline; flex-wrap: wrap;
           gap: 0.5rem; border-bottom: 1px solid #e5e2dc; padding-bottom: 0.75rem; margin-bottom: 2rem; }}
  header h1 {{ margin: 0; }}
  header nav a {{ margin-left: 1.25rem; }}
  h2 {{ font-size: 1.05rem; margin: 0 0 0.5rem; }}
  /* Undoes the page-wide block `span`, which would break a heading over three lines. */
  h2 span {{ display: inline; font-weight: inherit; margin: 0; }}
  nav.tabs {{ display: flex; gap: 0.5rem; margin: -1rem 0 1.75rem; }}
  nav.tabs button {{ font-size: 0.95rem; padding: 0.4rem 1rem; margin: 0; cursor: pointer;
                    background: none; border: 0; border-bottom: 2px solid transparent; color: #446; }}
  nav.tabs button[aria-selected="true"] {{ border-bottom-color: #446; font-weight: 600; color: inherit; }}
  section[hidden] {{ display: none; }}
  .cols {{ display: flex; gap: 2.5rem; align-items: flex-start; }}
  form.settings {{ flex: 0 0 15rem; }}
  aside.side {{ flex: 1; min-width: 0; }}
  label {{ display: block; margin: 0 0 1.25rem; }}
  span {{ display: block; font-weight: 600; margin-bottom: 0.25rem; }}
  small {{ color: #666; font-weight: 400; }}
  select {{ font-size: 1rem; padding: 0.4rem; }}
  input {{ font-size: 1rem; padding: 0.4rem; width: 8rem; }}
  .field {{ margin: 0 0 1.25rem; }}
  label.sub {{ display: block; margin: 0.6rem 0 0; font-weight: 400; }}
  label.sub small {{ display: block; margin-bottom: 0.15rem; }}
  label.sub select {{ width: 100%; }}
  label.src {{ display: flex; align-items: center; gap: 0.4rem; font-weight: 400; margin: 0 0 0.3rem; }}
  label.src input {{ width: auto; padding: 0; }}
  button {{ font-size: 1rem; padding: 0.5rem 1.25rem; margin-top: 0.5rem; }}
  button:disabled {{ opacity: 0.45; }}
  /* A setting the chosen mode does not read: shown, so its value is not a surprise on the way back. */
  label.off {{ opacity: 0.45; }}
  a {{ color: #446; }}
  dl.status {{ display: grid; grid-template-columns: auto 1fr; gap: 0.35rem 1rem;
              background: #f4f2ee; padding: 1rem 1.25rem; border-radius: 6px; margin: 0 0 1.75rem; }}
  dl.status dt {{ color: #666; }}
  dl.status dd {{ margin: 0; }}
  dl.status dd span {{ display: inline; font-weight: inherit; margin: 0; }}
  dl.status dd.update {{ display: flex; align-items: center; gap: 0.5rem; }}
  dl.status dd.update button {{ margin: 0; }}
  time {{ border-bottom: 1px dotted #bbb; cursor: help; }}
  .ok, .bad, .warn {{ display: inline; font-weight: inherit; margin: 0; }}
  .ok {{ color: #3a7d44; }}
  .bad {{ color: #a4392f; }}
  .warn {{ color: #8a6d1f; }}
  form.block {{ margin: 0 0 1.75rem; }}  /* the Save button carries no bottom margin of its own */
  form.inline {{ display: inline; }}
  form.inline button {{ font-size: 0.8rem; padding: 0.1rem 0.5rem; margin: 0 0 0 0.5rem; }}
  ul.species {{ list-style: none; padding: 0; margin: 0 0 1.75rem;
               display: grid; grid-template-columns: repeat(auto-fill, minmax(13rem, max-content));
               justify-content: start; gap: 0.15rem 2.5rem; }}
  ul.species li {{ padding: 0.1rem 0; }}
  ul.species li.noart {{ color: #aaa; }}
  ul.species li.noart small {{ color: #aaa; }}
  ul.species li.empty {{ color: #999; }}
  /* Sized to the image, not the column: a portrait page in a 100%-wide box would
     draw its border around the letterboxing. */
  .preview img {{ display: block; max-width: 100%; max-height: 60vh;
                 border: 1px solid #ddd; border-radius: 6px; }}
  .rendering {{ display: none; align-items: center; justify-content: center; gap: 0.6rem;
               color: #666; }}
  /* The box holds its height across a re-render, so the page does not jump.
     Left-aligned: a portrait page centred in the column leaves it lopsided
     against the species list under it. */
  .preview {{ min-height: 14rem; display: flex; align-items: center; justify-content: flex-start;
             margin: 0 0 1.75rem; }}
  .preview.loading .rendering {{ display: flex; }}
  .preview.loading img {{ display: none; }}
  /* margin: undoes the page-wide `span` rule, which offsets it from the caption. */
  .spinner {{ width: 1.1rem; height: 1.1rem; margin: 0; border: 2px solid #ddd;
             border-top-color: #888; border-radius: 50%; animation: spin 0.8s linear infinite; }}
  .spinner.inline {{ display: inline-block; vertical-align: -0.15rem; }}
  #bar {{ width: 7rem; height: 0.55rem; }}
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  @media (prefers-reduced-motion: reduce) {{ .spinner {{ animation: none; }} }}
  @media (max-width: 40rem) {{
    .cols {{ flex-direction: column; }}
    form.settings {{ flex: none; }}
  }}
</style>
</head>
<body>
<header>
  <h1>Fugleramme</h1>
  <nav><a href="/">Kiosk</a><a id="birdnet" href="#" title="detection &amp; stats">BirdNET-Go</a><a href="{DOCS_URL}" target="_blank" rel="noopener">Docs</a></nav>
</header>
<nav class="tabs" role="tablist">
  <button type="button" role="tab" data-tab="settings">Display</button>
  <button type="button" role="tab" data-tab="system">System</button>
</nav>
<section id="tab-settings" class="cols">
  <form class="settings" method="post" action="/admin">
    <input type="hidden" name="{CHECKBOXES}" value="show_names">
    {mode_field}
    <label><span>Resolution <small>(web view only)</small></span>
      <select name="web_resolution">{resolutions}</select></label>
    <label><span>Rotation <small>(how the frame hangs)</small></span>
      <select name="rotation">{rotations}</select></label>
    <label id="lookback"{"" if windowed else ' class="off"'}>
      <span>Lookback window <small>(how far back the frame looks)</small></span>
      <select name="lookback_hours"{"" if windowed else " disabled"}>{lookbacks}</select></label>
    <label><span>Polling interval <small>(seconds between checks)</small></span>
      <input type="number" name="kiosk_refresh_seconds" min="1" max="3600" value="{settings.kiosk_refresh_seconds}"></label>
    {names_field}
    {style_field}
    <button type="submit">Save</button>
  </form>
  <aside class="side">
    <h2>Preview</h2>
    <div class="preview loading" id="preview">
      <p class="rendering"><span class="spinner"></span> Rendering…</p>
      <img id="shot" alt="Current page">
    </div>
    <h2>On the page (<span id="count">{len(species)}</span>)</h2>
    <ul class="species" id="species">{rows}</ul>
  </aside>
</section>
<section id="tab-system" hidden>
  <h2>Updates</h2>
  <dl class="status">
    <dt>Version</dt><dd>v{__version__}</dd>
    <dt>Update</dt><dd class="update">{_update_dd(status)}</dd>
  </dl>
  <form class="block" method="post" action="/admin">
    <input type="hidden" name="{CHECKBOXES}" value="auto_update">
    {_checkbox("auto_update", "Install new releases automatically", settings.auto_update)}
    <button type="submit">Save</button>
  </form>
  <h2>System</h2>
  <dl class="status">
    <dt>Inky panel</dt><dd>{panel_status}</dd>
    <dt>BirdNET-Go</dt><dd>{_state(_reachable("127.0.0.1", BIRDNET_PORT), "running", "unreachable")}</dd>
    <dt>Host</dt><dd>{_lan_address()}</dd>
    <dt>Internet</dt><dd>{_online()}</dd>
    <dt>Disk</dt><dd>{_disk_free(data_dir)}</dd>
    <dt>Started</dt><dd>{_stamp(status.started_at)}</dd>
    <dt>Kiosk render</dt><dd>{w}×{h}</dd>
  </dl>
  <h2>Activity</h2>
  <dl class="status">
    <dt>Last render</dt><dd>{rendered}</dd>
    <dt>Last detection</dt><dd>{last}</dd>
  </dl>
</section>
<script>
  // Same host as this page, BirdNET-Go's own port - the bind host (0.0.0.0) is not reachable.
  document.getElementById("birdnet").href = location.protocol + "//" + location.hostname + ":{BIRDNET_PORT}/";

  // Every button posts and redirects, so a save reloads: the tab and the scroll
  // position have to be carried across by hand.
  for (const f of document.querySelectorAll("form")) {{
    f.addEventListener("submit", () => sessionStorage.setItem("scroll", String(window.scrollY)));
  }}
  const scrolled = sessionStorage.getItem("scroll");
  sessionStorage.removeItem("scroll");

  // The install reloads the page as a new version, so the tab is what remembers
  // the old one - long enough to say the update landed.
  const was = sessionStorage.getItem("version");
  const state = document.getElementById("state");
  sessionStorage.setItem("version", "{__version__}");
  if (state && was && was !== "{__version__}") state.textContent = "updated to v{__version__}";

  const tabs = document.querySelectorAll("nav.tabs button");
  function showTab(name) {{
    for (const tab of tabs) {{
      const on = tab.dataset.tab === name;
      tab.setAttribute("aria-selected", on);
      document.getElementById("tab-" + tab.dataset.tab).hidden = !on;
    }}
    localStorage.setItem("tab", name);
  }}
  for (const tab of tabs) tab.addEventListener("click", () => showTab(tab.dataset.tab));
  showTab(localStorage.getItem("tab") === "system" ? "system" : "settings");

  // The check runs inside its own POST, so the spinner only has to outlive the navigation.
  const check = document.querySelector("dd.update form.check");
  if (check) {{
    check.addEventListener("submit", () => {{
      check.insertAdjacentHTML("beforebegin", '<span class="spinner inline"></span>');
      check.querySelector("button").disabled = true;
    }});
  }}

  // An install ends with systemd restarting us, so the poll rides out a dead
  // server and reloads once one answers with the work done - or failed.
  if (document.getElementById("bar")) {{
    const phase = document.getElementById("phase");
    const bar = document.getElementById("bar");
    (function poll() {{
      setTimeout(async () => {{
        try {{
          const state = await (await fetch("/update", {{cache: "no-store"}})).json();
          if (!state.updating) {{
            location.reload();
            return;
          }}
          if (state.phase) {{
            phase.textContent = state.phase + (state.percent === null ? "" : " " + state.percent + "%");
          }}
          if (state.percent === null) bar.removeAttribute("value");
          else bar.value = state.percent;
        }} catch (e) {{}}
        poll();
      }}, 1000);
    }})();
  }}

  const preview = document.getElementById("preview");
  const shot = document.getElementById("shot");
  const caption = document.querySelector(".rendering");
  const captionHTML = caption.innerHTML;
  const form = document.querySelector("form.settings");
  const save = form.querySelector("button[type=submit]");
  const serialize = () => new URLSearchParams(new FormData(form)).toString();
  const saved = serialize();
  const dirty = () => serialize() !== saved;
  let saving = false, shown = null, seq = 0, timer = null;

  function loadPreview() {{
    const query = serialize();
    if (query === shown) return;
    const id = ++seq;
    preview.classList.add("loading");
    caption.innerHTML = captionHTML;
    const next = new Image();  // decode off-screen, so the img is never stale or broken
    next.onload = () => {{
      if (id !== seq) return;  // a later edit already superseded this render
      shown = query;
      shot.src = next.src;
      preview.classList.remove("loading");
    }};
    next.onerror = () => {{
      if (id !== seq) return;
      caption.textContent = "Preview unavailable";
    }};
    next.src = "/preview.png?" + query;
    loadSpecies(query, id);
  }}

  // The list under the preview is of the page being previewed, not the saved one.
  async function loadSpecies(query, id) {{
    try {{
      const body = await (await fetch("/species?" + query, {{cache: "no-store"}})).json();
      if (id !== seq) return;
      document.getElementById("count").textContent = body.count;
      document.getElementById("species").innerHTML = body.html;
    }} catch (e) {{}}  // the preview alone is worth showing
  }}

  // Settings the chosen mode ignores go dim and stop being submitted, so the
  // saved value survives a trip through a mode that has no use for it.
  const windowedModes = {windowed_modes};
  const lookback = document.getElementById("lookback");
  function syncMode() {{
    const mode = form.querySelector("input[name=mode]:checked");
    const on = !mode || windowedModes.includes(mode.value);
    lookback.querySelector("select").disabled = !on;
    lookback.classList.toggle("off", !on);
  }}

  form.addEventListener("input", () => {{
    syncMode();
    save.disabled = !dirty();
    clearTimeout(timer);  // debounced: a render is expensive on the Pi
    timer = setTimeout(loadPreview, 500);
  }});
  form.addEventListener("submit", () => {{ saving = true; }});
  window.addEventListener("beforeunload", (e) => {{
    if (saving || !dirty()) return;
    e.preventDefault();
    e.returnValue = "";
  }});

  syncMode();
  save.disabled = true;
  loadPreview();
  if (scrolled !== null) window.scrollTo(0, Number(scrolled));
</script>
</body>
</html>
"""


def make_handler(
    db: Database, images_dir: Path, store: SettingsStore, picks: Picks,
    featured: Featured, panel: Panel | None, status: Status,
):
    class Handler(BaseHTTPRequestHandler):
        timeout = REQUEST_TIMEOUT

        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def log_error(self, fmt, *args):
            log.warning("%s %s", self.address_string(), fmt % args)

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _send_png(self, png: bytes):
            # no-cache + ETag lets an unchanged refresh return a bodyless 304 instead of re-downloading the collage.
            etag = f'"{hashlib.md5(png).hexdigest()}"'
            if self.headers.get("If-None-Match") == etag:
                self.send_response(304)
                self.send_header("ETag", etag)
                self.end_headers()
                return
            self.send_response(200)
            self.send_header("Content-Type", "image/png")
            self.send_header("Content-Length", str(len(png)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("ETag", etag)
            self.end_headers()
            self.wfile.write(png)

        def _namer(self, settings: Settings) -> Namer:
            return namer(
                settings.primary_language, settings.secondary_language, store.path.parent
            )

        def _subjects(self, settings: Settings) -> list[tuple[str, str | None]]:
            """What the current mode's page is about, each with the plate its
            artwork was cut from, or None when it has none to draw."""
            style = resolve(settings.style, images_dir)
            rows = []
            for name in modes.subjects(self._context(settings)):
                pick = image_for(name, images_dir, style, picks)
                # Unstamped (a hand-filled style): name the style itself.
                rows.append((name, source_of(pick) or style if pick else None))
            return rows

        def _context(self, settings: Settings) -> modes.Context:
            # commit stays False: the kiosk must never advance the bird of the day.
            return modes.context(
                db, images_dir, picks, featured, settings, self._namer(settings),
                settings.web_size(),
            )

        def do_GET(self):
            route = urlparse(self.path).path
            settings = store.get()
            if route in ("/", "/index.html"):
                self._send(200, _kiosk_html(settings.kiosk_refresh_seconds).encode(), "text/html; charset=utf-8")
            elif route in ("/collage.png", "/preview.png"):
                if route == "/preview.png":
                    # The admin's unsaved form state, so Preview shows it before Save.
                    query = parse_qs(urlparse(self.path).query)
                    settings = merged(settings, **_form_changes(query))
                self._send_png(modes.png_bytes(self._context(settings)))
            elif route == "/state":
                # Cheap enough to poll every second: one grouped query, no render.
                body = json.dumps({
                    "token": modes.token(modes.state_key(self._context(settings))),
                    "refresh": settings.kiosk_refresh_seconds,
                })
                self._send(200, body.encode(), "application/json")
            elif route == "/species":
                # The admin's unsaved form state, like /preview.png.
                settings = merged(settings, **_form_changes(parse_qs(urlparse(self.path).query)))
                rows = self._subjects(settings)
                body = json.dumps(
                    {"count": len(rows), "html": _species_html(rows, self._namer(settings))}
                )
                self._send(200, body.encode(), "application/json")
            elif route == "/admin":
                available = available_styles(images_dir)
                style = resolve(settings.style, images_dir)
                html = _admin_html(
                    settings, self._subjects(settings), db.latest(),
                    panel.resolution if panel else None, available, style,
                    status, db.path.parent,
                    ordered(catalog(store.path.parent)), self._namer(settings),
                )
                self._send(200, html.encode(), "text/html; charset=utf-8")
            elif route == "/update":
                body = json.dumps(
                    {"updating": bool(status.updating or status.update_requested),
                     "version": __version__,
                     "phase": status.update_phase,
                     "percent": status.update_percent}
                )
                self._send(200, body.encode(), "application/json")
            elif route == "/health":
                self._send(200, b"ok", "text/plain")
            else:
                self._send(404, b"not found", "text/plain")

        def do_POST(self):
            if urlparse(self.path).path != "/admin":
                self._send(404, b"not found", "text/plain")
                return
            length = int(self.headers.get("Content-Length", 0))
            form = parse_qs(self.rfile.read(length).decode())
            action = form.get("action", [""])[0]
            if action == "check":
                status.update_error = None
                status.update_available = updates.available(force=True)
            elif action == "update" and status.update_available:
                # The loop installs it: exiting mid-render or mid-push is not safe here.
                status.update_requested = status.update_available
            else:
                store.update(**_form_changes(form))
            self.send_response(303)
            self.send_header("Location", "/admin")
            self.end_headers()

    return Handler


def serve(
    db_path: Path,
    images_dir: Path,
    host: str,
    port: int,
    store: SettingsStore,
    picks: Picks,
    featured: Featured,
    panel: Panel | None = None,
    status: Status | None = None,
) -> None:
    """Blocking server loop. Opens its own DB connection."""
    db = Database(db_path)
    handler = make_handler(db, images_dir, store, picks, featured, panel, status or Status())
    httpd = ThreadingHTTPServer((host, port), handler)
    httpd.serve_forever()
