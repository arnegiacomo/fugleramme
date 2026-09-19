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

- [ ] Cut from a real plate, nothing AI-generated (retouching a scan is fine)
- [ ] Licensing is public domain or compatible with the style folder's own terms
- [ ] Added with `tools/add_bird.py`, halo per [Adding artwork](../docs/adding-artwork.md)
- [ ] Shipped as WebP - `add_bird.py` writes it, whatever you hand it
- [ ] `manifest.json` entry per file; `ATTRIBUTION.md` entry and manifest key if the source is new
- [ ] `geometry.json` entry per file, boxing the main bird alone - not the perch, the ground or a second bird
- [ ] A preview of each bird you are adding, dropped in below

Plate(s) it came from:

Preview:

<!-- The preview is the most useful thing to review, so please don't skip it. A cut can look clean on white and still have a noticable halo on the page.

  uv run python tools/add_bird.py bird.png --preview /tmp/check.png --dry-run

That renders the bird on paper. Drag the PNG into the space above. A photo of it on your own frame is just as good. -->
