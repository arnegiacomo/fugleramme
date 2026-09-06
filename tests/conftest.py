"""The fake BirdNET-Go, as a fixture: the tests reach it over the same /api/v2
a real detector serves."""

from __future__ import annotations

import pytest

from fugleramme import fake, languages
from fugleramme.api import ApiSource
from fugleramme.render import collage


@pytest.fixture(autouse=True)
def _clean_language_caches(monkeypatch):
    """Module globals, so one test's detector must not leak into the next."""
    monkeypatch.setattr(languages, "_source", None)
    monkeypatch.setattr(languages, "_catalog", None)
    monkeypatch.setattr(languages, "_dicts", {})


@pytest.fixture(autouse=True)
def _no_cached_layouts():
    """A module global, so one test's packing must not answer for the next."""
    collage._layouts.clear()


@pytest.fixture
def detector():
    """Start a fake on an OS-assigned port; `rows` replaces the generated ones.
    Returns (base URL, server) - the row list is live, so appending to it is
    what a new detection looks like."""
    servers = []

    def start(rows=None, count: int = 40, seed: int = 1, **kwargs):
        httpd = fake.serve(
            fake.generate(count, seed) if rows is None else rows, "127.0.0.1", 0, **kwargs
        )
        servers.append(httpd)
        return f"http://127.0.0.1:{httpd.server_address[1]}", httpd

    yield start
    for httpd in servers:
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def source(detector):
    """An ApiSource over a fresh fake."""

    def start(**kwargs) -> ApiSource:
        url, _httpd = detector(**kwargs)
        return ApiSource(url)

    return start
