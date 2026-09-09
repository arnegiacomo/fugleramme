"""Which birds make the page (#53).

A busy station hears more species than one sheet can hold. The admin's limit and
ranking decide which ones it keeps, and the frame's own ceiling - MAX_BIRDS, a
render budget - spends itself on the most heard rather than the first by name.
"""

from __future__ import annotations

from PIL import Image

from fugleramme.names import normalize
from fugleramme.picks import Picks
from fugleramme.render import collage
from fugleramme.render.collage import RANK_RAREST


class _Counted:
    """Just enough of a Source for gather_entries: who was heard, how often."""

    def __init__(self, counts: dict[str, int]):
        self._counts = counts

    def species_since(self, hours: int = 24) -> list[tuple[str, int]]:
        return sorted(self._counts.items(), key=lambda kv: (-kv[1], kv[0]))


def _garden(tmp_path, count: int, drawn: int | None = None) -> list[str]:
    """`count` species, the i-th heard i+1 times, so the busiest sort last by
    name. Only the first `drawn` of them get a plate."""
    birds = tmp_path / "classic" / "birds"
    birds.mkdir(parents=True, exist_ok=True)
    names = [f"Testus sp{i:02d}" for i in range(count)]
    for name in names[: count if drawn is None else drawn]:
        Image.new("RGBA", (20, 16), (30, 30, 30, 255)).save(birds / f"{normalize(name)}.png")
    return names


def _on_page(tmp_path, names: list[str], **kwargs) -> list[str]:
    source = _Counted({name: i + 1 for i, name in enumerate(names)})
    return collage.selected_species(source, tmp_path, "classic", **kwargs)


def test_the_frames_own_ceiling_keeps_the_most_heard_not_the_first_by_name(tmp_path):
    """Cutting by name instead retired the busiest bird in the garden for being
    called Turdus rather than Anas."""
    names = _garden(tmp_path, collage.MAX_BIRDS + 5)
    kept = _on_page(tmp_path, names)

    assert set(kept) == set(names[-collage.MAX_BIRDS :])  # the busiest, not the first
    assert kept == sorted(kept)  # and still handed over in name order


def test_a_limit_keeps_the_most_heard_by_default(tmp_path):
    names = _garden(tmp_path, 20)
    assert _on_page(tmp_path, names, limit=5) == sorted(names[-5:])


def test_the_rarest_ranking_keeps_the_other_end(tmp_path):
    """What the request was for: the residents are the same every day, so the
    visitor worth seeing is the one at the bottom of the list."""
    names = _garden(tmp_path, 20)
    assert _on_page(tmp_path, names, limit=5, ranking=RANK_RAREST) == sorted(names[:5])


def test_no_limit_is_the_default_and_still_answers_to_the_frames_ceiling(tmp_path):
    names = _garden(tmp_path, collage.MAX_BIRDS + 5)
    assert len(_on_page(tmp_path, names)) == collage.MAX_BIRDS
    assert len(_on_page(tmp_path, names, limit=collage.NO_LIMIT)) == collage.MAX_BIRDS
    assert len(_on_page(tmp_path, names, limit=10)) == 10


def test_the_ranking_has_no_say_until_there_is_a_limit(tmp_path):
    """The admin greys the ranking out under "No limit", so a saved "rarest"
    must not quietly decide which forty a busy station gets."""
    names = _garden(tmp_path, collage.MAX_BIRDS + 5)
    by_default = _on_page(tmp_path, names)
    assert _on_page(tmp_path, names, ranking=RANK_RAREST) == by_default
    assert set(by_default) == set(names[-collage.MAX_BIRDS :])


def test_a_species_with_no_artwork_never_takes_a_place_from_one_that_has_it(tmp_path):
    # The loudest bird in the garden, and the style cannot draw it. Dropping it
    # after the limit rather than before would spend a place on nothing.
    names = _garden(tmp_path, 12, drawn=11)
    loudest = names[-1]

    kept = _on_page(tmp_path, names, limit=5)

    assert loudest not in kept
    assert kept == sorted(names[6:11])  # the five busiest it can actually draw


def test_the_entries_carry_the_artwork_each_selected_bird_is_wearing(tmp_path):
    names = _garden(tmp_path, 6)
    source = _Counted({name: i + 1 for i, name in enumerate(names)})

    entries = collage.gather_entries(
        source, tmp_path, "classic", Picks(tmp_path / "artwork.json"), limit=3
    )

    assert [name for name, _path in entries] == sorted(names[-3:])
    assert all(path is not None for _name, path in entries)
