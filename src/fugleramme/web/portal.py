"""The captive portal a phone on the setup hotspot sees (#308): pick a network, type its
password, and the frame joins it.

Every request from the hotspot gets one of these two pages, whatever it asked for: that is
what makes a phone's network check open them by itself. Self-contained, in the standard
library alone, so a frame that only drives a panel (examples/inky) can carry a copy.
"""

from __future__ import annotations

import base64
import html
import json
from collections.abc import Sequence

TITLE = "Fugleramme"

# The radio for a network the scan did not list. Longer than the 32 bytes an SSID holds, so no
# network is called this.
OTHER = "a network that is not in the list above"

_STYLE = """
body{font:17px/1.4 system-ui,sans-serif;margin:0 auto;max-width:28rem;padding:1.2rem;color:#222}
.title{font:italic 3.2rem/1 Title,Georgia,serif;text-align:center;margin:.6rem 0 1.4rem}
h1{font-size:1.4rem;margin:.2rem 0 1rem}
.bad{color:#b00020}
label.net{display:flex;gap:.6rem;align-items:center;padding:.7rem .2rem;border-bottom:1px solid #ddd}
label.net span{flex:1;overflow-wrap:anywhere}
input[type=text],input[type=password]{width:100%;box-sizing:border-box;font:inherit;padding:.6rem;
margin:.3rem 0 .8rem;border:1px solid #999;border-radius:.4rem}
button{font:inherit;width:100%;padding:.8rem;margin-top:.6rem;border:0;border-radius:.4rem;
background:#222;color:#fff}
small{color:#666}
.address{font-weight:600;overflow-wrap:anywhere;user-select:all;-webkit-user-select:all}
"""

# Shows the password field only for a network that wants one, and the name field only for one
# the scan did not list.
_SCRIPT = """
const form = document.forms[0];
function sync() {
  const picked = form.querySelector('input[name=ssid]:checked');
  const other = picked && picked.value === OTHER;
  document.getElementById('other').hidden = !other;
  document.getElementById('password').hidden = !picked || picked.dataset.open === '1';
}
form.addEventListener('change', sync);
sync();
"""

_LOCK = (
    '<svg viewBox="0 0 16 16" width="16" height="16" aria-label="needs a password">'
    '<path d="M4 7V5a4 4 0 0 1 8 0v2h1v8H3V7zm2 0h4V5a2 2 0 0 0-4 0z" fill="currentColor"/></svg>'
)


def _page(title: str, body: str, font: bytes) -> str:
    """`font` sets the title, inline: a phone on the hotspot has nowhere else to fetch it."""
    face = (
        "@font-face{font-family:Title;"
        f"src:url(data:font/ttf;base64,{base64.b64encode(font).decode()})}}"
        if font
        else ""
    )
    return (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f"<title>{html.escape(title)}</title><style>{face}{_STYLE}</style></head>"
        f'<body><p class="title">{TITLE}</p>{body}</body></html>'
    )


def choose(
    name: str, networks: Sequence[tuple[str, bool]], error: str = "", font: bytes = b""
) -> str:
    """The network list, strongest first, as (name, needs a password)."""
    rows = "".join(
        f'<label class="net"><input type="radio" name="ssid" value="{html.escape(ssid)}"'
        f' data-open="{"0" if secure else "1"}"><span>{html.escape(ssid)}</span>'
        f"{_LOCK if secure else ''}</label>"
        for ssid, secure in networks
    )
    other = (
        f'<label class="net"><input type="radio" name="ssid" value="{html.escape(OTHER)}"'
        ' data-open="0"><span>Other network</span></label>'
        '<div id="other" hidden><label>Network name'
        '<input type="text" name="other" autocapitalize="off" autocorrect="off"></label></div>'
    )
    password = (
        '<div id="password" hidden><label>Password'
        '<input type="password" name="password" autocomplete="off"></label>'
        "<small>Leave it empty for a network without one.</small></div>"
    )
    failed = f'<p class="bad">{html.escape(error)}</p>' if error else ""
    return _page(
        f"Connect {name}",
        f"<h1>Connect the frame to Wi-Fi</h1>{failed}"
        f'<form method="post" action="/join">{rows}{other}{password}'
        f'<button type="submit">Connect</button></form>'
        f"<script>const OTHER = {json.dumps(OTHER)};{_SCRIPT}</script>",
        font,
    )


def joining(ssid: str, home: str, font: bytes = b"") -> str:
    """What the phone is left with: the hotspot is about to go. `home` is where the frame
    answers on the new network. Text, not a link: a phone shows this page in its captive
    sheet, which would open the link inside itself, over a network that is going away."""
    return _page(
        "Connecting",
        f"<h1>Connecting to {html.escape(ssid)}</h1>"
        "<p>The hotspot will now close. When the frame is connected, the birds come back "
        "on it, and you'll find its page at</p>"
        f'<p class="address">{html.escape(home)}</p>'
        "<p>If they don't, the setup screen comes back. Join the hotspot again and check the "
        "password.</p>",
        font,
    )


def parse(form: dict[str, list[str]]) -> tuple[str, str, bool] | None:
    """The network, its password and whether it is hidden, or None for a form without one."""
    picked = form.get("ssid", [""])[0]
    hidden = picked == OTHER
    ssid = form.get("other", [""])[0].strip() if hidden else picked
    if not ssid or len(ssid.encode()) > 32:  # 32 bytes is all an SSID holds
        return None
    return ssid, form.get("password", [""])[0], hidden
