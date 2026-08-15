"""Style-folder selection: discovery, resolution of a saved selection against
what's on disk, and a species' variants (and the empty page's perches) within
the active style."""

from __future__ import annotations

from fugleramme.names import (
    PERCHES,
    available_styles,
    image_for,
    perches_for,
    resolve,
    variants_for,
)
from fugleramme.picks import Picks


def _make(images_dir, style, *stems):
    d = images_dir / style
    d.mkdir(parents=True, exist_ok=True)
    for stem in stems:
        (d / f"{stem}.png").write_bytes(b"x")


def test_available_styles_lists_only_folders(tmp_path):
    _make(tmp_path, "classic", "turdus-merula")
    _make(tmp_path, "custom", "turdus-merula")
    (tmp_path / "ATTRIBUTION.md").write_text("x")
    assert available_styles(tmp_path) == ["classic", "custom"]


def test_an_empty_style_is_not_offered(tmp_path):
    # A `custom/` waiting to be filled must not be selectable - it would blank the frame.
    _make(tmp_path, "classic", "turdus-merula")
    (tmp_path / "custom").mkdir()
    (tmp_path / "custom" / "README.md").write_text("drop art here")
    assert available_styles(tmp_path) == ["classic"]

    # Perches alone are not a style either: there would be no birds to draw.
    (tmp_path / "custom" / PERCHES).mkdir()
    (tmp_path / "custom" / PERCHES / "birch-twig.png").write_bytes(b"x")
    assert available_styles(tmp_path) == ["classic"]

    _make(tmp_path, "custom", "corvus-corax")
    assert available_styles(tmp_path) == ["classic", "custom"]


def test_resolve_empty_or_stale_falls_back_to_the_first_present(tmp_path):
    _make(tmp_path, "classic", "turdus-merula")
    _make(tmp_path, "custom", "turdus-merula")
    assert resolve("", tmp_path) == "classic"  # unset -> first present
    assert resolve("ghost", tmp_path) == "classic"  # renamed away -> first present
    assert resolve("custom", tmp_path) == "custom"  # honoured


def test_resolve_is_empty_with_no_artwork_at_all(tmp_path):
    assert resolve("classic", tmp_path) == ""


def test_variants_are_the_styles_own_numbered_files(tmp_path):
    _make(tmp_path, "classic", "turdus-merula", "turdus-merula-2", "turdus-merula-3")
    _make(tmp_path, "custom", "turdus-merula")
    assert [p.stem for p in variants_for("Turdus merula", tmp_path, "classic")] == [
        "turdus-merula",
        "turdus-merula-2",
        "turdus-merula-3",
    ]
    # No union across styles: only the active one is drawn from.
    assert [p.stem for p in variants_for("Turdus merula", tmp_path, "custom")] == ["turdus-merula"]
    assert variants_for("Turdus merula", tmp_path, "") == []


def test_variants_exclude_a_hybrid_file(tmp_path):
    _make(tmp_path, "classic", "tetrao-urogallus", "tetrao-urogallus-x-lagopus-lagopus")
    assert [p.stem for p in variants_for("Tetrao urogallus", tmp_path, "classic")] == [
        "tetrao-urogallus"
    ]


def test_image_for_is_none_when_the_active_style_has_nothing(tmp_path):
    _make(tmp_path, "classic", "turdus-merula")
    _make(tmp_path, "custom", "corvus-corax")
    picks = Picks(tmp_path / "artwork.json")
    assert image_for("Turdus merula", tmp_path, "classic", picks).stem == "turdus-merula"
    assert image_for("Turdus merula", tmp_path, "custom", picks) is None
    assert image_for("Corvus corax", tmp_path, "classic", picks) is None
    assert image_for("Turdus merula", tmp_path, "", picks) is None


def test_perches_come_from_the_active_style(tmp_path):
    _make(tmp_path, "classic", "turdus-merula")
    (tmp_path / "classic" / PERCHES).mkdir()
    (tmp_path / "classic" / PERCHES / "birch-twig.png").write_bytes(b"x")
    _make(tmp_path, "custom", "turdus-merula")
    assert [p.name for p in perches_for(tmp_path, "classic")] == ["birch-twig.png"]
    # A style with none draws none rather than borrowing the other style's hand.
    assert perches_for(tmp_path, "custom") == []
    assert perches_for(tmp_path, "") == []


def test_a_perch_folder_is_not_mistaken_for_a_species(tmp_path):
    _make(tmp_path, "classic")
    (tmp_path / "classic" / PERCHES).mkdir()
    assert variants_for("Perches", tmp_path, "classic") == []
