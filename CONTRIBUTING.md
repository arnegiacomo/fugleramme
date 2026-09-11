# Contributing

This is a one-person project, but issues and PRs are very welcome - fixes, docs and artwork most of all!

| You have | Where it goes |
| --- | --- |
| A fix, a doc change, a bird you've cut | **A PR.** No issue needed. Ref an existing if relevant. |
| Something is broken | **A [bug report](https://github.com/arnegiacomo/fugleramme/issues/new/choose)** |
| An idea, a feature request, a setup question, showcase or anything else | **[Discussions](https://github.com/arnegiacomo/fugleramme/discussions)** |

The one thing worth asking about first is a big feature or change - start it in Discussions so you don't spend a weekend on something that's already half-designed or deliberately out of scope.

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

**Artwork is `chore`, not `fix`** - `chore(assets): add Sturnus unicolor`. A new
bird isn't a new version of the software, so it is added to the next release rather than cutting one of its own.

## Artwork

Half the point of this project is showing off amazing public-domain natural-history illustration, so every bird has to be cut from a real plate. Nothing AI-generated.
Retouching a scan with AI is fair game - e.g. the `classic` perches were tidied up that way.

**A bird missing from `classic`** is the usual one. Cut it and open a PR. If
you'd rather point at a plate than cut it yourself, open a
[Missing bird](https://github.com/arnegiacomo/fugleramme/issues/new/choose)
issue instead.

**A whole new style** is the nicest thing you can contribute: its own folder
under `assets/artwork/`, its own `ATTRIBUTION.md`, picked from the admin page.

Some things no tool can check, so they're what an artwork PR gets read for:
whether the licensing is A-ok, the illustration looks good and fits the styles, and whether the cut-out blends nicely on the page.

The rest is mechanical. `assets/artwork/custom/README.md` covers the file
itself: a transparent WebP or PNG, named for the scientific name exactly as BirdNET-Go
emits it (`assets/birdnet_labels_v2.4.txt`), with `-2`, `-3` for more of the
same bird. A name that isn't an existing label fails the test suite.

After cutting a bird, use the artwork tool to add it as an asset:

```bash
uv run python tools/add_bird.py ~/Desktop/bird.png
```

It searches BirdNET species and existing artist/source keys, assigns the next
variant filename, and updates the style manifest. `fzf` provides live search
when installed. See [Adding artwork](docs/adding-artwork.md).

`--preview` renders your cut-out on the page's paper before it is written, which
is the quickest way to see whether the halo blends:

```bash
uv run python tools/add_bird.py ~/Desktop/bird.png --preview /tmp/bird.png --dry-run
```

Then, for the style folder it lands in:

- **The licensing has to work.** Public domain, or terms compatible with the
  folder's own. `classic` is CC BY-SA 4.0.
- **The folder's `manifest.json` names each file's source and links its
  plate** (`"bird.webp": {"source": "gould", "url": ...}`). A new file means a
  new entry.
- **`ATTRIBUTION.md` names the works and their terms, and gives each one its
  manifest key** (``Manifest key: `gould`.``). A new source means a new entry -
  the test suite fails a manifest key no entry names.
- **An entry describes a work, not a plate.** Three or four lines: title,
  creators, dates, where the scans came from, terms, manifest key. No volume or
  plate numbers, no per-plate engravers or printers - the manifest already links
  the plate page, which carries all of that. A bird from a work already listed
  touches `manifest.json` alone, and a key exists to separate terms, so don't
  add one for a source an existing entry already covers.

## Docs

`docs/` is the manual for someone building and living with a frame. Internals
and mechanism don't belong there.

The install guide is written from macOS. If you set yours up from Linux or
Windows, a PR extending it is very welcome.

## Licensing

The code is MIT and contributions come in under the same licence - there's no
CLA. For artwork, you're telling me you have the right to contribute the images.
