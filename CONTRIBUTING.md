# Contributing

This is a one-person project, but issues and PRs are very welcome - fixes, docs and artwork most of all!

Open an issue before building anything big, so you don't spend a weekend on something that's already half-designed or deliberately out of scope. Small fixes just need the PR.

## Running it without a Pi

Everything except the panel, the buttons and the mic runs on a workstation:

```bash
uv sync
uv run fugleramme-fake-detector               # stand-in BirdNET-Go on :8090
uv run fugleramme-dev                         # :8080, restarts on save
```

Kiosk on `http://localhost:8080/`, admin on `/admin`.
`uv run fugleramme-frame --preview out.png` renders the collage once and exits.

The fake serves the same `/api/v2` endpoints the frame reads, over generated
detections; `--auth` and `--down` reproduce a locked-down and an unreachable
station. To work against a real one instead, pass its address:
`uv run fugleramme-dev --detector http://birdnet.local:8090`.
`uv run fugleramme-check` says whether a detector answers everything the frame
needs, and is the first thing to run when a page comes up empty.

> [!NOTE]
> I can only test on the hardware I have. If a change touches the panel, the
> buttons or the install scripts, say in the PR what you ran it on.

## Before you open a PR

CI runs these (good idea to run them yourself first):

```bash
uv run ruff format
uv run ruff check
uv run mypy
uv run pytest -q
```

If you touched `pyproject.toml`, commit `uv.lock` with it - CI installs with
`uv sync --locked` and fails on a drifted lock.

Whether you write the code yourself or use an LLM is up to you, as long as you can explain, understand and be accountable for it.

## Commit messages

Conventional commits (with the issue number if applicable):

```
feat: #23 add a mic-less display mode
docs: fix the passepartout measurements
```

Releases are cut straight from these:

| Type | Release kind |
| --- | --- |
| `feat` | minor |
| `fix`, `perf` | patch |
| anything else (e.g. `docs`) | no release |

PRs are squashed, so the title is the message that counts.

## Artwork

Half the point of this project is showing off amazing public-domain natural-history illustration, so every bird has to be cut from a real plate. Nothing AI-generated.
Retouching a scan with AI is fair game - e.g. the `classic` perches were tidied up that way.

`assets/artwork/custom/README.md` covers the file itself: a transparent PNG, named
for the scientific name exactly as BirdNET-Go emits it
(`assets/birdnet_labels_v2.4.txt`), with `-2`, `-3` for more of the same bird. A
name that isn't an existing label fails the test suite.

Then, for the style folder it lands in:

- **The licensing has to work.** Public domain, or terms compatible with the
  folder's own. `classic` is CC BY-SA 4.0.
- **The folder's `manifest.json` names each PNG's source and links its
  plate** (`"bird.png": {"source": "gould", "url": ...}`). A new file means a
  new entry.
- **`ATTRIBUTION.md` names the works and their terms.** A new source means a new
  entry.

**A whole new style** is the nicest thing you can contribute: its own folder
under `assets/artwork/`, its own `ATTRIBUTION.md`, picked from the admin page.

**A missing bird in `classic`** is better as an issue than a PR - link the plate
you have in mind (ideally on Wikimedia Commons or similar). The cutting and
colour work happens in a curation pipeline that isn't in the repo
(workstation-only, and gitignored), so a cut-out done another way tends to sit
wrong on the page.

## Docs

`docs/` is the manual for someone building and living with a frame. Internals
and mechanism don't belong there.

The install guide is written from macOS. If you set yours up from Linux or
Windows, a PR extending it is very welcome.

## Licensing

The code is MIT and contributions come in under the same licence - there's no
CLA. For artwork, you're telling me you have the right to contribute the images.
