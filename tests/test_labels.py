"""Species-label invariants: every offered font is present and usable, a label
packs as part of its bird rather than on top of the page, and a page too full to
name loses the names rather than the birds."""

from __future__ import annotations

from unittest.mock import patch

import numpy as np
import pytest
from PIL import Image, ImageFont

from fugleramme.render import collage, fonts
from fugleramme.render.collage import _pack, _probes, _Sprite, _with_label, render_collage
from fugleramme.render.page import INK, PANEL_INK, label_px, stamp, text_mask
from fugleramme.render.paper import TARGET_PAPER


@pytest.fixture(autouse=True)
def _no_cached_layouts():
    collage._layouts.clear()


def _ink(font, text="Turdus merula") -> float:
    return float(np.asarray(text_mask(text, font, flat=True)).mean())


@pytest.mark.parametrize("key", sorted(fonts.FONTS))
def test_every_font_is_pinned_to_book_weight(key):
    _name, filename = fonts.FONTS[key]
    raw = ImageFont.truetype(str(fonts.FONTS_DIR / filename), 26)
    variable = True
    try:
        raw.get_variation_axes()
    except OSError:
        variable = False  # static: nothing to pin, the raw face is already book weight

    loaded = _ink(fonts.load(key, 26))
    assert loaded >= _ink(raw)
    if variable:
        # Bitter's fvar default is Thin; without pinning it renders far lighter.
        assert loaded > 30


def test_unknown_font_falls_back_to_the_default_file():
    assert fonts.load("nope", 20).path == fonts.load(fonts.DEFAULT_FONT, 20).path
    assert fonts.load("bitter", 20).path != fonts.load(fonts.DEFAULT_FONT, 20).path


def test_flat_label_has_no_intermediate_alpha():
    font = fonts.load(fonts.DEFAULT_FONT, 26)
    flat = set(np.unique(np.asarray(text_mask("Pica pica", font, flat=True))))
    smooth = set(np.unique(np.asarray(text_mask("Pica pica", font, flat=False))))
    assert flat <= {0, 255}
    assert not smooth <= {0, 255}  # the screen keeps its antialiasing


def test_panel_names_are_stamped_in_exact_palette_black():
    # Anything but exact black would be re-dithered into colour speckle.
    for textured, expected in ((False, PANEL_INK), (True, INK)):
        canvas = Image.new("RGB", (20, 20), (255, 255, 255))
        stamp(canvas, Image.new("L", (6, 4), 255), (2, 3), textured)
        assert canvas.getpixel((2, 3)) == expected


def test_a_second_language_stacks_centred_under_the_first():
    font = fonts.load(fonts.DEFAULT_FONT, 26)
    one = text_mask("Svarttrost", font, flat=True)
    two = text_mask("Svarttrost\n(Turdus merula)", font, flat=True)

    assert two.height > one.height * 2  # two lines plus the leading between them
    assert two.width > one.width  # the wider line sets the box

    rows = np.asarray(two).any(axis=1)
    inked = rows.nonzero()[0]
    assert not rows[inked.min() : inked.max()].all()  # blank rows separate the lines
    assert np.asarray(two).nonzero()[1].mean() == pytest.approx(two.width / 2, abs=2)


def test_label_size_scales_with_the_short_side():
    assert label_px(1600, 1200, "small") < label_px(1600, 1200, "xlarge")
    assert label_px(1600, 1200, "medium") == label_px(1200, 1600, "medium")
    assert label_px(400, 300, "nonsense") == label_px(400, 300, fonts.DEFAULT_LABEL_SIZE)


def test_label_reserves_space_in_the_footprint():
    art_mask = np.ones((30, 41), dtype=bool)  # odd width: the centroid is a whole pixel
    sprite = _with_label(0, 41, art_mask, Image.new("L", (90, 12), 255), gap=5)

    assert sprite.mask.shape == (30 + 5 + 12, 90)  # the label is wider than the bird
    assert sprite.art_at == (25, 0)  # bird centred over the label
    assert sprite.label_at == (0, 35)
    assert sprite.mask[35:, :].all()  # the label box is reserved
    assert not sprite.mask[30:35, :].any()  # the gap is not


