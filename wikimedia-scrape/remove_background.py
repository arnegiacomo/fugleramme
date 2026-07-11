"""Key out a source's downloaded plates into transparent cut-outs for manual
review, then curate the good ones into `../assets/birds/` by hand.

    python remove_background.py vonwright   # originals/vonwright/ -> staging/vonwright/
    python remove_background.py gould
    python remove_background.py all

Resumable: skips cut-outs already produced. First run downloads the
birefnet-general model (~1 GB) and is CPU-heavy (~3-8 s/image).
"""
import sys
from pathlib import Path

from common import background
from sources import ALL

HERE = Path(__file__).resolve().parent
ORIGINALS = HERE / "originals"
STAGING = HERE / "staging"


def run(source):
    print(f"[{source.NAME}] keying out -> staging/{source.NAME}/")
    background.process(ORIGINALS / source.NAME, STAGING / source.NAME,
                       **getattr(source, "BG", {}))


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {*ALL, "all"}:
        sys.exit(f"usage: python remove_background.py {{{'|'.join([*ALL, 'all'])}}}")
    targets = ALL.values() if sys.argv[1] == "all" else [ALL[sys.argv[1]]]
    for source in targets:
        run(source)


if __name__ == "__main__":
    main()
