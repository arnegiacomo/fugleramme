"""Render GitHub's `> [!NOTE]` alerts as Material admonitions.

Lets the docs and the README share one callout syntax: GitHub renders it
natively, and this rewrites it for the site at build time.
"""

import re

TYPES = {
    "NOTE": "note",
    "TIP": "tip",
    "IMPORTANT": "info",
    "WARNING": "warning",
    "CAUTION": "danger",
}

ALERT = re.compile(
    rf"^> \[!({'|'.join(TYPES)})\][ \t]*\n((?:^>.*\n?)*)",
    re.MULTILINE,
)


def _admonition(match: re.Match) -> str:
    body = (re.sub(r"^> ?", "", line) for line in match[2].splitlines())
    # Explicit title: Material would otherwise label IMPORTANT/CAUTION as Info/Danger.
    head = f'!!! {TYPES[match[1]]} "{match[1].capitalize()}"\n'
    return head + "".join(f"    {line}\n".rstrip() + "\n" for line in body)


def on_page_markdown(markdown: str, **_) -> str:
    return ALERT.sub(_admonition, markdown)
