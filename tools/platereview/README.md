# Plate cut and review

Cut a bird out of a scanned public-domain plate, then look at what you cut before it ships.

Curation is a workstation job and the frame never runs any of this - see the `scripts/` note
in `.gitignore`. What lives here is the half that decides whether a plate is good enough to
ship, which is the half worth keeping and sharing. The cut is deterministic: a fault is a spec
edit and a re-cut, never a new attempt.

## The review page

`index.html` is checked in and never generated. A review folder holds only what its plates
differ in - `birds.js` and `img/<id>/*.jpg`, written by `build.py` - so nothing regenerates
the page and no review folder carries a copy of it.

It loads `birds.js` with a script tag rather than fetching JSON, because `fetch()` of a
`file://` URL is blocked as cross-origin and double-clicking `index.html` has to keep working.

Five layers, toggled with `1` to `5` or by letting it flip between scan and plate:

| | |
|---|---|
| **Scan** | the crop, untouched |
| **Plate** | the shipped WebP on the frame's own paper, through the frame's own halo code, as it will print |
| **Flags** | flat paper where the bird should be, in red. Magenta is the dotted ring |
| **Cut** | blue where the cut removed something drawn, red where it kept blank page inside the bird |
| **Cut-out** | the shipped WebP itself on a loud blue ground, where the halo shows as a band to judge its width and evenness |

Red between legs and a perch is a declared gap and fine. Red round a cut branch end, or over
painted ground, is the halo covering ink, as intended. Red inside the bird is a fault. White
plumage that was cut away shows in neither colour, because it is the colour of paper - catch
that by toggling scan against plate.

Mode 4 is computed in the page, in JavaScript, from two images and nothing else: `scan.png`
and `cut.png`, the shipped plate as RGBA with nothing composited under it. No classification
is worked out in Python and handed over - the browser reads both images into a canvas and
decides every pixel itself, which is why moving the slider changes the answer live.

It deliberately does not diff `plate.png`, the version on paper. That one carries generated
paper texture, a halo and WebP, all of which differ from the scan everywhere by design and
none of which is the cut.

Two reads per pixel, both taken in the browser from those two images - is the scan darker
than page tone here, and is the plate opaque here and carrying something other than the
halo's own paper tone. They give four states, and every pixel is in exactly one:

- **blue** - drawn on, and the plate no longer shows it. Grass, a branch, a neighbouring
  bird. Also anything the halo painted over, which hides ink just as effectively as cutting
  it. This is most of what a good cut does, and should look like the thing you meant to lose.
- **red** - the plate shows a pixel the scan never drew on. A hole in the bird, or page left
  inside the silhouette. Between legs and a perch it is a declared gap.
- **plain** - drawn on and still shown: the bird, in its own colours.
- **grey** - blank on both sides. The page round the bird, where nothing happened.

There is no fifth case to fall through into, which matters: an earlier version rendered the
halo band as background, and 30,000 px of ink it had covered simply vanished from the layer.

The one threshold is how dark a scan pixel must be to count as drawn on, and it is a slider.
Pale plumage sits close to page tone, so a cream breast reddens as you raise it - move the
slider before reading red as a fault. `scan.png` and `plate.png` are PNG so that nothing
here is reading JPEG artifacts.

Verdicts and notes live in the browser and survive a rebuild. "Copy review notes" gives you
the lot as text.

## The crop preview

`crop.html` is the same idea one step earlier: look at where a crop is going to land before
anything is cut from it. It shows the whole scan at full resolution with the spec's `box`
drawn on it, the crop that box gives, and a loupe at scan pixels.

Drag the box or its handles to where the crop belongs. The proposal stays on the page as a
dashed outline. Mark each crop Accept, Needs work or Skip and say why, and "Copy crop notes"
gives the lot as text, one line a crop, with the box to put in the spec. The page never
edits a spec itself.

A scan can hold more than one crop: separate vignettes on one page, or rival boxes for the
same one. Every crop proposed on the same scan is outlined and numbered on it, and clicking
an outline switches to that crop. Skip is for a candidate you do not want. Drag on the scan
outside the box to add a crop nobody proposed: it has no spec yet, lives in the browser, and
comes back in the notes as a `NEW` line.

The red dot is the spec's `seed`. The seed is in crop pixels, so moving the box moves it:
the notes carry where it lands in the new crop, or say that it fell outside.

A corrected box and a verdict answer one proposal. When the spec proposes a different box
they are dropped and only the note is kept.

```bash
uv run python crops.py <review>         # crops.json in, crops.js and img/ out
uv run python crops.py <review> heron   # rebuild one bird
```

`crops.json` lists `id`, `name`, the path to the bird's `spec`, and optionally `url` - the
full-resolution scan file itself. A spec whose `scan` is not on disk is downloaded from
`url` to that path, which is where `plate.py crop` then reads it. Entries whose specs name
the same `scan` are crops of one page.

It is a page of its own rather than a mode of the review: a review bird has a shipped plate
and a cut, and a bird at this stage has neither.

## Running a review

```bash
./review.sh                    # serve the one review folder beside this script, and open it
./review.sh review-demo 9000   # a named folder, a named port
```

Or just open `index.html` in the folder. The script is for when a browser refuses `file://`.
A folder with `crops.js` and no `birds.js` yet opens on `crop.html`.

## Cutting a bird

```bash
uv run python plate.py crop <bird>/spec.json          # crop.png and a gridded overview
uv run python plate.py cut  <bird>/spec.json          # cut.png and check.jpg on a loud ground
uv run python finish.py <bird>/cut.png final.png      # downscale, halo-tone the soft edge, deepen a faded scan
uv run python ../add_bird.py final.png --style classic --key <key> --source <src> --url <plate>
```

`spec.json` is the whole interface: `scan`, `box` in scan px, `paper_min`, a `seed` inside the
bird, then per-plate hints in crop px - `remove` polygons over branches and neighbours, `discs`
to round a cut branch end, `gaps` to tone enclosed paper to the page, `keep` to stop the paper
flood walking into white plumage, and `outline` for a bird on painted ground (follow it with
`snap.py`, which pulls a loose trace onto the ink edge). `fade` takes `[polygon, px]` pairs: inside
each polygon the bird's edge fades into the page over about `2*px` instead of being sliced, for
plumage the artist blurred into a painted ground.

**Watch the pixel count.** `cut` prints how many pixels the bird came to. Record it for a cut
you trust and compare after every edit: the cutter keeps only the piece your `seed` is in, so
severing a leg or a tail deletes it silently. A large drop means something came off, and a
`! N px not connected to the seed` line says so outright.

Then build a review and look at it. Every fault worth catching has been invisible at
thumbnail size.

```bash
uv run python build.py <review>       # plates.json in, birds.js and img/ out
uv run python build.py <review> heron # rebuild one bird, the rest keep their images
```

`plates.json` lists `id`, `name`, `pr`, and paths to the shipped `plate`, the `scan` crop and
the `cut`.

## The rest

- `ringscan.py *.webp` counts dark pixels under a soft edge. A shipped plate must read 0.
- `overlay.py` draws a trace on the crop, for editing an `outline` with the shape visible.
- `review-demo/` is a worked example: two plates from PR #135, both the ones the maintainer
  sent back. Built review folders are gitignored, so rebuild it rather than expecting images.
