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
uv run python -m fugleramme.seed --count 40 # write a BirdNET-Go-shaped fixture DB so the collage has content
./setup.sh                                   # Pi only: one-command bootstrap (deps + BirdNET-Go + services)
uv run pytest -q                            # run tests
uv run pytest tests/test_artwork_names.py   # run a single test file
```

`--panel {4.0,7.3,13.3}` / `--resolution WxH` set render resolution (default 7.3" / 800x480); `--db`, `--images`, `--host`, `--port` are also flags.

## Architecture

Work is split by concern across GitHub issues: **#1 frame service**, **#2 admin interface** (not yet built), **#3 detector** (BirdNET-Go + mic), **#7 direct-read refactor**. #1 and #3 exist in code; each issue is the source of truth for its half.

The two halves meet only at the DB file. BirdNET-Go (Docker) writes its own normalized SQLite, bind-mounted to a persistent host path (`detector/data`, on NVMe on the Pi); the frame reads that same file directly, read-only. `db.py` is a thin adapter and the only code that knows BirdNET-Go's schema (species come from a `labels`/`label_types` join, timestamps are epoch seconds); it exposes `species_last_24h` / `recent` / `latest` / `stats` so nothing else sees BirdNET-Go SQL. There is no frame-owned DB and no sync process (dropped in #7). WAL lets the render loop and the HTTP server each hold a read connection in one process without contention. Detector detail: [`detector/README.md`](detector/README.md).

**Render once, fan out** (`service.py`): the loop re-renders only when the set of species seen in the last 24h changes, dithers the collage to 6 colors for the panel (`render.py`), and pushes it if a panel is present. The kiosk serves the same collage full-color per request (`server.py`, cached per species-set). If the Inky is absent it logs a warning and runs web-only, the same path as `--preview`.

**The collage is the product** (`collage.py` + `paper.py`), not a single-detection frame or a dashboard (stats/config are #2). Birds are packed by their alpha silhouette so opaque pixels never overlap and nothing clips; the von Wright cut-outs' paper "halos" are normalized to one tone and feathered onto a textured paper page at render time (assets untouched). No-artwork species are omitted.

**Name to artwork** (`names.py`): normalize the detector's scientific name ("Turdus merula") to the filename shape ("turdus-merula.png") and exact-match in `assets/birds/`, random-picking among numbered variants. There is no runtime alias map because the assets were renamed from 1800s von Wright taxonomy to modern eBird / BirdNET v2.4 names (`scripts/rename_artwork.py`). `tests/test_artwork_names.py` enforces the invariant: every filename must be a BirdNET label (from `assets/birdnet_labels_v2.4.txt`), a hybrid (`-x-`), or a listed exception.

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
- English for code, comments, and commits, even though the UI strings are Norwegian

## Docs

- [`README.md`](README.md) - project summary and licensing split
- [`detector/README.md`](detector/README.md) - BirdNET-Go container, the direct-read DB, and Pi deployment
- [`assets/birds/ATTRIBUTION.md`](assets/birds/ATTRIBUTION.md) - artwork provenance and CC BY-SA 4.0 terms
- [`wikimedia-scrape/README.md`](wikimedia-scrape/README.md) - how the cut-outs are scraped and background-removed from the von Wright plates
