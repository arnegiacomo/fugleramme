# wikimedia-scrape

Scrapes public-domain bird plates from Wikimedia Commons into
transparent-background cut-outs. Approximate - outputs land in a `staging/`
folder for manual review; you curate the good ones into
`../assets/birds/<source>/` by hand (one folder per source, e.g.
`assets/birds/gould/`), which the frame's admin UI then lets you toggle on/off.

## Sources

Each work is a module in `sources/`:

- **`vonwright`** - [Svenska fåglar (von Wright)](https://commons.wikimedia.org/wiki/Category:Svenska_f%C3%A5glar_(von_Wright)).
- **`gould`** - [The Birds of Europe (Gould)](https://commons.wikimedia.org/wiki/Category:The_Birds_of_Europe_(Gould)), Volumes 1-5.

A source declares its Commons categories, a `plan(info)` that resolves each file
to a Latin binomial, and an attribution block. Add a new source by dropping a
module in `sources/` and registering it in `sources/__init__.py`.

## Layout

```
common/      shared machinery: Commons API, name/slug/variant, background pipeline
sources/     one module per work (categories + name parser + attribution)
scrape.py    download plates          -> originals/<source>/   (gitignored)
remove_background.py  key out for review -> staging/<source>/  (gitignored)
```

`common/naming.py` slugs each name to `genus-species` and numbers duplicates
(`-2`, `-3`, ...). Gould reads the `<Genus species> (illustrations)` member
category (falling back to a filename binomial, then a common-name map);
von Wright parses the rawpixel image descriptions.

## Usage

Run from the repo root; paths resolve relative to the scripts.

```bash
uv venv --python 3.13 .venv-rembg            # 3.14 has no onnxruntime wheels
.venv-rembg/bin/pip install -r wikimedia-scrape/requirements.txt

.venv-rembg/bin/python wikimedia-scrape/scrape.py gould            # -> originals/gould/
.venv-rembg/bin/python wikimedia-scrape/remove_background.py gould # -> staging/gould/
# review staging/gould/, then move the good cut-outs into assets/birds/
```

Use `all` in place of a source name to process every source. Both scripts are
resumable (skip files already produced).

`remove_background.py` downloads the birefnet-general model (~1 GB) on first run
and is CPU-heavy (~3-8 s/image). The pipeline is tuned to the von Wright plates;
other sources may need per-source tuning (add a `BG` dict to the source module)
- reviewing `staging/` is where you catch that. See
`../assets/birds/ATTRIBUTION.md` for image licensing.
