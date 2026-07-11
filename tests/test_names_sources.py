"""Source-folder selection (#8/#2): discovery, resolution of a saved selection
against what's on disk, and variant union across active sources."""

from __future__ import annotations

from fugleramme.names import available_sources, image_for, resolve, variants_for


def _make(images_dir, source, *stems):
    d = images_dir / source
    d.mkdir(parents=True, exist_ok=True)
    for stem in stems:
        (d / f"{stem}.png").write_bytes(b"x")


def test_available_sources_lists_only_folders(tmp_path):
    _make(tmp_path, "vonwright", "turdus-merula")
    _make(tmp_path, "gould", "turdus-merula")
    (tmp_path / "ATTRIBUTION.md").write_text("x")
    assert available_sources(tmp_path) == ["gould", "vonwright"]


def test_resolve_empty_or_stale_falls_back_to_all(tmp_path):
    _make(tmp_path, "vonwright", "turdus-merula")
    _make(tmp_path, "gould", "turdus-merula")
    assert resolve((), tmp_path) == ["gould", "vonwright"]          # empty -> all
    assert resolve(("ghost",), tmp_path) == ["gould", "vonwright"]  # none present -> all
    assert resolve(("gould",), tmp_path) == ["gould"]               # honoured
    assert resolve(("gould", "ghost"), tmp_path) == ["gould"]       # stale dropped


def test_variants_union_across_active_sources(tmp_path):
    _make(tmp_path, "vonwright", "turdus-merula", "turdus-merula-2")
    _make(tmp_path, "gould", "turdus-merula")
    both = variants_for("Turdus merula", tmp_path, ["gould", "vonwright"])
    assert {p.parent.name for p in both} == {"gould", "vonwright"}
    assert len(both) == 3
    one = variants_for("Turdus merula", tmp_path, ["gould"])
    assert [p.parent.name for p in one] == ["gould"]


def test_variant_regex_excludes_hybrid(tmp_path):
    _make(tmp_path, "vonwright", "tetrao-urogallus", "tetrao-urogallus-x-lagopus-lagopus")
    matches = variants_for("Tetrao urogallus", tmp_path, ["vonwright"])
    assert [p.stem for p in matches] == ["tetrao-urogallus"]


def test_image_for_none_when_absent_in_active_sources(tmp_path):
    _make(tmp_path, "gould", "turdus-merula")
    assert image_for("Turdus merula", tmp_path, ["vonwright"]) is None
