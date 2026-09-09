"""Which birds make the page (#53).

A busy station hears more species than one sheet can hold. The admin's limit and
ranking decide which ones it keeps; the frame holds no ceiling of its own.
"""

from __future__ import annotations

from PIL import Image

from fugleramme.names import normalize
from fugleramme.picks import Picks
from fugleramme.render import collage
from fugleramme.render.collage import RANK_RAREST, RANK_RAREST_EVER
from fugleramme.settings import DEFAULT_LIMIT, Settings


class _Counted:
    """Just enough of a Source for gather_entries: who was heard, how often,
    and how often ever (`hours` of 0) where the two differ."""

    def __init__(self, counts: dict[str, int], ever: dict[str, int] | None = None):
        self._counts = counts
        self._ever = ever or counts

    def species_since(self, hours: int = 24) -> list[tuple[str, int]]:
        counts = self._ever if hours == 0 else self._counts
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))


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


def test_show_all_keeps_every_species_the_window_holds(tmp_path):
    """The removed ceiling would have trimmed this to forty."""
    names = _garden(tmp_path, 60)
    kept = _on_page(tmp_path, names)

    assert kept == sorted(names)


def test_a_limit_keeps_the_most_heard_by_default(tmp_path):
    names = _garden(tmp_path, 20)
    assert _on_page(tmp_path, names, limit=5) == sorted(names[-5:])


def test_the_rarest_ranking_keeps_the_other_end(tmp_path):
    """What the request was for: the residents are the same every day, so the
    visitor worth seeing is the one at the bottom of the list."""
    names = _garden(tmp_path, 20)
    assert _on_page(tmp_path, names, limit=5, ranking=RANK_RAREST) == sorted(names[:5])


def test_the_all_time_rarest_ranks_on_the_record_not_the_window(tmp_path):
    """Heard equally today, the surprise is the one the station has barely ever
    logged - which only the record knows."""
    names = _garden(tmp_path, 4)
    lately = dict.fromkeys(names, 2)  # nothing to separate them in the window
    ever = dict.fromkeys(names, 500) | {names[1]: 3}
    source = _Counted(lately, ever)

    def kept(ranking):
        return collage.selected_species(source, tmp_path, "classic", limit=1, ranking=ranking)

    assert kept(RANK_RAREST_EVER) == [names[1]]
    assert kept(RANK_RAREST) == [names[0]]  # a window tie falls back to the name


def test_a_limit_keeps_exactly_that_many_and_a_fresh_frame_carries_one(tmp_path):
    names = _garden(tmp_path, 60)
    assert Settings().species_limit == DEFAULT_LIMIT
    assert len(_on_page(tmp_path, names, limit=10)) == 10
    assert len(_on_page(tmp_path, names, limit=45)) == 45
    assert len(_on_page(tmp_path, names, limit=collage.NO_LIMIT)) == 60


def test_the_ranking_has_no_say_without_a_limit(tmp_path):
    """Every bird is on the page anyway, which is why the admin greys it out."""
    names = _garden(tmp_path, 60)
    assert _on_page(tmp_path, names, ranking=RANK_RAREST) == _on_page(tmp_path, names)


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
