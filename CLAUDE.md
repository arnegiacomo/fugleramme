# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Fugleramme is an e-ink bird frame for a Raspberry Pi 5. A USB mic feeds BirdNET-Go (BirdNET v2.4 in Docker), which classifies bird sounds and logs detections to its own SQLite; the frame service reads that DB directly (read-only) and renders the recently seen birds as a collage on the Pimoroni Inky Impression (Spectra 6) panel and serves it over HTTP. The frame stack is Python managed with `uv`, Pillow + numpy for rendering, stdlib `sqlite3` and `http.server`, and the Pi-only `inky` driver. It's deployed and running on a Pi; the frame also runs on a Mac for development (web-only, no panel). Live mic capture and the Inky panel push are Pi-only.

## Commands

```bash
uv sync                                     # create/refresh the venv from the lockfile
uv run fugleramme-frame                     # run the service: render loop + kiosk on 0.0.0.0:8080
uv run fugleramme-dev                       # same, auto-restart on source change
uv run fugleramme-frame --preview out.png   # render the current collage once and exit, no server/panel
uv run python -m fugleramme.seed --count 40 # BirdNET-Go-shaped fixtures: detections + the names cache
uv run python scripts/curate.py             # workstation only: contact sheet on :8081, pick a species' artwork
./setup.sh                                   # Pi only: one-command bootstrap (deps + BirdNET-Go + services)
uv run pytest -q                            # run tests
uv run pytest tests/test_artwork_names.py   # run a single test file
```

