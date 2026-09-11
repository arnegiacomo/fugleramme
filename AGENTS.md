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
docker build -t fugleramme .                # the kiosk image: no panel, no detector (docs/container.md)
```

**Settings are runtime, flags are launch-only.** Display mode, kiosk resolution, rotation, lookback, the panel's refresh floor, how many species and which ones, style, names (on/off, primary + optional second language, typeface, size) and auto-update all live in the admin UI (`:8080/admin`), persisted to `--config` (default `detector/data/settings.json`). The detector's address and password are settings too, so a frame can be re-pointed without a restart. The flags are `--detector`, `--images`, `--config`, `--output`, `--host`, `--port`, `--preview`. The panel's own size is never a setting.

**The environment seeds settings; it never overrides them** (`settings.from_env`). `FUGLERAMME_<FIELD>` for any field of `Settings`, read off the dataclass so a new setting needs nothing added. It exists for the container image, where a fresh `/data` has no `settings.json` and the detector's address has to come from somewhere. These become the store's *defaults*, exactly as `--detector` does: a key the file carries wins, so a variable goes quiet from the first Save on. Override-on-boot instead and the admin page - which offers to change every one of them - would be lying. Precedence is `settings.json` > `--detector` > environment > built-in default.

## Architecture

**The API is the interface.** The halves meet at BirdNET-Go's `/api/v2`, never at its database. A frame can therefore point at the container beside it, at a BirdNET-Go already running on the same machine, or at one across the house - all the same code path, only a different URL.

- `source.py` is the surface everything above sees: `species_since` / `recent` / `latest` / `life_list` / `stats`. `api.py` is the only implementation, and the only code that knows upstream's endpoints.
- **A transport failure raises `Unavailable`; an empty list means the detector answered and there were no birds.** Never collapse the two. HTTP failures are routine, and a source that returned `[]` on a timeout would push a bare perch to the glass on the first blip. The render loop holds its last good page and the server holds the last one it served - dropped when the settings name another detector, since another station's birds are not ours. With nothing held the route answers 503; the admin still renders and says so.
- **The endpoints disagree about which bird is which, too.** BirdNET-Go rewrites a scientific name to its current form as it stores a detection but leaves rows it already stored alone, so a station upgraded across a reclassification serves one bird as two species forever - and BirdNET's own labels keep the old name regardless. `api._merged` folds the summary's two rows into one and `_detection` canonicalizes the feed, so nothing above `api.py` ever sees the pair. Get this wrong and the species count and life list double, the newest arrival is dated to the day the detector was upgraded, and the bird lands on the sheet twice.
- The endpoints disagree about time: the species summary filters on whole dates and stamps `first_heard`/`last_heard` with an offset, while `/detections/recent` gives a bare wall clock. So the summary is where the station's own UTC offset is read from, and a window shorter than a day is counted off the feed instead.
- **Only birds come off the source** (`taxa.py`). A station classifies more than birds and can run a bat or multi-taxa model beside the one that hears them, so `recent()` and `_summary()` both drop what `is_bird` rejects. Two halves, neither a judgement call about a species: v2.4's own label set is an allowlist, which is what catches a bat whatever its genus, since a name that model never emitted has no artwork by construction (`tests/test_artwork_names.py` pins the filenames to those labels, under their current spelling); and `NON_BIRD_GENERA` covers the 101 labels inside v2.4 that are noise classes, frogs, crickets, squirrels and other mammals, read off eBird's own `t-` species codes rather than judged one by one. Every drop is logged once per species, since a bird that silently stops appearing is otherwise unaccountable. An unreadable label file fails open, allowlist off and genus check standing: the odd frog on the glass beats a blank one.
- Both halves key through `names.normalize` and the summary is filtered after `_merged`, so a species reclassified since v2.4 answers to the label's spelling and to the detector's alike. Match raw text instead and the goshawk goes the way of a bat.
- `api.Configured` wraps the source and rebuilds it when the settings name a different detector, so one save reaches the loop, the server and `languages` at once. It must never call out to another module while holding its lock.
- `fake.py` serves the same endpoints over generated detections, so the dev loop, the tests and `fugleramme-check` all run without a container. It is also where upstream's real response shapes are written down, and its station hears a bat, a squirrel and a noise class among the birds so the filter is exercised everywhere it is used.

**Render once, fan out** (`service.py`).

- The loop re-renders only when its inputs change: the species on the page, panel size, style, rotation, names + language + typeface.
- `settings.refresh_minutes` floors how often the *birds* may change the page (#64): at a busy station the species either side of the limit's cutoff trade on every call, and each trade is a full e-ink refresh. A changed `Settings` bypasses the floor, so a save is never held back by it.
- It dithers to 6 colors and pushes to the panel; the kiosk serves the same page full-color at its own pixel count. No panel means web-only, the same path as `--preview`.

**The panel sizes itself** (`panel.py`).

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
- `selected_species` is the single answer to which birds are on the page: it drops what the style cannot draw, then applies the admin's limit under the admin's ranking - `rarest_ever` costs a second summary call, since a resident heard twice today is only a rarity by the window's reckoning. There is no ceiling of the frame's own - a fresh frame ships at `settings.DEFAULT_LIMIT`, and `NO_LIMIT` really draws every species the window holds, so a long lookback at a busy station is the admin's to bound. The key reads *that* list, not the window's - under a limit two birds can trade places across it while the set of species heard sits still.
- A label's box joins its bird's collision mask, so it tucks under the body and never lands on a neighbour. A second language stacks below in parentheses.
- On the panel labels are hard-thresholded to pure black: antialiased grey dithers into colour speckle.

**BirdNET-Go owns the names** (`languages.py`).

- The frame keys everything on the scientific name and asks the detector for the rest, through the same session as the detections.
- `GET /api/v2/settings/locales` lists locales, `HEAD /api/v2/species/dictionary/<code>` says which have one. The two disagree on codes (the list's `no` answers as `nb`), so a language's code is its dictionary's.
- Dictionaries cache in `detector/data/names/`, revalidated by ETag, and carry the station they came from so re-pointing the frame cannot serve another station's names. With nothing cached and nothing answering, the only language is `sci`.
- **The names are gated where the detections are not.** BirdNET-Go registers `/settings/*` behind its auth middleware whenever any provider is configured, while the detections only answer to `PrivateMode` - so a station happily serving birds to a frame with no password still refuses it the locale list, and the language menu collapses to the scientific name. `catalog_failure` carries the reason to the admin, `api.probe` tests both endpoints, and `fake.serve(private=False)` is that shape. The Detector row says `needs a password` beside `running` for it - red when PrivateMode gates everything, amber when only the names are short. `/health` is not on upstream's PrivateMode exempt list and `hostinfo` asks it without credentials, so its 401 says the detector wants a password, never that this frame lacks one - only whether the page's own calls came back tells those apart. Where the admin would have put a bird it says the same in red, linked to that field (`admin._fix`), rather than "unreachable" - which would send the reader to an address that is answering fine.
- **An empty probe is a failure, not an answer.** Caching one would hold the menu empty for `_CATALOG_TTL` and write itself over the good list on disk, which no one can fix without a restart. The catalog is keyed on `ApiSource.station`, one per source, so entering the password the locale list was waiting for expires it at once - `Configured` builds a new source for a credential change as much as for an address.
- BirdNET-Go prompts for a password alone, but its login rejects an empty username and matches the one it is given against `security.basicauth.clientid`. The admin asks for no username; the frame sends `api.CLIENT_ID`, that setting's default. `Settings.detector_username` stays for an install that changed the id.
- Norwegian names arrive lowercase and English titled, so a label capitalizes the first letter only.
- A plate's date follows the primary language too, via `babel`: `Namer.date` for the newest arrival (a day and its year, which can be months back), `Namer.moment` for the latest bird (a day and a clock time). Languages differ in more than the month's name - Hungarian and Latvian put the year first, only some join the day and time with a comma - so a hand-rolled table would get them wrong. `sci`, and any language `babel` lacks, get a numeric date.
- The plates carry no words beyond the name. Nothing translates UI text, so "First heard" became the year. Narrow no-break spaces are flattened to plain ones: CLDR asks for one before AM/PM and five of the seven label faces draw a box instead of it.

**Name to artwork** (`names.py`, `picks.py`).

- **Shipped artwork is filed under the species' current name, and only that.** "Turdus merula" normalizes to `turdus-merula.webp` plus any curated `-N` variants. v2.4's label set is frozen at its training taxonomy, so 236 of its 6522 labels name a bird the detector now reports under a newer name; `normalize` folds both spellings to the current one, which is what the label table, the body masses, the picks and the collage are all keyed on. One nameset everywhere means there is never a question of which of a bird's two names a plate is under.
- `variants_for` still reads the label's spelling as well, current first, but only for artwork this repo never sees: a user's own style folder is outside CI, and a plate they curated as `corvus-monedula.png` must not silently stop drawing on an update. Shipped assets may not use it - `tests/test_artwork_names.py` is what keeps that from being an open choice.
- `assets/birdnet_aliases.json` is that alias map: an unmodified copy of [OpenFauna](https://github.com/tphakala/openfauna)'s `build/aliases.json`, the same data BirdNET-Go canonicalizes with, so the frame agrees with the detector by construction rather than by a hand-kept guess. CC BY-SA 4.0, credited in `assets/ATTRIBUTION.md`. Refresh it by hand when a species is reported missing, and alongside the label list: `taxa.is_bird` keys the allowlist through `normalize`, so a canonical name the detector knows and this map does not is dropped as a non-bird rather than merely drawn without a plate. `api` logs what it drops, once per species, which is where that shows up.
- **Ship WebP, read either.** `names.SUFFIXES` is the order, and a stem carrying both draws the WebP once rather than twice. PNG stays readable on purpose - a `custom/` folder should draw whatever is dropped in it, and PNG is what an editor exports by default - but nothing shipped is PNG, and `add_bird.write_plate` is what keeps it that way. Alpha is stored losslessly, so the cut-out - the expensive part - survives exactly, while q90 on the RGB under it took the tree from 1055 MB to 165 MB for a difference that does not reach the rendered page. Everything that lists a style goes through `names.artwork_in` so the tools and the frame cannot disagree about what counts.
- Artwork is grouped by **style** into subfolders of `assets/artwork/`, each holding `birds/` and `perches/` beside its `ATTRIBUTION.md` and `manifest.json`, one active at a time (`settings.style`; empty = whichever is present). No union across styles, and a folder with no birds isn't offered at all.
- `tests/test_artwork_names.py` enforces it: every filename (`perches/` aside) must name a BirdNET species under its current name, be a hybrid (`-x-`), or be a listed exception - the 15 modern names v2.4 has no label for at all, which can never be detected and are kept for the artwork alone. It also pins every detectable plate to a body mass, since `sizes.mass_of` answers a missing row with the dataset median and would quietly draw a large bird at 35g.
- The variant pick is per species, not per render, persisted to `detector/data/artwork.json` so a restart doesn't reshuffle the page. Only the render loop calls `retain` - the kiosk and admin preview may hold a different lookback. The collage cache key needs nothing extra: picks change only when the species set does.

**Curation is a tool, not a render-time choice** (`scripts/curate.py`).

- The whole artwork pipeline (scraping, background removal, contact sheet, plates) is gitignored and workstation-only: the frame doesn't depend on it and plates are re-scrapeable.
- Generated cut-outs go through staging and manual selection before `curate.py` writes shipped assets.
- Shipped plates are capped at 1200 pixels on their longest side and written by `add_bird.write_plate`, the one place the encoding is decided. Premultiply alpha when resampling cut-outs to avoid dark fringes.
- Prefer public-domain plates with individual hand-drawn birds on paper and no painted scenery; sources must also be practical to curate reliably.
- The sheet writes kept candidates as `<key>.webp`, `<key>-2.webp`, ... and rewrites a species whole on every change, so dropping one renumbers the rest rather than leaving a gap `variants_for` would never look for.
- A style's `manifest.json` gives a shipped file the work it was cut from and a link to the plate (`birds/turdus-merula.webp` -> `{"source": "gould", "url": ...}`), keyed by the path under the style so one record covers `birds/` and `perches/` both. The sheet writes it alongside the files it renames and carries the perch entries through untouched. `names.source_of` reads the key ATTRIBUTION.md maps to terms, `names.origin_of` the citation; both cached per folder on the file's mtime, since the admin page asks once per subject. No manifest (a hand-filled `custom/`), no entry, or an entry with no URL all resolve to `""` rather than failing.

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

**The image is the kiosk alone** (`Dockerfile`, `.dockerignore`, `.github/workflows/image.yml`).

- Pull it, point it at a BirdNET-Go you already run, read the collage on a web page. No panel (SPI, I2C and the buttons are the Pi's) and `install.sh` knows nothing about it - both their own follow-ups, not gaps to fill in passing.
- The *image* is the kiosk alone; `examples/docker-compose.yml` is what brings a detector up beside it, for a machine with a mic and no panel. It is documentation, curl'able straight from `main`, so it pins the same BirdNET-Go tag `detector/docker-compose.yml` does - `tests/test_container.py` holds the two together, since the pin only moves after it is tested on the Pi.
- **The checkout's shape has to survive into the image.** `config.REPO_ROOT` is derived from the package's own file, and the artwork, the fonts, the labels and `bird_sizes.csv` all hang off it, so the project is installed editable at `/app` with `/app/src/fugleramme` beside `/app/assets`. A build-time `RUN python -c` asserts it: fail the build, not the first render.
- The plates are split across a COPY layer per letter range so a release adding a species re-pulls that range instead of all 165 MB - the registry serves blobs by digest, so the letters that did not move are already on disk. The ranges must leave no letter out, and a range matching nothing fails the build; `tests/test_container.py` reads the globs back out of the Dockerfile and holds them to both.
- Everything mutable already derives from `--config`'s parent, so one volume at `/data` is the whole persistence story and no code knows about it. A fresh one is configured through `FUGLERAMME_<FIELD>`, which seeds and never overrides - see the settings rule above.
- **`updates.apply` refuses in a container** (`updates.in_container`, the image's own `FUGLERAMME_CONTAINER`): there is no checkout to move onto a tag, no systemd to restart it, and handing the frame the docker socket buys a button. `available()` still runs - knowing a release is out is the half that works - and the admin drops the Install button, shows the auto-update toggle disabled, and prints `updates.CONTAINER_COMMAND` in its place.
- `image.yml` is a separate workflow from `release.yml`, fired by the tag that one pushes. The release's job is to cut the tag; a slow or broken image build must never delay or fail a version bump. Native runners per architecture, pushed by digest, with a merge job for the manifest list.

## Workflow

- Commit directly to `main` - single-person appliance, no branches or PRs
- Conventional commits, short messages, reference the issue as `#1` (not `#gh-1`): e.g. `feat: #1 add render`
- English throughout - code, comments, commits, and the kiosk and admin UI
- `ci.yml` runs on every push and PR: `uv sync --locked`, ruff format + check, mypy, pytest, and shellcheck over the two install scripts. Ruff and mypy are configured in `pyproject.toml` and take no path arguments - they read their own scope
- The lock check is the one worth knowing: `--locked` fails on drift between `uv.lock` and `pyproject.toml`, because a stale lock is what blocks the self-update's checkout
- Commit types drive releases: python-semantic-release tags every push to `main` carrying a `feat` (minor) or `fix`/`perf` (patch), bumps `pyproject.toml` + `__init__.py`, and writes `CHANGELOG.md`
- `uv.lock` carries the project's version, so the release commit must re-lock it - a stale lock gets rewritten by the next `uv sync`, and the dirty file then blocks the self-update's checkout
- That's why `updates.apply` checks out with `--force`: it discards tracked files only, and everything the Pi owns (`detector/data`, `detector/config/config.yaml`, `detector/.env`, `frame.env`, `frame.png`) is gitignored. Committing a currently-ignored per-Pi path would put it in the blast radius

## Docs

- [`README.md`](README.md) - end-user-facing project summary and licensing split; avoid internal ownership and architecture jargon
- [`docs/`](docs/index.md) - the end-user manual (hardware, install, operations, troubleshooting)
- [`assets/artwork/classic/ATTRIBUTION.md`](assets/artwork/classic/ATTRIBUTION.md) - that style's sources and terms; one per style folder
- [`assets/fonts/ATTRIBUTION.md`](assets/fonts/ATTRIBUTION.md) - label typefaces, SIL OFL 1.1
