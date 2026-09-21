"""The kiosk and admin views: routing in `server`, the admin page in `admin`."""

from __future__ import annotations

from pathlib import Path

STATIC_DIR = Path(__file__).resolve().parent / "static"

# The door (#52). Here rather than in `server`, because the pages name it too and
# `admin` cannot import the module that imports it.
LOGIN = "/admin/login"
LOGOUT = "/admin/logout"
