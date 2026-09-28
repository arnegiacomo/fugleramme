<!--
The title is the commit message - PRs are squashed. Conventional commits, with
the issue number if there is one:

  chore(assets): add Sturnus unicolor     <- artwork is chore, never fix
  feat: #23 add a mic-less display mode
  fix: #44 keep long names from clipping the label
  docs: fix the passepartout measurements
-->

## What this changes



<!-- If it touches the panel, the buttons or the install scripts, say what you
ran it on - I can only test the hardware I have. -->

## Checks

- [ ] `uv run ruff format && uv run ruff check && uv run mypy && uv run pytest -q`
- [ ] `uv.lock` committed, if `pyproject.toml` changed

<!-- ─────────────  ARTWORK ONLY - delete this section otherwise  ───────────── -->

## Artwork

- [ ] Many birds? - split a bigger batch into several PRs
- [ ] Cut from a real plate, nothing AI-generated (retouching a scan is fine)
- [ ] Licensing is public domain or compatible with the style folder's own terms
- [ ] Added with `tools/add_bird.py`, halo per [Adding artwork](../docs/adding-artwork.md)
- [ ] Shipped as WebP - `add_bird.py` writes it, whatever you hand it
- [ ] `manifest.json` entry per file; `ATTRIBUTION.md` entry and manifest key if the source is new
- [ ] `geometry.json` entry per file, boxing the main bird alone - not the perch, the ground or a second bird

Plate(s) it came from:

<!-- A preview of each bird on the page is nice to have. A bot also comments a web and dithered panel collage of the birds you added on the PR. -->
