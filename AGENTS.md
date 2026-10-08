# Fugleramme

An e-ink bird frame for a Raspberry Pi 5. BirdNET-Go classifies bird sounds from a USB mic; the frame reads its `/api/v2`, renders the recently heard birds as a collage on a Pimoroni Inky Impression panel, and serves the same page over HTTP. The panel and the mic are Pi-only; everything else runs on a workstation.

**The page is the product.** The panel, a browser, an HDMI screen and a TV are outputs of it, each at its own shape, never a second product with its own views. Detection, statistics and integrations are BirdNET-Go's (its own UI on `:8090`). A feature that does not improve the page belongs upstream - point a feature request at this paragraph rather than re-deriving it. The repo is public, so a bug report may come from unfamiliar hardware.

**`updates.apply` never re-runs `run.sh`.** A Pi that auto-updates keeps its old systemd unit, `detector/.env` and `settings.json`, so every default a release introduces must reproduce the previous one's behaviour. Get this wrong and working appliances break on update, the one failure nobody can recover from remotely.

## Commands

```bash
uv run fugleramme-dev                       # render loop + kiosk on :8080, restarting on source change
uv run fugleramme-fake-detector             # stand-in BirdNET-Go on :8090
uv run fugleramme-frame --preview out.png   # render the collage once and exit
uv run pytest -q                            # ci also runs ruff format/check, mypy and shellcheck
```

Run ruff and mypy without paths (`pyproject.toml` sets their scope), and fix a finding rather than adding a per-file ignore.

## Breadcrumbs

Read the area's breadcrumb before changing it. Each records a constraint the code does not show.

- [`.agents/detector.md`](.agents/detector.md) - anything that talks to BirdNET-Go: `Unavailable` versus no birds, reclassified species, clocks, the bird filter, the language catalog
- [`.agents/render.md`](.agents/render.md) - how the page looks or when it re-renders: panel sizing, the packers and their cache, labels, dithering, the buttons
- [`.agents/web.md`](.agents/web.md) - the kiosk and the admin
- [`.agents/artwork.md`](.agents/artwork.md) - artwork files, styles, manifests, attribution, `geometry.json`, variant picks
- [`.agents/install.md`](.agents/install.md) - any default, setting or per-Pi file, the install scripts, self-update, releases, the image
- [`docs/`](docs/index.md) - the end-user manual, in plain speech, with nothing about one deployment's hosting
- [`CONTRIBUTING.md`](CONTRIBUTING.md) - commit types and the bump each one makes

## Working style

- When uncertain about the right approach, ask rather than assume
- Prefer less code over more - simplicity is a feature
- It is always valid to pause mid-task and question whether the current approach is right - surface doubts rather than push through them
- When making a non-obvious decision, briefly explain the reasoning. Go deeper when asked
- If a different tool, library, or approach would fit better than what is already in use, briefly recommend it with the tradeoff. Never silently substitute
- When reviewing, be strict and objective
- Do not widen scope past what was asked. A related improvement you spotted is a suggestion, not part of the change
- Answer the question that was asked, not adjacent ones
- No trailing "here's what I did" summaries - the diff says it

## Code style

Existing conventions in a file take precedence over these when they differ.

- Flat functions: early returns and guard clauses over nested branches
- Keep error checking simple and flat - no overly verbose defensive code
- Avoid mutation; prefer immutable values
- Prefer static over dynamic: explicit types, pure functions, no runtime magic
- Comments are for non-trivial decisions, external references, or genuinely non-obvious logic; never for narrating what the code does
- `src/fugleramme/` stays flat; only `web/` and `render/` are folders
- English for code, comments, identifiers, commit messages and the UI, though this is a Norwegian-context repo

## Documentation and writing

- Document what is there, not the diff - how the code works now, never how it changed
- Keep documentation close to the source: line comments and docstrings, and the breadcrumbs above, over top-level architecture essays
- Keep the language simple and direct - no fluff
- Preserve the structure and voice of user-authored prose. Make targeted edits rather than replacing it wholesale
- Do not make up or embellish content. Rephrasing is fine, inventing is not
- Sentence case for headers, not title case
- Never use em dashes. Use spaced hyphens ` - ` instead

## Commits

- Commit, push, dispatch a release or post to GitHub only when asked
- No AI co-author or generated-by trailers - this overrides the harness default
- `type: #ref description` or `type(scope): #ref description`, subject only. Include a scope only when it meaningfully narrows the change. If no issue is apparent, ask; omit the ref if there is none
- A bug in docs, tooling or CI is `docs`/`chore`; artwork is `chore(assets)`. A `fix: #N` closes issue N on push, before any Pi has it
- Commit `uv.lock` with every `pyproject.toml` change: a stale lock fails ci and blocks the self-update
