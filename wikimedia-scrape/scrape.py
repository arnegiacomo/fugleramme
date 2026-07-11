"""Download a source's Commons plates, naming each file after the bird's Latin
binomial (`genus-species.jpg`, duplicates get `-2`, `-3`, ... in one shared
namespace).

    python scrape.py vonwright        # -> originals/vonwright/
    python scrape.py gould
    python scrape.py all

Resumable: skips files already downloaded.
"""
import os
import sys
import time
from pathlib import Path

from common import commons
from common.naming import Variants
from sources import ALL

ORIGINALS = Path(__file__).resolve().parent / "originals"

# Skip low-resolution re-uploads (thumbnails): the real plate scans are
# ~1800px+ on the short edge, the junk is <900. Measured from Commons' reported
# size before download, so junk never lands. Filenames don't record which was
# dropped, so this must be permissive enough to keep every genuine scan.
MIN_EDGE = 900


def scrape(source):
    out_dir = ORIGINALS / source.NAME
    out_dir.mkdir(parents=True, exist_ok=True)

    titles = commons.list_files(source.CATEGORIES)
    print(f"[{source.NAME}] category: {len(titles)} files")

    info = {}
    for i in range(0, len(titles), 50):
        info.update(commons.image_info(titles[i:i + 50]))
        time.sleep(0.3)

    variants = Variants()
    plan, dropped = [], []
    for name, title in source.plan(info):
        meta = info[title]
        if not meta["mime"].startswith("image/"):   # skip PDFs and other media
            dropped.append(f"{title.replace('File:', '')} ({meta['mime']})")
            continue
        if min(meta["width"], meta["height"]) < MIN_EDGE:
            dropped.append(f"{title.replace('File:', '')} "
                           f"({meta['width']}x{meta['height']})")
            continue
        plan.append((variants.assign(name, title), meta["url"]))
    if dropped:
        print(f"[{source.NAME}] dropped {len(dropped)} below {MIN_EDGE}px: "
              + ", ".join(dropped))

    ok = err = skip = 0
    for fname, url in plan:
        dest = out_dir / fname
        if dest.exists() and dest.stat().st_size > 1000:
            skip += 1; continue
        try:
            dest.write_bytes(commons.fetch(url))
            ok += 1; time.sleep(0.4)
        except Exception as e:
            err += 1; print("ERR", fname, str(e)[:60])
    print(f"[{source.NAME}] done: downloaded={ok} skipped={skip} "
          f"errors={err} total={len(plan)}")


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {*ALL, "all"}:
        sys.exit(f"usage: python scrape.py {{{'|'.join([*ALL, 'all'])}}}")
    targets = ALL.values() if sys.argv[1] == "all" else [ALL[sys.argv[1]]]
    for source in targets:
        scrape(source)


if __name__ == "__main__":
    main()
