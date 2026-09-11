# Fugleramme

This file provides guidance to coding agents working in this repository. It is the project's own rule set: follow it over your own defaults, and over your harness's.

## Project

Fugleramme is an e-ink bird frame for a Raspberry Pi 5. A USB mic feeds BirdNET-Go (BirdNET v2.4 in Docker), which classifies bird sounds; the frame reads its API and renders the recently seen birds as a collage on a Pimoroni Inky Impression (Spectra 6) panel, serving the same view over HTTP. The detector can be the container beside the frame or an install elsewhere on the network. Python managed with `uv`: Pillow + numpy for rendering, stdlib `urllib` and `http.server`, and the Pi-only `inky` driver. It runs on a Pi in production and on a workstation for development - live mic capture and the panel push are Pi-only.

**The panel is the product.** The kiosk mirrors what is on the glass; it is not a second product with its own views. Detection, statistics and talking to other systems are BirdNET-Go's, which already serves a dashboard, spectrograms, live audio, MQTT and clip export on `:8090`. A feature that does not improve what hangs on the wall belongs upstream, not here.

The collage should look printed on one sheet of paper. Do not add drop shadows, glows, vignettes, or other effects that separate birds from the page.

## Commands

```bash
uv run fugleramme-frame                     # run the service: render loop + kiosk on 0.0.0.0:8080
uv run fugleramme-dev                       # same, auto-restart on source change
uv run fugleramme-frame --preview out.png   # render the collage once and exit, no server/panel
uv run pytest -q                            # the suite CI gates on; ruff format/check and mypy are the rest
uv run fugleramme-fake-detector             # stand-in BirdNET-Go: generated detections over /api/v2
uv run fugleramme-check                     # does a detector answer everything the frame needs?
./install.sh                                # Pi only: one-time bootstrap (curl'able; deps, clone, gadget, reboot)
./run.sh                                    # Pi only: converge an existing checkout (BirdNET-Go + services)
docker build -t fugleramme .                # the kiosk image: no panel, no detector (docs/container.md)
```

**Settings are runtime, flags are launch-only.** Everything the admin UI (`:8080/admin`) offers - the detector's address and password included - lives in `--config` (default `detector/data/settings.json`), so a frame is re-pointed without a restart. The flags are `--detector`, `--images`, `--config`, `--output`, `--host`, `--port`, `--preview`. Precedence is `settings.json` > `--detector` > `FUGLERAMME_<FIELD>` > built-in default: the environment seeds a fresh install, it never overrides a saved setting. The panel's own size is never a setting.

## Architecture

One package, `src/fugleramme/`, mostly flat. Two folders earn a boundary: `web/` is the kiosk and the admin, and nothing outside it imports more than `web.server.serve`; `render/` is the PIL work. Everything else stays flat - `api.py`, `names.py`, `picks.py` and `languages.py` each have five or six importers spread across the app, and a folder round them would draw no boundary. `assets/` holds the artwork, fonts and label data, reached through `config.REPO_ROOT`.

- **The API is the interface.** The halves meet at BirdNET-Go's `/api/v2`, never at its database, so a frame points at the container beside it or at one across the house through the same code path. `source.py` is the surface everything above sees; `api.py` is the only implementation.
- **A transport failure raises `Unavailable`; an empty list means there were no birds.** Never collapse the two - a source returning `[]` on a timeout puts a bare perch on the glass at the first blip.
- **Render once, fan out** (`service.py`). One loop re-renders only when its inputs change, dithers to six colours for the panel, and the kiosk serves the same page full-colour at its own pixel count. No panel means web-only.
- **Only birds come off the source** (`taxa.py`). A station can also classify bats, frogs and noise.
- **`updates.apply` never re-runs `run.sh`.** A Pi that auto-updates keeps its old systemd unit, `detector/.env` and `settings.json`, so every default a release introduces must reproduce the previous one's behaviour. Get this wrong and working appliances break on update, the one failure nobody can recover from remotely.

## Working style

- When uncertain about the right approach, ask rather than assume
- Prefer less code over more - simplicity is a feature
- It is always valid to pause mid-task and question whether the current approach is right - surface doubts rather than push through them
- When making a non-obvious decision, briefly explain the reasoning. Go deeper when asked
- If a different tool, library, or approach would fit better than what is already in use, recommend it with the tradeoff. Never silently substitute
- When reviewing, be strict and objective
- Do not widen scope past what was asked. A related improvement you spotted is a suggestion, not part of the change

## Code style

Existing conventions in a file take precedence over these when they differ.