Kiosk resolution, rotation, lookback window, kiosk refresh, artwork style, species names (on/off, primary + optional second language, typeface, size) and auto-update are runtime settings in the admin UI (`:8080/admin`, #2), persisted to `--config` (default `detector/data/settings.json`). The panel's own size is never a setting - it comes from the attached Inky. CLI flags are launch-only: `--db`, `--images`, `--config`, `--output`, `--host`, `--port`.

## Architecture

Work is split by concern across GitHub issues: **#1 frame service**, **#2 admin interface** (presentation settings at `/admin`), **#3 detector** (BirdNET-Go + mic), **#7 direct-read refactor**. Each issue is the source of truth for its half.

The two halves meet at the DB file, plus BirdNET-Go's API for names alone. BirdNET-Go (Docker) writes its own normalized SQLite, bind-mounted to a persistent host path (`detector/data`, on NVMe on the Pi); the frame reads that same file directly, read-only. `db.py` is a thin adapter and the only code that knows BirdNET-Go's schema (species come from a `labels`/`label_types` join, timestamps are epoch seconds); it exposes `species_since` / `recent` / `latest` / `stats` so nothing else sees BirdNET-Go SQL. There is no frame-owned DB and no sync process (dropped in #7). WAL lets the render loop and the HTTP server each hold a read connection in one process without contention. Detector detail: [`detector/README.md`](detector/README.md).

**Render once, fan out** (`service.py`): the loop re-renders only when its inputs change - the species in the lookback window, the panel size, the style, the rotation, and the names with their language and typeface - dithers the collage to 6 colors for the panel (`render.py`), and pushes it if a panel is present. The kiosk serves the same collage full-color per request (`server.py`), cached on the same inputs at its own resolution (`collage_key`). If the Inky is absent it logs a warning and runs web-only, the same path as `--preview`.

**The panel sizes itself** (`panel.py`, #4): the loop renders at the attached Inky's own resolution (`FALLBACK_PANEL_RESOLUTION`, the 13.3", when none is attached), so the admin resolution setting only ever governs the kiosk. `settings.rotation` (0/90/180/270, counter-clockwise) shapes both, but only `push` turns pixels: the render is sized as the viewer sees it and the driver takes native landscape only. Color reduction is ours, not the driver's: `inky.set_image` re-dithers anything that is not already a 6-color "P" image, so `render.dither` hands it one whose palette maps 1:1 onto the driver's, which `tests/test_panel.py` pins. The palette is a blend of the driver's desaturated and saturated sets, so the saved frame and the glass agree.

**The buttons are settings writes** (`buttons.py`): the panel's four buttons are plain GPIO with no `inky` API, read with `gpiod` on a daemon thread (the 13.3" moves button C to line 25, so the pins key off `Panel.driver`). A press only ever calls `SettingsStore.update`, so nothing crosses threads and presses during the slow e-ink refresh coalesce into one re-render. B toggles names, C turns the picture a quarter turn clockwise (`rotation` counts down, being counter-clockwise), D walks the artwork styles; A is reserved for the display modes (#17).

**The collage is the product** (`collage.py` + `paper.py`), not a single-detection frame or a dashboard (stats/config are #2). Birds are packed by their alpha silhouette so opaque pixels never overlap and nothing clips; the cut-outs' paper "halos" are normalized to one tone and feathered onto a textured paper page at render time (assets untouched). No-artwork species are omitted, and a window with nothing in it draws a single bare branch from the style's `perches/` - style-scoped like the birds, so a style with none shows empty paper rather than borrowing another's hand.

**Names pack with their bird** (`collage.py` + `fonts.py`): names are on by default and the label's box joins its bird's collision mask, centred on the silhouette's centroid and raised until it just clears the outline - so it tucks under the body and can never land on a neighbour. A second language stacks centred on the first, in parentheses, as one multi-line label. Six OFL italics are vendored in `assets/fonts/` (variable ones instantiated at weight 400) and picked in the admin along with a size. On the panel the label is hard-thresholded and stamped in pure black: antialiased grey would dither into colour speckle.

**BirdNET-Go owns the names** (`languages.py`): the admin picks a primary language (required) and an optional second one, shown in parentheses a line below; both drive the collage labels and the admin listings. Nothing is vendored and there is no second name mapping - the frame keys everything on the scientific name (artwork, `sizes.py`) and asks BirdNET-Go for the rest, because its SQLite has no common names at all (`labels` is scientific-only). `GET /api/v2/settings/locales` lists the locales, `HEAD /api/v2/species/dictionary/<code>` says which of them actually have one, and the dictionary itself is `{scientific name: common name}` with BirdNET-Go's own English fallback baked in. The two endpoints disagree on codes (the list's `no` answers as `nb`), so a language's code is its dictionary's. Dictionaries cache under `detector/data/names/` and revalidate by ETag (which is BirdNET-Go's `speciesDictVersion`), so the frame keeps its names across restarts and outages; with nothing cached the only language is `sci`, the scientific name - the Mac dev loop's normal state. Common names come lowercase in Norwegian and titled in English, so a label capitalizes the first letter and leaves the rest.

**Name to artwork** (`names.py`): normalize the detector's scientific name ("Turdus merula") to the filename shape ("turdus-merula.png") and exact-match, plus any curated `-N` variants. Artwork is grouped by **style** into subfolders of `assets/birds/` (`classic/`, a user's `custom/`, ...) and one is active at a time (`settings.style`; empty = whichever is present, settled by `names.resolve` at render time) - no union across styles. Style, not provenance: normalizing the Gould halos to von Wright's (d1e4606) left the two visually indistinguishable, so the axis a viewer picks between is style. There is no runtime alias map because the assets were renamed from 1800s taxonomy to modern eBird / BirdNET v2.4 names in a one-off migration. `tests/test_artwork_names.py` enforces the invariant: every filename (any style folder, `perches/` aside - those are named for the plant) must be a BirdNET label (from `assets/birdnet_labels_v2.4.txt`), a hybrid (`-x-`), or a listed exception.

**A bird keeps its picture while it is here** (`picks.py`): a style may hold several images for one species, but the choice is made per species, not per render - rolling per render meant a new bird, a shifted detection count or a restart reshuffled the whole page. `Picks` maps species -> the filename it is wearing, persisted to `detector/data/artwork.json` (gitignored, next to `settings.json`) so a restart doesn't re-roll; `choose` holds that pick as long as the file is still one of the style's variants, and `retain` forgets everything outside the window, so a bird that returns tomorrow returns in a different picture. Only the render loop calls `retain` - the kiosk and the admin preview can be looking at a different lookback. The mirror (`collage._flip`) is a hash of the name for the same reason. The collage cache key needs nothing for any of this: picks change only when the species set does, and that is already in the key.

**Curation is a tool, not a render-time choice** (`scripts/curate.py`): the artwork pipeline - scraping, background removal, the contact sheet, and the scans and cut-outs they work on - is gitignored and lives on the workstation only, because nothing the frame runs depends on it and the plates are re-scrapeable. Candidates sit in `wikimedia-scrape/staging/<source>/`; the contact sheet serves them one row per species on the frame's own paper - tiles toggle, `compare` opens them all full-size side by side - and writes the kept ones into the style folder as `<key>.png`, `<key>-2.png`, ... A species is rewritten whole on every change, so dropping one renumbers the rest rather than leaving a gap `variants_for` would never look for. Rows are ordered by `scripts/bergen_species.txt`, a hand-ranked local-commonness list, so the birds that actually turn up get curated first.

**The image is its own provenance record**: each shipped PNG carries `Source` and `Origin` tEXt chunks naming the plate it was cut from, spliced in after IHDR rather than re-encoded through Pillow (pixels untouched, and a 2 MB plate copies in milliseconds). That is why there is no manifest: the record cannot drift from the file and a re-curation cannot leave it stale. `names.origin_of` reads it back by walking the header chunks by hand - Pillow opens the whole plate, which is 18s over a curated folder against 0.02s, and about 1ms for the birds on an admin page. Both the admin listing (which plate this bird came from) and `curate.py` (what is already kept, on resume) read the files rather than anything alongside them; per-style `ATTRIBUTION.md` covers the works collectively.

## Working style

- When uncertain about the right approach, ask rather than assume
- Prefer less code over more - simplicity is a feature
- Comments are for non-trivial decisions, external references, or genuinely non-obvious logic; not for narrating what the code does
- When reviewing, be strict and objective
- Surface doubts rather than push through them; it is always valid to pause and question the current approach
- This is a learning project - when making non-obvious decisions, briefly explain the reasoning, and go deeper when asked

## Workflow

- Commit directly to `main` - single-person appliance, no branches or PRs
- Conventional commits, short messages, reference the issue as `#1` (not `#gh-1`): e.g. `feat: #1 add render`
- English throughout - code, comments, commits, and the kiosk and admin UI
- Commit types drive releases: python-semantic-release tags every push to `main` where a `feat` (minor) or `fix`/`perf` (patch) landed, bumps `pyproject.toml` + `__init__.py`, and writes `CHANGELOG.md`. Version shows in the admin corner, the startup log, and `setup.sh`
- `uv.lock` carries the project's own version, so the release commit must re-lock it (`build_command`, staged via `assets`) - a lock left one release behind gets rewritten by the next `uv sync` and the dirty file then blocks the self-update's checkout. That is also why `updates.apply` checks out with `--force`: it discards tracked files only, and everything the Pi owns (`detector/data`, `detector/config/config.yaml`, `detector/.env`, `frame.png`) is gitignored. Committing a currently-ignored per-Pi path would put it in the blast radius

## Docs

- [`README.md`](README.md) - project summary and licensing split
- [`detector/README.md`](detector/README.md) - BirdNET-Go container, the direct-read DB, and Pi deployment
- [`assets/birds/classic/ATTRIBUTION.md`](assets/birds/classic/ATTRIBUTION.md) - that style's sources and CC BY-SA 4.0 terms. One per style folder; a new style brings its own
- [`assets/fonts/ATTRIBUTION.md`](assets/fonts/ATTRIBUTION.md) - label typefaces and SIL OFL 1.1 terms
- `wikimedia-scrape/README.md` - how the cut-outs are scraped and background-removed from the Wikimedia Commons plate sources (von Wright, Gould), and curated into a style. Gitignored with the rest of the pipeline, so it exists on the workstation only
