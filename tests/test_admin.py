"""Admin page invariants. The markup, the style and the script are files of
their own now, so only a render proves that the template's slots, the page's
asset links and the values admin.js reads still line up."""

from __future__ import annotations

import json
import re

import pytest

from fugleramme import admin, modes, server
from fugleramme.config import STATIC_DIR
from fugleramme.db import Database
from fugleramme.featured import Featured
from fugleramme.languages import namer
from fugleramme.picks import Picks
from fugleramme.settings import Settings
from fugleramme.status import Status


def _page(tmp_path, **overrides) -> str:
    settings = Settings(**overrides)
    ctx = modes.context(
        Database(tmp_path / "absent.db"), tmp_path, Picks(tmp_path / "artwork.json"),
        Featured(tmp_path / "featured.json"), settings, namer("sci", "", tmp_path),
        settings.web_size(),
    )
    return admin.page(ctx, settings, Status(), None, tmp_path)


@pytest.mark.parametrize("mode", list(modes.MODES))
def test_every_slot_in_the_template_is_filled(tmp_path, mode):
    # substitute raises on a slot with no value; a leftover $ is the other way round.
    assert "$" not in _page(tmp_path, mode=mode)


def test_every_asset_the_page_links_is_one_the_server_serves(tmp_path):
    linked = set(re.findall(r'(?:href|src)="(/[^"?]*)', _page(tmp_path)))
    assert linked == {"/", "/admin.css", "/admin.js"}
    assert linked <= set(server.FILES)


def test_the_config_blob_carries_everything_admin_js_reads(tmp_path):
    """The script is static, so this blob is its only channel from the frame."""
    blob = re.search(
        r'<script id="config"[^>]*>(.*?)</script>', _page(tmp_path), re.DOTALL
    ).group(1)
    used = set(re.findall(r"\bcfg\.(\w+)", (STATIC_DIR / "admin.js").read_text()))
    assert used and used <= set(json.loads(blob))


def test_a_species_with_no_artwork_is_marked_rather_than_dropped(tmp_path):
    name_of = namer("sci", "", tmp_path)
    html = admin.species_html([("Pica pica", "gould"), ("Corvus cornix", None)], name_of)
    assert html.count("<li") == 2
    assert 'class="noart"' in html and "Corvus cornix" in html
    assert admin.species_html([], name_of) == '<li class="empty">none yet</li>'


def test_the_update_row_offers_the_install_only_once_a_release_is_known():
    status = Status()
    assert "Check" in admin._update(status)

    status.update_available = "v9.9.9"
    assert "Install" in admin._update(status)

    status.update_available, status.updating = None, True
    assert "<progress" in admin._update(status)  # no button while it installs
