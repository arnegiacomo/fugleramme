"""Style-folder selection: discovery, resolution of a saved selection against
what's on disk, a species' variants (and the empty page's perches) within the
active style, and the manifest naming the plate each file was cut from."""

from __future__ import annotations

import json
import os

from fugleramme.names import (
    BIRDS,
    MANIFEST,
    PERCHES,
    available_styles,
    image_for,
    origin_of,
    perches_for,
    resolve,
    source_of,
    variants_for,
)
from fugleramme.picks import Picks


def _make(images_dir, style, *stems):
    d = images_dir / style / BIRDS
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


def _manifest(images_dir, style, record):
    (images_dir / style / MANIFEST).write_text(json.dumps(record))


def test_provenance_comes_from_the_styles_manifest(tmp_path):
    _make(tmp_path, "classic", "turdus-merula", "turdus-merula-2")
    _manifest(
        tmp_path,
        "classic",
        {
            "birds/turdus-merula.png": {"source": "gould", "url": "https://example.org/a"},
            "birds/turdus-merula-2.png": {"source": "vonwright", "url": "https://example.org/b"},
        },
    )
    pngs = variants_for("Turdus merula", tmp_path, "classic")
    assert [source_of(p) for p in pngs] == ["gould", "vonwright"]
    assert [origin_of(p) for p in pngs] == ["https://example.org/a", "https://example.org/b"]


def test_a_perch_is_keyed_by_its_path_under_the_style(tmp_path):
    # One manifest per style, so a subfolder's files carry their folder in the key.
    _make(tmp_path, "classic", "turdus-merula")
    perches = tmp_path / "classic" / PERCHES
    perches.mkdir()
    (perches / "birch-twig.png").write_bytes(b"")
    _manifest(
        tmp_path,
        "classic",
        {"perches/birch-twig.png": {"source": "vonwright", "url": "https://example.org/p"}},
    )
    perch = perches_for(tmp_path, "classic")[0]
    assert source_of(perch) == "vonwright"
    assert origin_of(perch) == "https://example.org/p"


def test_an_entry_may_carry_a_source_and_no_url(tmp_path):
    # Not every plate has a page to cite; the work it came from still holds.
    _make(tmp_path, "classic", "turdus-merula")
    _manifest(tmp_path, "classic", {"birds/turdus-merula.png": {"source": "gould"}})
    assert source_of(tmp_path / "classic" / BIRDS / "turdus-merula.png") == "gould"
    assert origin_of(tmp_path / "classic" / BIRDS / "turdus-merula.png") == ""


def test_a_style_with_no_manifest_resolves_cleanly(tmp_path):
    # A hand-filled `custom/` ships nothing but images; that is not a failure.
    _make(tmp_path, "custom", "turdus-merula")
    assert source_of(tmp_path / "custom" / BIRDS / "turdus-merula.png") == ""
    assert origin_of(tmp_path / "custom" / BIRDS / "turdus-merula.png") == ""


def test_a_file_the_manifest_omits_has_no_provenance(tmp_path):
    _make(tmp_path, "classic", "turdus-merula", "corvus-corax")
    _manifest(tmp_path, "classic", {"birds/turdus-merula.png": {"source": "gould"}})
    assert source_of(tmp_path / "classic" / BIRDS / "corvus-corax.png") == ""


def test_an_entry_that_is_not_a_record_is_dropped(tmp_path):
    # The shape changed once already; a leftover string must not crash a render.
    _make(tmp_path, "classic", "turdus-merula", "corvus-corax")
    _manifest(
        tmp_path,
        "classic",
        {
            "birds/turdus-merula.png": "gould/turdus-merula.png",
            "birds/corvus-corax.png": {"source": "gould"},
        },
    )
    assert source_of(tmp_path / "classic" / BIRDS / "turdus-merula.png") == ""
    assert source_of(tmp_path / "classic" / BIRDS / "corvus-corax.png") == "gould"


def test_a_rewritten_manifest_is_read_again(tmp_path):
    # Cached per folder, so an edit under the running frame has to invalidate it.
    _make(tmp_path, "classic", "turdus-merula")
    path = tmp_path / "classic" / BIRDS / "turdus-merula.png"
    _manifest(tmp_path, "classic", {"birds/turdus-merula.png": {"source": "gould"}})
    assert source_of(path) == "gould"
    _manifest(tmp_path, "classic", {"birds/turdus-merula.png": {"source": "vonwright"}})
    manifest_path = tmp_path / "classic" / MANIFEST
    os.utime(manifest_path, (0, manifest_path.stat().st_mtime + 1))
    assert source_of(path) == "vonwright"


def test_a_broken_manifest_is_not_fatal(tmp_path):
    _make(tmp_path, "classic", "turdus-merula")
    (tmp_path / "classic" / MANIFEST).write_text("{ not json")
    assert source_of(tmp_path / "classic" / BIRDS / "turdus-merula.png") == ""
