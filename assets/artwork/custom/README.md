# custom artwork

Your own artwork style. Select **Custom** in the admin UI (`:8080/admin`) to use
it - one style is active at a time.

- Transparent WebP or PNG in `birds/`, named for the scientific name:
  `turdus-merula.webp`. It must be a name BirdNET-Go can emit
  (`assets/birdnet_labels_v2.4.txt`). `tools/add_bird.py` writes WebP for you.
- Several per bird: `turdus-merula-2.webp`, `-3`, ... One is picked and kept for
  as long as that bird is in the window.
- `perches/` holds the bare branches for when nothing has been heard.
- Every shared image needs a `manifest.json` entry naming its source, and an
  `ATTRIBUTION.md` entry describing that source and its terms, as `classic/` has.
