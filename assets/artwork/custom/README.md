# custom artwork

Your own artwork style. Select **Custom** in the admin UI (`:8080/admin`) to use
it - one style is active at a time.

- Transparent PNGs in `birds/`, named for the scientific name:
  `turdus-merula.png`. It must be a name BirdNET-Go can emit
  (`assets/birdnet_labels_v2.4.txt`).
- Several per bird: `turdus-merula-2.png`, `-3`, ... One is picked and kept for
  as long as that bird is in the window.
- `perches/` holds the bare branches for when nothing has been heard.
- `ATTRIBUTION.md` if you share the style, as `classic/` has.