@pytest.mark.parametrize("label_width", range(60, 70))
def test_reserved_box_always_covers_the_drawn_label(label_width):
    # Rounding the two edges separately used to leave the mask a column short.
    sprite = _with_label(
        0, 57, np.ones((20, 57), dtype=bool), Image.new("L", (label_width, 8), 255), gap=3
    )
    lx, top = sprite.label_at
    assert lx >= 0 and lx + label_width <= sprite.mask.shape[1]
    assert sprite.mask[top : top + 8, lx : lx + label_width].all()


def test_label_tucks_up_under_the_silhouette():
    # A body over one leg: the columns the name sits under end at row 20, so it
    # rises there instead of hanging below the leg.
    art_mask = np.zeros((40, 40), dtype=bool)
    art_mask[:20, :] = True
    art_mask[20:, :6] = True
    sprite = _with_label(0, 40, art_mask, Image.new("L", (20, 8), 255), gap=2)

    _lx, top = sprite.label_at
    assert top == 22  # last opaque row under the label, +1, + the gap
    assert sprite.mask.shape[0] == 40  # and the footprint is no taller than the bird


def test_label_centres_on_the_silhouette_not_the_bounding_box():
    # Body on the left, long tail to the right: the name follows the body.
    art_mask = np.zeros((20, 100), dtype=bool)
    art_mask[:, :20] = True
    art_mask[8:12, 20:] = True
    sprite = _with_label(0, 100, art_mask, Image.new("L", (10, 6), 255), gap=1)

    lx, _top = sprite.label_at
    ax, _ay = sprite.art_at
    centre_of_label = lx + 5 - ax
    assert centre_of_label == pytest.approx(art_mask.nonzero()[1].mean(), abs=1)


def test_packing_never_overlaps_a_label():
    sprites = [
        _with_label(n, 30, np.ones((30, 30), dtype=bool), Image.new("L", (60, 10), 255), gap=4)
        for n in range(6)
    ]
    placed = _pack(sprites, 400, 400)
    assert placed is not None

    occupied = np.zeros((400, 400), dtype=bool)
    for sprite, x, y in placed:
        h, w = sprite.mask.shape
        assert not (occupied[y : y + h, x : x + w] & sprite.mask).any()
        occupied[y : y + h, x : x + w] |= sprite.mask


def test_sprite_without_a_label_is_just_the_bird():
    sprite = _Sprite(0, 10, np.ones((10, 10), dtype=bool))
    assert sprite.label_at is None
    assert sprite.art_at == (0, 0)


def _crowded(tmp_path, count=40):
    """A full page of species, each with its own artwork file."""
    art = Image.new("RGBA", (200, 150), (40, 40, 40, 255))
    path = tmp_path / "bird.png"
    art.save(path)
    return [(f"Genus species{n}", path) for n in range(count)]


def test_a_page_too_full_to_name_still_draws_the_birds(tmp_path, caplog):
    # Names used to be rasterised at a fixed size while only the birds shrank, so
    # a full page could not converge and rendered as blank paper.
    page = render_collage(
        _crowded(tmp_path), (400, 300), show_names=True, label_size="xlarge", textured=False
    )
    assert np.asarray(page).std() > 1  # something was drawn


def test_names_shrink_with_the_birds_rather_than_being_dropped(tmp_path, caplog):
    page = render_collage(
        _crowded(tmp_path, count=12),
        (700, 500),
        show_names=True,
        label_size="large",
        textured=False,
    )
    assert (np.asarray(page) == PANEL_INK).all(axis=2).any()  # names made it onto the page
    assert "No layout fits" not in caplog.text


def test_the_same_page_packs_identically_at_every_output_size(tmp_path):
    """The panel and the kiosk draw the same page at different pixel counts, and
    the packer works in whole pixels, so it runs at one size and the placements
    are scaled. Packing at the output size used to swap birds between the two."""
    packed = []
    real = collage._layout

    def spy(*args, **kwargs):
        placed, px = real(*args, **kwargs)
        packed.append(
            (args[5:8], px, [(s.index, s.dim, s.art_at, s.label_at, x, y) for s, x, y in placed])
        )
        return placed, px

    entries = _crowded(tmp_path, count=8)
    with patch.object(collage, "_layout", spy):
        for size in ((1600, 1200), (1920, 1440), (800, 600), (2880, 2160)):
            collage._layouts.clear()  # the cache would otherwise answer for all four
            render_collage(entries, size, show_names=True, textured=False)

    assert len(packed) == 4
    assert packed.count(packed[0]) == 4


