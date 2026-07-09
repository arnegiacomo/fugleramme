"""One-time migration: rename bird artwork from 1800s von Wright taxonomy to
the modern eBird names that BirdNET-Go emits.

173 of the 267 species stems already match a BirdNET v2.4 label; this maps the
remaining ones. Targets are verified against the vendored label set by
tests/test_artwork_names.py, which is the ongoing consistency guard. Five
species (see EXCEPTIONS in that test) have no BirdNET label at all and keep
their current modern names.

Collisions (an old name whose modern form already exists as a file, or two old
names mapping to one modern name) merge in as numbered variants (-2, -3, ...),
picking the next free slot after any existing variants.

Usage:
    python scripts/rename_artwork.py            # dry-run, prints the plan
    python scripts/rename_artwork.py --apply    # execute via git mv
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

IMAGES = Path("assets/birds")

# old von Wright stem -> modern stem (BirdNET label form, or modern taxonomy
# for the five species BirdNET lacks). Verified against the vendored labels.
MAP = {
    "acanthis-cannabina": "linaria-cannabina",
    "acanthis-flavirostris": "linaria-flavirostris",
    "acanthis-linaria": "acanthis-flammea",
    "acrocephalus-aquaticus": "acrocephalus-paludicola",
    "acrocephalus-streperus": "acrocephalus-scirpaceus",
    "aegithalus-caudatus": "aegithalos-caudatus",
    "alcedo-ispida": "alcedo-atthis",
    "ampelis-garrulus": "bombycilla-garrulus",
    "anas-penelope": "mareca-penelope",
    "anas-querquedula": "spatula-querquedula",
    "anas-strepera": "mareca-strepera",
    "capella-gallinago": "gallinago-gallinago",
    "capella-media": "gallinago-media",
    "carduelis-cannabina": "linaria-cannabina",
    "carduelis-chloris": "chloris-chloris",
    "carduelis-flammea": "acanthis-flammea",
    "carduelis-flavirostris": "linaria-flavirostris",
    "carduelis-spinus": "spinus-spinus",
    "charadrius-pluvialis": "pluvialis-apricaria",
    "chelidon-rustica": "hirundo-rustica",
    "coloeus-monedula": "corvus-monedula",
    "colymbus-arcticus": "gavia-arctica",
    "colymbus-immer": "gavia-immer",
    "colymbus-stellatus": "gavia-stellata",
    "crocethia-alba": "calidris-alba",
    "cyanecula-svecica": "luscinia-svecica",
    "cypselus-apus": "apus-apus",
    "dryobates-leucotus": "dendrocopos-leucotos",
    "dryobates-major": "dendrocopos-major",
    "dryobates-medius": "dendrocoptes-medius",
    "eniconetta-stelleri": "polysticta-stelleri",  # not in BirdNET v2.4
    "falco-aesalon": "falco-columbarius",
    "harelda-hyemalis": "clangula-hyemalis",
    "hippolais-hippolais": "hippolais-icterina",
    "hirundo-urbica": "delichon-urbicum",
    "hydrochelidon-nigra": "chlidonias-niger",
    "lagopus-mutus": "lagopus-muta",
    "larus-glaucus": "larus-hyperboreus",
    "larus-leucopterus": "larus-glaucoides",
    "larus-minutus": "hydrocoloeus-minutus",
    "larus-ridibundus": "chroicocephalus-ridibundus",
    "limicola-falcinellus": "calidris-falcinellus",
    "lobipes-lobatus": "phalaropus-lobatus",
    "miliaria-calandra": "emberiza-calandra",
    "muscicapa-atricapilla": "ficedula-hypoleuca",
    "muscicapa-collaris": "ficedula-albicollis",
    "muscicapa-ficedula": "ficedula-hypoleuca",
    "nannus-troglodytes": "troglodytes-troglodytes",
    "nyctea-scandiaca": "bubo-scandiacus",
    "nyroca-ferina": "aythya-ferina",
    "nyroca-fuligula": "aythya-fuligula",
    "nyroca-marila": "aythya-marila",
    "oidemia-fusca": "melanitta-fusca",
    "oidemia-nigra": "melanitta-nigra",
    "oidemia-perspicillata": "melanitta-perspicillata",
    "otis-tetrax": "tetrax-tetrax",
    "parus-ater": "periparus-ater",
    "parus-atricapillus": "poecile-montanus",  # Willow Tit (historically ambiguous)
    "parus-cinctus": "poecile-cinctus",
    "pavoncella-pugnax": "calidris-pugnax",
    "phalacrocorax-aristotelis": "gulosus-aristotelis",  # not in BirdNET v2.4
    "philomachus-pugnax": "calidris-pugnax",
    "porzana-parva": "zapornia-parva",
    "pratincola-rubetra": "saxicola-rubetra",
    "squatarola-squatarola": "pluvialis-squatarola",
    "sterna-albifrons": "sternula-albifrons",
    "sterna-sandvicensis": "thalasseus-sandvicensis",
    "sula-bassana": "morus-bassanus",
    "sylvia-communis": "curruca-communis",
    "sylvia-curruca": "curruca-curruca",
    "sylvia-nisoria": "curruca-nisoria",
    "totanus-erythropus": "tringa-erythropus",
    "totanus-glareola": "tringa-glareola",
    "totanus-littoreus": "tringa-nebularia",
    "totanus-ochropus": "tringa-ochropus",
    "totanus-totanus": "tringa-totanus",
    "tringa-alpina": "calidris-alpina",
    "tringa-canutus": "calidris-canutus",
    "tringa-ferruginea": "calidris-ferruginea",
    "tringa-maritima": "calidris-maritima",
    "tringa-minuta": "calidris-minuta",
    "tringa-temminckii": "calidris-temminckii",
    "triorchis-lagopus": "buteo-lagopus",
    "turdus-musicus": "turdus-philomelos",  # Song Thrush (historically ambiguous)
    "uria-grylle": "cepphus-grylle",
    "uria-troille": "uria-aalge",
}


def variant_files(stem: str) -> list[Path]:
    """Files for a stem: <stem>.png and <stem>-N.png (numbered only, so a
    species key never sweeps up a hybrid file)."""
    rx = re.compile(rf"{re.escape(stem)}(-\d+)?$")
    return sorted(p for p in IMAGES.glob(f"{stem}*.png") if rx.fullmatch(p.stem))


def slot_name(stem: str, slot: int) -> str:
    return f"{stem}.png" if slot == 1 else f"{stem}-{slot}.png"


def used_slots(stem: str) -> set[int]:
    used = set()
    for p in variant_files(stem):
        m = re.fullmatch(rf"{re.escape(stem)}(?:-(\d+))?", p.stem)
        used.add(int(m.group(1)) if m.group(1) else 1)
    return used


def build_plan() -> list[tuple[Path, Path]]:
    # Group source files by target so intra-set collisions share numbering.
    by_target: dict[str, list[Path]] = {}
    for old, new in MAP.items():
        for f in variant_files(old):
            by_target.setdefault(new, []).append(f)

    plan: list[tuple[Path, Path]] = []
    for target, sources in by_target.items():
        used = used_slots(target)  # slots occupied by existing target files
        next_slot = 1
        for src in sorted(sources):
            while next_slot in used:
                next_slot += 1
            used.add(next_slot)
            plan.append((src, IMAGES / slot_name(target, next_slot)))
    return plan


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="execute via git mv")
    args = parser.parse_args()

    plan = build_plan()
    dests = [new for _, new in plan]
    if len(dests) != len(set(dests)):
        sys.exit("ERROR: duplicate destinations in plan")

    for old, new in plan:
        print(f"{old.name:40s} -> {new.name}")
    print(f"\n{len(plan)} files, {len({n.stem.rstrip('-0123456789') for _, n in plan})}+ target species")

    if not args.apply:
        print("\n(dry-run; pass --apply to execute)")
        return
    for old, new in plan:
        subprocess.run(["git", "mv", str(old), str(new)], check=True)
    print(f"\nrenamed {len(plan)} files")


if __name__ == "__main__":
    main()
