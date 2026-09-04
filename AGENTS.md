# Fugleramme

This file provides guidance to coding agents working in this repository.

## Project

Fugleramme is an e-ink bird frame for a Raspberry Pi 5. A USB mic feeds BirdNET-Go (BirdNET v2.4 in Docker), which classifies bird sounds; the frame reads its API and renders the recently seen birds as a collage on a Pimoroni Inky Impression (Spectra 6) panel, serving the same view over HTTP. The detector can be the container beside the frame or an install elsewhere on the network. Python managed with `uv`: Pillow + numpy for rendering, stdlib `urllib` and `http.server`, and the Pi-only `inky` driver. It runs on a Pi in production and on a workstation for development - live mic capture and the panel push are Pi-only.

**The panel is the product.** The kiosk mirrors what is on the glass; it is not a second product with its own views. Detection, statistics and talking to other systems are BirdNET-Go's - it already serves a dashboard, spectrograms, live audio, MQTT with Home Assistant discovery, BirdWeather and clip export on `:8090`, and the admin links there. A feature that does not improve what hangs on the wall or the artwork on it belongs upstream, not here.

The collage should look printed on one sheet of paper. Do not add drop shadows, glows, vignettes, or other effects that separate birds from the page.

## Commands

```bash
uv run fugleramme-frame                     # run the service: render loop + kiosk on 0.0.0.0:8080
uv run fugleramme-dev                       # same, auto-restart on source change
uv run fugleramme-frame --preview out.png   # render the collage once and exit, no server/panel
uv run pytest -q                            # the suite CI gates on; ruff format/check and mypy are the rest
uv run fugleramme-fake-detector             # stand-in BirdNET-Go: generated detections over /api/v2
uv run fugleramme-check                     # does a detector answer everything the frame needs?
uv run python scripts/curate.py             # workstation only: contact sheet on :8081
./install.sh                                # Pi only: one-time bootstrap (curl'able; deps, clone, gadget, reboot)
./run.sh                                    # Pi only: converge an existing checkout (BirdNET-Go + services)
```

