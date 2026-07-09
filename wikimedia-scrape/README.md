# wikimedia-scrape

Scrapes the Wikimedia Commons category
[Svenska fåglar (von Wright)](https://commons.wikimedia.org/wiki/Category:Svenska_f%C3%A5glar_(von_Wright))
into transparent-background bird cut-outs. Approximate - some images may need
manual touch-ups.

## Scripts

- **`scrape.py`** - downloads every plate to `wikimedia-scrape/originals/`
  (gitignored), named by Latin binomial (`genus-species.jpg`, duplicates get
  `-2`, `-3`, ...).
- **`remove_background.py`** - writes `assets/birds/<name>.png`, per image:
  - crops off the species-name caption (found via the empty paper gap above it);
  - masks the subject with a color-key flood-fill unioned with a birefnet matte
    (crisp leaf edges + solid white birds);
  - keeps the artist signature (dark ink above the crop), drops paper specks;
  - leaves a `BUFFER_PX` (50 px) ring of the original image around the subject.

Both are resumable (skip files already produced).

## Usage

Run from anywhere; paths resolve relative to the scripts.

```bash
python3.13 -m venv .venv && source .venv/bin/activate   # 3.14 has no onnxruntime wheels
pip install -r wikimedia-scrape/requirements.txt

python wikimedia-scrape/scrape.py             # -> wikimedia-scrape/originals/
python wikimedia-scrape/remove_background.py  # -> assets/birds/
```

`remove_background.py` downloads the birefnet-general model (~1 GB) on first
run and is CPU-heavy (~3-8 s/image). See `../assets/birds/ATTRIBUTION.md` for
image licensing.
