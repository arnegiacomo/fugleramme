# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Fugleramme is an e-ink bird frame for a Raspberry Pi 5. A USB mic feeds BirdNET-Go (BirdNET v2.4 in Docker), which classifies bird sounds into its own SQLite; the frame reads that DB read-only and renders the recently seen birds as a collage on a Pimoroni Inky Impression (Spectra 6) panel, serving the same view over HTTP. Python managed with `uv`: Pillow + numpy for rendering, stdlib `sqlite3` and `http.server`, and the Pi-only `inky` driver. It runs on a Pi in production and on a workstation for development - live mic capture and the panel push are Pi-only.

## Commands

```bash
uv sync                                     # create/refresh the venv from the lockfile
uv run fugleramme-frame                     # run the service: render loop + kiosk on 0.0.0.0:8080
uv run fugleramme-dev                       # same, auto-restart on source change
uv run fugleramme-frame --preview out.png   # render the collage once and exit, no server/panel
uv run python -m fugleramme.seed --count 40 # BirdNET-Go-shaped fixtures: detections + names cache
uv run python scripts/curate.py             # workstation only: contact sheet on :8081
./install.sh                                # Pi only: one-time bootstrap (curl'able; deps, clone, gadget, reboot)
./run.sh                                    # Pi only: converge an existing checkout (BirdNET-Go + services)
uv run pytest -q                            # run tests
uv run pytest tests/test_artwork_names.py   # run a single test file
```