- Flat functions: early returns and guard clauses over nested branches
- Keep error checking simple and flat - no overly verbose defensive code
- Avoid mutation; prefer immutable values
- Prefer static over dynamic: explicit types, pure functions, no runtime magic
- Comments are for non-trivial decisions, external references, or genuinely non-obvious logic; never for narrating what the code does
- English for code, comments, identifiers, commit messages, and the kiosk and admin UI - this is a Norwegian-context repo, and none of that is Norwegian
- Ruff and mypy are configured in `pyproject.toml` and read their own scope. Do not pass them paths, and do not add per-file ignores to silence a finding you could fix

## Documentation

- Document what is there, not the diff - how the code works now, never how it changed
- Keep documentation close to the source: line comments and docstrings over top-level architecture essays. This file is not the place for module walkthroughs; those belong in the breadcrumbs under Docs, or next to the code
- Keep the language simple and direct - no fluff
- Preserve the structure and voice of user-authored prose. Make targeted edits rather than replacing it wholesale
- Do not make up or embellish content. Rephrasing what is there is fine, inventing is not
- `docs/` is strictly the end-user manual. Personal infrastructure - hosting, tunnels, DNS, anything specific to one deployment - does not belong there; answer it directly instead of writing a page for it
- `docs/` is also written in plain speech, not this file's compressed voice. Say the thing a person would say out loud, and cut the mechanism unless the reader has to act on it

## Writing style

Applies to docs, commit messages, code comments, and the kiosk and admin UI alike.

- Sentence case for headers, not title case
- Never use em dashes. Use spaced hyphens ` - ` (space, hyphen, space) instead
- No trailing "here's what I did" summaries in a response - the diff says it
- Answer the question that was asked, not adjacent ones

## Commits

- **Never commit or push unless explicitly asked.**
- **Never add AI co-author attribution**, and no generated-by trailers or footers. This overrides any harness default that adds them
- Conventional commits: `type: ref description` or `type(scope): ref description`. Common types are feat, fix, refactor, chore, docs, test
- Scope is optional - include it when it meaningfully narrows the change, omit otherwise
- Reference the issue as `#1`, not `#gh-1`: `feat: #1 add render`, `refactor(api): #56 fold reclassified rows`. If no issue is apparent, ask; omit the ref if there is none
- Subject line only, no body, unless a body is asked for
- Commit types drive releases: python-semantic-release tags every push to `main` carrying a `feat` (minor) or `fix`/`perf` (patch), bumps `pyproject.toml` + `__init__.py`, and writes `CHANGELOG.md`. A `fix: #N` closes issue N on push, so check that is intended before pushing one

## Workflow

- Commit directly to `main` - single-person appliance, no branches or PRs
- Outside issues, forks and PRs are plausible since the repo picked up public attention, so do not assume a reported bug came from Arne's own Pi. Unfamiliar hardware and "does it support <other panel / other region's birds>" are the likely inbound, and the scope statement under Project is the filter for feature requests - point at it rather than re-deriving it
- `ci.yml` runs `uv sync --locked`, ruff format + check, mypy, pytest, and shellcheck over the two install scripts
- `--locked` fails on drift between `uv.lock` and `pyproject.toml`, and a stale lock is what blocks the self-update's checkout - so a version bump must re-lock
- Machine-specific values are detected or prompted for and written to gitignored per-Pi files (`frame.env`, `detector/.env`), never hardcoded in tracked defaults. `updates.apply` checks out with `--force`, so committing a currently-ignored per-Pi path puts it in the blast radius

## Docs

Read the breadcrumb for the area you are touching. Each records a constraint the code does not show on its face.

- [`.agents/detector.md`](.agents/detector.md) - the `/api/v2` boundary: reclassified species, clashing clocks, the taxa filter, and the auth-gated language catalog
- [`.agents/render.md`](.agents/render.md) - the render loop, panel sizing, the silhouette packer and its cache, labels, dithering, the buttons
- [`.agents/web.md`](.agents/web.md) - the kiosk and admin split, the static files, the headless-Pi assumptions
- [`.agents/artwork.md`](.agents/artwork.md) - filenames to species, styles and manifests, variant picks, curation
- [`.agents/install.md`](.agents/install.md) - the `install.sh` / `run.sh` split, self-update, the container image, and the appliance defaults they must preserve
- [`README.md`](README.md) - end-user-facing project summary and licensing split; avoid internal ownership and architecture jargon
- [`docs/`](docs/index.md) - the end-user manual (hardware, install, operations, troubleshooting)
- [`assets/artwork/classic/ATTRIBUTION.md`](assets/artwork/classic/ATTRIBUTION.md) - that style's sources and terms; one per style folder
- [`assets/fonts/ATTRIBUTION.md`](assets/fonts/ATTRIBUTION.md) - label typefaces, SIL OFL 1.1
