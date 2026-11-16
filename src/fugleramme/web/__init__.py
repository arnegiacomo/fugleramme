"""The kiosk and admin views: routing in `server`, the admin page in `admin`."""

from __future__ import annotations

import os
from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# The door (#52). Here rather than in `server`, because the pages name it too and
# `admin` cannot import the module that imports it.
LOGIN = "/admin/login"
LOGOUT = "/admin/logout"


def base_path(raw: str) -> str:
    """`/a/b` for any spelling of a prefix, empty for none."""
    return "".join(f"/{segment}" for segment in raw.split("/") if segment)


# Where a reverse proxy serves the frame, when it does not serve it at the root.
BASE_PATH = base_path(os.environ.get("FUGLERAMME_BASE_PATH", ""))