**Settings are runtime, flags are launch-only.** Kiosk resolution, rotation, lookback, kiosk refresh, style, names (on/off, primary + optional second language, typeface, size) and auto-update all live in the admin UI (`:8080/admin`, #2), persisted to `--config` (default `detector/data/settings.json`). The flags are `--db`, `--images`, `--config`, `--output`, `--host`, `--port`, `--preview`. The panel's own size is never a setting.

## Architecture

Work is split across GitHub issues: **#1 frame service**, **#2 admin**, **#3 detector**, **#7 direct-read refactor**. Each issue is the source of truth for its half.

**The DB file is the interface.** The halves meet at BirdNET-Go's SQLite (bind-mounted to `detector/data`), plus its API for names alone.

- `db.py` is the only code that knows BirdNET-Go's schema. It exposes `species_since` / `recent` / `latest` / `stats` - nothing else sees its SQL.
- No frame-owned DB and no sync process (dropped in #7). WAL lets the loop and the server each hold a read connection.

**Render once, fan out** (`service.py`).

- The loop re-renders only when its inputs change: species in the window, panel size, style, rotation, names + language + typeface.
- It dithers to 6 colors and pushes to the panel; the kiosk serves the same collage full-color at its own resolution (`collage_key`). No panel means web-only, the same path as `--preview`.

**The panel sizes itself** (`panel.py`, #4).

- The loop renders at the attached Inky's resolution (`FALLBACK_PANEL_RESOLUTION` when none is attached), so the admin resolution setting only governs the kiosk.
- `settings.rotation` (counter-clockwise) shapes both, but only `push` turns pixels - the driver takes native landscape only.
- `inky.set_image` re-dithers anything that is not already a 6-color "P" image, so `render.dither` must hand it a palette mapping 1:1 onto the driver's. `tests/test_panel.py` pins this.

**The web pages are files** (`static/`, `admin.py`, `server.py`).

- `static/` holds the kiosk and admin markup, style and script. `admin.html` is a `string.Template`; the kiosk page needs no substitution at all.
- `admin.js` is static and cached: it reads its server values from a JSON blob in the page rather than being built per request.
- `server.py` is routing and transport only. `admin.py` builds the page from a `modes.Context`, `hostinfo.py` probes the machine.

**The buttons are settings writes** (`buttons.py`).

- Plain GPIO read with `gpiod` on a daemon thread; pins key off `Panel.driver` (the 13.3" moves C to line 25).
- A press only ever calls `SettingsStore.update`, so nothing crosses threads and presses during a refresh coalesce.
- B toggles names, C rotates a quarter turn clockwise, D walks styles. A is reserved for display modes (#17).

**The collage is the product** (`collage.py` + `paper.py`), not a dashboard.

- Birds are packed by their alpha silhouette so opaque pixels never overlap and nothing clips; halos are normalized and feathered onto paper at render time, assets untouched.
- No-artwork species are omitted. An empty window draws one branch from the style's own `perches/`, chosen by day (`collage.perch_day`, in both cache keys).
- A label's box joins its bird's collision mask, so it tucks under the body and never lands on a neighbour. A second language stacks below in parentheses.
- On the panel labels are hard-thresholded to pure black: antialiased grey dithers into colour speckle.

**BirdNET-Go owns the names** (`languages.py`).

- The frame keys everything on the scientific name and asks the API for the rest - BirdNET-Go's SQLite has no common names at all.
- `GET /api/v2/settings/locales` lists locales, `HEAD /api/v2/species/dictionary/<code>` says which have one. The two disagree on codes (the list's `no` answers as `nb`), so a language's code is its dictionary's.
- Dictionaries cache in `detector/data/names/`, revalidated by ETag. With nothing cached the only language is `sci` - the dev loop's normal state.
- Norwegian names arrive lowercase and English titled, so a label capitalizes the first letter only.

**Name to artwork** (`names.py`, `picks.py`).

- "Turdus merula" normalizes to `turdus-merula.png` plus any curated `-N` variants. No runtime alias map - the assets were renamed to modern eBird / BirdNET v2.4 names in a one-off migration.
- Artwork is grouped by **style** into subfolders of `assets/birds/`, one active at a time (`settings.style`; empty = whichever is present). No union across styles, and a folder with no birds isn't offered at all.
- `tests/test_artwork_names.py` enforces it: every filename (`perches/` aside) must be a BirdNET label, a hybrid (`-x-`), or a listed exception.
- The variant pick is per species, not per render, persisted to `detector/data/artwork.json` so a restart doesn't reshuffle the page. Only the render loop calls `retain` - the kiosk and admin preview may hold a different lookback. The collage cache key needs nothing extra: picks change only when the species set does.

**Curation is a tool, not a render-time choice** (`scripts/curate.py`).

- The whole artwork pipeline (scraping, background removal, contact sheet, plates) is gitignored and workstation-only: the frame doesn't depend on it and plates are re-scrapeable.
- The sheet writes kept candidates as `<key>.png`, `<key>-2.png`, ... and rewrites a species whole on every change, so dropping one renumbers the rest rather than leaving a gap `variants_for` would never look for.
- Shipped PNGs carry `Source` / `Origin` tEXt chunks spliced in after IHDR, so provenance can't drift from the file and there is no manifest. `names.origin_of` hand-parses the header - Pillow opens the whole plate (18s over a folder against 0.02s).

**The install splits at the reboot** (`install.sh`, `run.sh`).

- `install.sh` is the curl'able one-time bootstrap: deps, clone, groups, SPI/I2C overlays, gadget mode. Everything in it only takes effect on boot, so it is the only script that prompts a reboot - and only if something actually changed. It must stay self-contained; it is fetched before the checkout exists.
- `run.sh` is the idempotent converge: `uv sync`, config, compose up, systemd unit. Re-run after a pull or a repo move - it bakes `$REPO_ROOT` into the unit.
- With a reboot pending, `--no-start` leaves the frame enabled but stopped, since there is no SPI and no group membership yet. The container starts either way: `restart: unless-stopped` only revives a container that was already running.
- Prompts read `/dev/tty`, not stdin - under `curl | bash` stdin is the script itself. Same reason the body is wrapped in `main`, called on the last line.

## Workflow

- Commit directly to `main` - single-person appliance, no branches or PRs
- Conventional commits, short messages, reference the issue as `#1` (not `#gh-1`): e.g. `feat: #1 add render`
- English throughout - code, comments, commits, and the kiosk and admin UI
- Commit types drive releases: python-semantic-release tags every push to `main` carrying a `feat` (minor) or `fix`/`perf` (patch), bumps `pyproject.toml` + `__init__.py`, and writes `CHANGELOG.md`
- `uv.lock` carries the project's version, so the release commit must re-lock it - a stale lock gets rewritten by the next `uv sync`, and the dirty file then blocks the self-update's checkout
- That's why `updates.apply` checks out with `--force`: it discards tracked files only, and everything the Pi owns (`detector/data`, `detector/config/config.yaml`, `detector/.env`, `frame.png`) is gitignored. Committing a currently-ignored per-Pi path would put it in the blast radius

## Working style

- When uncertain about the right approach, ask rather than assume
- Prefer less code over more - simplicity is a feature
- Comments are for non-trivial decisions or genuinely non-obvious logic, not for narrating what the code does
- When reviewing, be strict and objective
- Surface doubts rather than push through them
- This is a learning project - briefly explain the reasoning behind non-obvious decisions, and go deeper when asked

## Docs

- [`README.md`](README.md) - project summary and licensing split
- [`docs/`](docs/index.md) - the end-user manual (hardware, install, operations, troubleshooting)
- [`detector/README.md`](detector/README.md) - BirdNET-Go container, the direct-read DB, and Pi deployment
- [`assets/birds/classic/ATTRIBUTION.md`](assets/birds/classic/ATTRIBUTION.md) - that style's sources and terms; one per style folder
- [`assets/fonts/ATTRIBUTION.md`](assets/fonts/ATTRIBUTION.md) - label typefaces, SIL OFL 1.1