def test_the_panel_and_the_kiosk_share_one_pack(tmp_path):
    """Packing is the whole cost of a render and both outputs pack the same, so
    whichever draws first pays for both."""
    entries = _crowded(tmp_path, count=8)
    calls = 0
    real = collage._layout

    def spy(*args, **kwargs):
        nonlocal calls
        calls += 1
        return real(*args, **kwargs)

    with patch.object(collage, "_layout", spy):
        for size, textured in (((1600, 1200), False), ((1920, 1440), True), ((2880, 2160), True)):
            render_collage(entries, size, show_names=True, textured=textured)
    assert calls == 1

    # A different page still packs: the key is the species and their artwork.
    with patch.object(collage, "_layout", spy):
        render_collage(_crowded(tmp_path, count=6), (1600, 1200), show_names=True, textured=False)
    assert calls == 2


def test_nothing_is_drawn_against_the_page_edge(tmp_path):
    page = render_collage(_crowded(tmp_path, count=12), (700, 500), show_names=True, textured=False)
    margin = round(min(page.size) * collage._MARGIN)
    band = np.asarray(page).copy()
    band[margin:-margin, margin:-margin] = TARGET_PAPER
    assert (band == TARGET_PAPER).all()


def _perches(tmp_path, count=5):
    """Asymmetric, distinctly-shaded stand-in branches: the shade says which one
    was drawn, the notch says whether it was mirrored."""
    paths = []
    for n in range(count):
        # Kept dark: process_sprite snaps anything pale enough to read as paper
        # to the page tone, which would make two stand-ins indistinguishable.
        shade = 10 + n * 30
        img = Image.new("RGBA", (60, 90), (shade, shade, shade, 255))
        img.paste((255, 255, 255, 0), (0, 0, 20, 20))  # notch one corner only
        path = tmp_path / f"perch{n}.png"
        img.save(path)
        paths.append(path)
    return paths


def _branch(perches, textured):
    """Which branch is on the page, by its shade - tolerant of paper grain."""
    page = np.asarray(
        render_collage([], (300, 220), textured=textured, perches=perches).convert("L")
    )
    return round(float(np.median(page[page < 200])) / 10)


def test_the_empty_page_shows_one_branch_that_both_outputs_agree_on(tmp_path):
    # The perch used to be rolled per render, so the panel froze on whichever it
    # drew and the kiosk showed a different one.
    perches = _perches(tmp_path)
    assert len({_branch(perches, textured=True) for _ in range(4)}) == 1
    assert _branch(perches, textured=True) == _branch(perches, textured=False)


def test_the_branch_turns_over_with_the_day(tmp_path):
    perches = _perches(tmp_path)
    seen = set()
    for day in range(10):
        with patch.object(collage, "day_ordinal", return_value=day):
            page = render_collage([], (300, 220), textured=False, perches=perches)
            seen.add(np.asarray(page).tobytes())
    assert len(seen) == 10  # five branches, each also mirrored


def test_an_empty_page_with_no_perches_is_bare_paper(tmp_path):
    page = render_collage([], (200, 150), textured=False, perches=[])
    assert (np.asarray(page) == TARGET_PAPER).all()


def test_a_probe_is_a_real_row_of_the_sprite():
    """The packer skips the full footprint test whenever a probe row collides.
    That is only sound while a probe is literally a row of the mask at the index
    it claims - anything else would reject positions that were actually free."""
    rng = np.random.default_rng(0)
    for shape in ((40, 25), (3, 90), (120, 7)):
        mask = rng.random(shape) > 0.6
        for row, probe in _probes(mask):
            assert np.array_equal(probe, mask[row])
        # A blank band contributes nothing rather than a row that can never collide.
        assert all(probe.any() for _, probe in _probes(mask))


def test_a_sprite_with_no_opaque_pixels_probes_nothing():
    assert _probes(np.zeros((20, 20), dtype=bool)) == []
