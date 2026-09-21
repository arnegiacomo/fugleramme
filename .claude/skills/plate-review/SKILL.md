---
name: plate-review
description: Cut a bird out of a scanned public-domain plate for a fugleramme style folder, and build the local review page that toggles each scan against the finished plate. Use when adding or recutting classic artwork for fugleramme, when a maintainer reports blending or outline faults on a plate, or when the user asks to review plates before a PR.
---

# Plate review

The deliverable is a plate the user has looked at. Cut, build the review page, let the user
pass or fail each bird, fix what failed, and only then hand over for commit. Never skip the
review because a contact sheet looked fine: every fault below was invisible at that size.

The scripts are `tools/platereview/` in the repo, with a README covering the same ground for
a person rather than an agent. Run them with a Python that can import `fugleramme`
(`uv run python tools/platereview/plate.py ...`); `build.py` renders through the frame's own
paper code.

## Workflow

1. **Crop.** Write `<bird>/spec.json` with `scan`, `box` (scan px), `paper_min` (232 suits
   the Audubon scans) and `seed` (a point inside the bird, crop px). `plate.py crop spec.json`
   writes `crop.png` and a gridded overview. `plate.py zoom spec.json x0,y0,x1,y1 crop.png name [step]`
   gives gridded close-ups for reading coordinates.
2. **Decide what is bird and what is scenery, before cutting anything.** Read the *scan*,
   zoomed. A feature's identity is not readable from the cut-out or a thumbnail, and getting
   this wrong in either direction wastes a whole round. Plumes have barbs along their length
   and attach to the body; blades and stems are smooth, tapered, and cross the bird. Colour
   helps - on the Audubon scans grass is pale green and plumes are white.
3. **Cut.** Add what the bird needs, all in crop px:
   - `remove`: polygons over branches and neighbours to drop.
   - `discs`: `[x, y, r]` plugs that round a cut branch end and keep a pale branch sealed.
   - `gaps`: seeds in enclosed paper (between legs and perch) to tone to the page.
   - `outline`: a hand-traced edge, only for a bird on painted ground. Follow it with
     `snap.py spec.json <ymin>`, which pulls the trace onto the inked edge and keeps the
     original as `outline_traced`. Check the result with `overlay.py`.
   - `paper_clean` (default 241), `seal`, `regrow`: see Faults.
   `plate.py cut spec.json` writes `cut.png` and `check.jpg` on a loud ground.
4. **Finish.** `finish.py cut.png final.png` crops, downscales to 1200 px in floating point
   and sets the soft edge to the exact halo tone. Hand `final.png` to `tools/add_bird.py`,
   never `cut.png`.
5. **Add.** `tools/add_bird.py final.png --style classic --key <key> --source <key> --url <plate page> --preview <png>`.
   Take the key from `fugleramme.names.normalize`, not from the BirdNET label. To replace a
   plate, remove the file and add again: the tool gives the first free name. If the manifest
   entry already exists, check `git diff` afterwards and restore it if only the URL changed.
6. **Review.** List the plates in `<review>/plates.json` (`id`, `name`, `pr`, `plate`, `scan`,
   `cut`) and run `build.py <review> [ids]`, which writes `birds.js` and `img/`. The page is
   `tools/platereview/index.html`, checked in and never generated; `review.sh` serves a folder
   for a browser that refuses `file://`. The user toggles scan against plate, reads the zooms,
   marks Pass or Needs work, and pastes "Copy review notes" back.
   Mode 3: red is flat paper where the bird should be; magenta is the dotted ring. Red between
   legs and a perch is a declared gap and fine. On a bird cut from painted ground, red along
   the traced edge is a false alarm.
   Mode 4 is computed in the browser from two images and nothing else: the scan, and the
   shipped plate as RGBA with nothing composited under it. Two reads per pixel - is the scan
   darker than page tone, is the plate opaque and not the halo's own paper tone - give four
   states, and every pixel is in exactly one. Blue is drawn ink the plate no longer shows:
   grass, a branch, a neighbour, or anything the halo painted over. Red is a pixel the plate
   shows that the scan never drew on: a hole, or a declared gap between legs and a perch.
   Plain is the bird as it prints, grey is page on both sides. The one threshold is how dark
   a scan pixel must count as drawn on, and it is a slider: pale plumage sits near page tone
   and speckles red as you raise it, so move the slider before calling red a fault.
7. **Fix and rebuild** until the user passes every plate. Verdicts live in the browser and
   survive a rebuild, so tell the user which birds changed. **Look at the whole preview after
   every re-cut**, not only the region you edited - a heron once lost both legs while every
   crop being checked looked right.

## Faults this process exists to catch

- **A severed leg, tail or bill.** The cutter keeps only the piece containing `seed`, so a
  spec edit that cuts a thin structure off the body deletes it silently. `cut` prints the
  bird's pixel count and warns `! N px not connected to the seed`; record the count of a cut
  you trust and compare after every edit. A large drop means something came off. Do not edit
  an `outline` by index arithmetic - use `overlay.py` and edit with the shape visible, or
  extend the boundary outward only.
- **Paper fill leaking into pale plumage.** A bill, belly or white tail feather is lighter
  than `paper_min`, and its outline is often faint or dotted. The cutter therefore lets the
  outside in only through clean paper (`paper_clean`), seals openings narrower than `seal`,
  and lets the fill back into clean paper for `regrow` px. A scan whose paper is darker near
  the page edge needs a lower `paper_clean`; a narrow gape or toe gap left scan-white needs
  a larger `regrow`. `keep` polygons are the last resort.
- **The dotted ring.** `add_bird.py` corrupts low-alpha colour when it has to shrink a
  cut-out (it premultiplies, and so does Pillow's RGBA resize). `finish.py` avoids the step.
  `ringscan.py *.webp` counts the damage; shipped plates must read 0.
- **Loose hand traces.** Pink ground fringes and clipped ink on a bird cut from scenery.
  Use `snap.py`; do not try to remove ground by colour, claws are the same brown.

## Occlusion is an outcome, not a fault

Where the artist painted a leaf, a stem or another bird in front of the subject, that edge is
genuinely hidden and removing the obstruction must leave a straight edge. The alternative is
inventing linework the artist never drew, which is worse. Say so in the PR: an undisclosed
straight edge reads as a cutting defect and gets sent back.

## Delegating a cut

Per the user's standing preference, cutting agents run on the cheapest model and the parent
reviews. Tell a cutting agent to **report the bird's pixel count** and **attach the full
preview** - those are what let the parent catch a bad cut without redoing the work. Tell it to
read the image rather than hunt for pixel thresholds; agents burn long runs that way.

## Repo rules that bite

Artwork commits are `chore(assets): #ref ...`, subject only, no AI attribution. Never commit
or push unless the user asks, and never post to GitHub - the user posts their own comments.
Plates are single birds with a natural or rounded branch end. Disclose any retouching or
colour correction in the PR, and any occlusion. PR descriptions stay short, with a preview of
every bird.