**Settings are runtime, flags are launch-only.** Display mode, kiosk resolution, rotation, lookback, style, names (on/off, primary + optional second language, typeface, size) and auto-update all live in the admin UI (`:8080/admin`, #2), persisted to `--config` (default `detector/data/settings.json`). The detector's address and credentials are settings too, so a frame can be re-pointed without a restart. The flags are `--detector`, `--images`, `--config`, `--output`, `--host`, `--port`, `--preview`; `--detector` only supplies the default for a settings file that carries no `detector_url` of its own. The panel's own size is never a setting.

## Architecture

Work is split across GitHub issues: **#1 frame service**, **#2 admin**, **#3 detector**, **#29 reading the API**. Each issue is the source of truth for its half.

**The API is the interface.** The halves meet at BirdNET-Go's `/api/v2`, never at its database. A frame can therefore point at the container beside it, at a BirdNET-Go already running on the same machine, or at one across the house - all the same code path, only a different URL (#29).

- `source.py` is the surface everything above sees: `species_since` / `recent` / `latest` / `life_list` / `stats`. `api.py` is the only implementation, and the only code that knows upstream's endpoints.
- **A transport failure raises `Unavailable`; an empty list means the detector answered and there were no birds.** Never collapse the two. HTTP failures are routine, and a source that returned `[]` on a timeout would push a bare perch to the glass on the first blip. The render loop holds its last good page; the kiosk answers 503; the admin still renders and says so.
- The endpoints disagree about time: the species summary filters on whole dates and stamps `first_heard`/`last_heard` with an offset, while `/detections/recent` gives a bare wall clock. So the summary is where the station's own UTC offset is read from, and a window shorter than a day is counted off the feed instead.
- `api.Configured` wraps the source and rebuilds it when the settings name a different detector, so one save reaches the loop, the server and `languages` at once. It must never call out to another module while holding its lock.
- `fake.py` serves the same endpoints over generated detections, so the dev loop, the tests and `fugleramme-check` all run without a container. It is also where upstream's real response shapes are written down.

**Render once, fan out** (`service.py`).

- The loop re-renders only when its inputs change: species in the window, panel size, style, rotation, names + language + typeface.
- It dithers to 6 colors and pushes to the panel; the kiosk serves the same page full-color at its own pixel count. No panel means web-only, the same path as `--preview`.

**The panel sizes itself** (`panel.py`, #4).

- `resolution_of` is the single answer to how big the page is: the attached Inky, or `FALLBACK_PANEL_RESOLUTION`. Both renders derive from it.
- The admin resolution setting picks the kiosk's **height** only; `settings.web_size` takes the width from the panel's aspect. The collage packs into whatever rectangle it is handed, so a kiosk of a different shape would be a different page, not a scaled one - and the browser letterboxes anyway, so only the height is ever pixel-for-pixel.
- `settings.rotation` (counter-clockwise) shapes both, but only `push` turns pixels - the driver takes native landscape only.
- `inky.set_image` re-dithers anything that is not already a 6-color "P" image, so `render.dither.dither` must hand it a palette mapping 1:1 onto the driver's. `tests/test_panel.py` pins this.

**Two packages, the rest flat** (`web/`, `render/`).

- `web/` is the kiosk and the admin: `server.py` is routing and transport only, `admin.py` builds the page from a `modes.Context`, `hostinfo.py` probes the machine. Nothing outside it imports anything but `web.server.serve`.
- `render/` is the PIL work: the collage and the plate, the furniture they share (`page.py`, `paper.py`, `fonts.py`, `sizes.py`), and `dither.py` for the panel's six colors.
- Everything else stays flat. `api.py`, `names.py`, `picks.py` and `languages.py` each have five or six importers spread across the app - a folder round them would draw no boundary.

**The web pages are files** (`web/static/`).

- `admin.html` is a `string.Template`; the kiosk page needs no substitution at all.
- `admin.js` is static and cached: it reads its server values from a JSON blob in the page rather than being built per request.
- The admin is used from a remote browser against a headless Pi. Do not design flows around `file://` URLs, opening a browser on the server, or other local-GUI assumptions.

**The buttons are settings writes** (`buttons.py`).

- Plain GPIO read with `gpiod` on a daemon thread; pins key off `Panel.driver` (the 13.3" moves C to line 25).
- A press only ever calls `SettingsStore.update`, so nothing crosses threads and presses during a refresh coalesce.
- A cycles display modes, B toggles names, C rotates a quarter turn clockwise, and D walks styles.

**The collage is the product** (`render/collage.py` + `render/paper.py`), not a dashboard.

- Birds are packed by their alpha silhouette so opaque pixels never overlap and nothing clips; halos are normalized and feathered onto paper at render time, assets untouched.
- The packer works in whole pixels (`_STEP`, `_OVERLAP_PX`), so it is not scale-invariant: it packs at `_PACK_SHORT` and scales the placements to the output. Packing at the output size instead swapped birds between the panel and the kiosk. Sprites and labels are redrawn from source at the target size, never resampled from the packed raster, and a label is centred in the box `_with_label` reserved for it since a re-rasterized font is not exactly `width × scale`.
- Packing is ~90% of a render and both outputs pack identically, so `_placements` caches it (`_layouts`, keyed on the species and their artwork, the pack size, and the resolved label strings). The loop's panel render pays for the kiosk's: 5.4s to 0.5s here. The lock is held across the pack so the second caller waits rather than packing its own copy.
- No-artwork species are omitted. An empty window draws one branch from the style's own `perches/`, chosen by day (`collage.perch_day`, in both cache keys).
- A label's box joins its bird's collision mask, so it tucks under the body and never lands on a neighbour. A second language stacks below in parentheses.
- On the panel labels are hard-thresholded to pure black: antialiased grey dithers into colour speckle.

**BirdNET-Go owns the names** (`languages.py`).

- The frame keys everything on the scientific name and asks the detector for the rest, through the same session as the detections.
- `GET /api/v2/settings/locales` lists locales, `HEAD /api/v2/species/dictionary/<code>` says which have one. The two disagree on codes (the list's `no` answers as `nb`), so a language's code is its dictionary's.
- Dictionaries cache in `detector/data/names/`, revalidated by ETag, and carry the station they came from so re-pointing the frame cannot serve another station's names. With nothing cached and nothing answering, the only language is `sci`.
- Norwegian names arrive lowercase and English titled, so a label capitalizes the first letter only.
- A plate's date follows the primary language too, via `babel`: `Namer.date` for the newest arrival (a day and its year, which can be months back), `Namer.moment` for the latest bird (a day and a clock time). Languages differ in more than the month's name - Hungarian and Latvian put the year first, only some join the day and time with a comma - so a hand-rolled table would get them wrong. `sci`, and any language `babel` lacks, get a numeric date.
- The plates carry no words beyond the name. Nothing translates UI text, so "First heard" became the year. Narrow no-break spaces are flattened to plain ones: CLDR asks for one before AM/PM and five of the seven label faces draw a box instead of it.

**Name to artwork** (`names.py`, `picks.py`).

- "Turdus merula" normalizes to `turdus-merula.png` plus any curated `-N` variants. No runtime alias map - the assets were renamed to modern eBird / BirdNET v2.4 names in a one-off migration.
- Artwork is grouped by **style** into subfolders of `assets/artwork/`, each holding `birds/` and `perches/` beside its `ATTRIBUTION.md` and `manifest.json`, one active at a time (`settings.style`; empty = whichever is present). No union across styles, and a folder with no birds isn't offered at all.
- `tests/test_artwork_names.py` enforces it: every filename (`perches/` aside) must be a BirdNET label, a hybrid (`-x-`), or a listed exception.
- The variant pick is per species, not per render, persisted to `detector/data/artwork.json` so a restart doesn't reshuffle the page. Only the render loop calls `retain` - the kiosk and admin preview may hold a different lookback. The collage cache key needs nothing extra: picks change only when the species set does.

**Curation is a tool, not a render-time choice** (`scripts/curate.py`).

- The whole artwork pipeline (scraping, background removal, contact sheet, plates) is gitignored and workstation-only: the frame doesn't depend on it and plates are re-scrapeable.
- Generated cut-outs go through staging and manual selection before `curate.py` writes shipped assets.
- Shipped plates are capped at 1200 pixels on their longest side. Premultiply alpha when resampling cut-outs to avoid dark fringes.
- Prefer public-domain plates with individual hand-drawn birds on paper and no painted scenery; sources must also be practical to curate reliably.
- The sheet writes kept candidates as `<key>.png`, `<key>-2.png`, ... and rewrites a species whole on every change, so dropping one renumbers the rest rather than leaving a gap `variants_for` would never look for.
- A style's `manifest.json` gives a shipped file the work it was cut from and a link to the plate (`birds/turdus-merula.png` -> `{"source": "gould", "url": ...}`), keyed by the path under the style so one record covers `birds/` and `perches/` both. The sheet writes it alongside the files it renames and carries the perch entries through untouched. `names.source_of` reads the key ATTRIBUTION.md maps to terms, `names.origin_of` the citation; both cached per folder on the file's mtime, since the admin page asks once per subject. No manifest (a hand-filled `custom/`), no entry, or an entry with no URL all resolve to `""` rather than failing.

**The install splits at the reboot** (`install.sh`, `run.sh`).

- `install.sh` is the curl'able one-time bootstrap: deps, clone, groups, SPI/I2C overlays, gadget mode. Everything in it only takes effect on boot, so it is the only script that prompts a reboot - and only if something actually changed. It must stay self-contained; it is fetched before the checkout exists.
- `install.sh` also asks where BirdNET-Go lives: installed here, already running on this machine, or on another. The answer plus the two ports land in a gitignored `frame.env` at the repo root, which `run.sh` sources. Only a bundled detector gets a `detector/.env`, so an external install skips the container everywhere by that one marker.
- `run.sh` is the idempotent converge: `uv sync`, config, compose up, systemd unit. Re-run after a pull or a repo move - it bakes `$REPO_ROOT`, the frame's port and the detector's URL into the unit.
- **`updates.apply` never re-runs `run.sh`.** A Pi that auto-updates keeps its old unit, its old `detector/.env` and its old `settings.json`, so every default a release introduces must reproduce the previous one's behaviour: frame on 8080, bundled detector on 8090, `detector_url` of `http://127.0.0.1:8090`. A new compose variable needs its default inline (`${BIRDNET_PORT:-8090}`), not only in `frame.env`. Get this wrong and working appliances break on update, which is the one failure nobody can recover from remotely.
- The self-update converges the detector too, so a release can move the image pin (`updates._converge_detector`). It is `up -d`, not run.sh's `--force-recreate`: an unchanged pin must not bounce a working detector. `detector/.env` is the marker for "an appliance, not a dev checkout", and a failure only logs - the frame is already on the new version by then. The DB is copied to `birdnet.db.bak` first and a failed copy skips the swap, since the new container migrates it in place on first start. Upstream tags by date and the pin reaches every frame, so test a bump on the Pi before tagging the release that carries it.
- With a reboot pending, `--no-start` leaves the frame enabled but stopped, since there is no SPI and no group membership yet. The container starts either way: `restart: unless-stopped` only revives a container that was already running.
- Prompts read `/dev/tty`, not stdin - under `curl | bash` stdin is the script itself. Same reason the body is wrapped in `main`, called on the last line.
- New machine-specific values must be detected or prompted for and written to gitignored per-Pi configuration, not hardcoded in tracked defaults.
- BirdNET-Go must run with the host user's UID and GID so its mounted config and data remain writable without changing checkout ownership.
- USB gadget access is documented in troubleshooting; do not assume `10.12.194.1` when macOS Internet Sharing may assign a leased address.

## Workflow

- Commit directly to `main` - single-person appliance, no branches or PRs
- Conventional commits, short messages, reference the issue as `#1` (not `#gh-1`): e.g. `feat: #1 add render`
- English throughout - code, comments, commits, and the kiosk and admin UI
- `ci.yml` runs on every push and PR: `uv sync --locked`, ruff format + check, mypy, pytest, and shellcheck over the two install scripts. Ruff and mypy are configured in `pyproject.toml` and take no path arguments - they read their own scope
- The lock check is the one worth knowing: `--locked` fails on drift between `uv.lock` and `pyproject.toml`, because a stale lock is what blocks the self-update's checkout
- Commit types drive releases: python-semantic-release tags every push to `main` carrying a `feat` (minor) or `fix`/`perf` (patch), bumps `pyproject.toml` + `__init__.py`, and writes `CHANGELOG.md`
- `uv.lock` carries the project's version, so the release commit must re-lock it - a stale lock gets rewritten by the next `uv sync`, and the dirty file then blocks the self-update's checkout
- That's why `updates.apply` checks out with `--force`: it discards tracked files only, and everything the Pi owns (`detector/data`, `detector/config/config.yaml`, `detector/.env`, `frame.png`) is gitignored. Committing a currently-ignored per-Pi path would put it in the blast radius

## Docs

- [`README.md`](README.md) - end-user-facing project summary and licensing split; avoid internal ownership and architecture jargon
- [`docs/`](docs/index.md) - the end-user manual (hardware, install, operations, troubleshooting)
- [`assets/artwork/classic/ATTRIBUTION.md`](assets/artwork/classic/ATTRIBUTION.md) - that style's sources and terms; one per style folder
- [`assets/fonts/ATTRIBUTION.md`](assets/fonts/ATTRIBUTION.md) - label typefaces, SIL OFL 1.1
