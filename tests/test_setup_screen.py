"""The Wi-Fi setup screen (#308): a code a phone can join from, in black and white."""

from __future__ import annotations

import pytest

from fugleramme.render.dither import monochrome
from fugleramme.render.setup import setup_page, wifi_qr


def test_the_join_code_escapes_what_the_wifi_format_reserves():
    assert wifi_qr("Fugleramme-A215", "") == "WIFI:T:nopass;S:Fugleramme-A215;;"
    assert wifi_qr("Fugleramme-A215", 'a\\b;c,d"e:f') == (
        'WIFI:T:WPA;S:Fugleramme-A215;P:a\\\\b\\;c\\,d\\"e\\:f;;'
    )


@pytest.mark.parametrize("size", [(800, 480), (480, 800), (1600, 1200), (1200, 1600)])
def test_it_fills_the_page_at_any_shape(size):
    page = setup_page(size, (0.1, 0, 0.1, 0), "Fugleramme-A215", "", "http://10.42.0.1", "x")
    assert page.mode == "1"
    assert page.size == size
    assert page.getbbox() is not None  # inverted: the ink


def test_on_the_panel_it_stays_two_colours():
    page = setup_page((800, 480), (0, 0, 0, 0), "Fugleramme-A215", "secret12", "http://10.42.0.1")
    assert {index for _, index in monochrome(page).getcolors()} == {0, 1}  # black, white
