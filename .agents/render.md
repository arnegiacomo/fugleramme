# Rendering

Covers `service.py`, `panel.py`, `buttons.py` and the `render/` package.

## Render once, fan out (`service.py`)

- The loop re-renders only when its inputs change: the species on the page, panel size, style, rotation, names + language + typeface.
- `settings.refresh_minutes` floors how often the *birds* may change the page (#64): at a busy station the species either side of the limit's cutoff trade on every call, and each trade is a full e-ink refresh. A changed `Settings` bypasses the floor, so a save is never held back by it.
- It dithers to 6 colors and pushes to the panel; the kiosk serves the same page full-color at its own pixel count. No panel means web-only, the same path as `--preview`.

## The panel sizes itself (`panel.py`)

- `resolution_of` is the single answer to how big the page is: the attached Inky, or `FALLBACK_PANEL_RESOLUTION`. Both renders derive from it.
- The admin resolution setting picks the kiosk's **height** only; `settings.web_size` takes the width from the panel's aspect. The collage packs into whatever rectangle it is handed, so a kiosk of a different shape would be a different page, not a scaled one - and the browser letterboxes anyway, so only the height is ever pixel-for-pixel.
- `settings.rotation` (counter-clockwise) shapes both, but only `push` turns pixels - the driver takes native landscape only.
- `inky.set_image` re-dithers anything that is not already a 6-color "P" image, so `render.dither.dither` must hand it a palette mapping 1:1 onto the driver's. `tests/test_panel.py` pins this.

## The render package

- `render/` is the PIL work: the collage and the plate, the furniture they share (`page.py`, `paper.py`, `fonts.py`, `sizes.py`), and `dither.py` for the panel's six colors.

## The collage is the product, not a dashboard

`render/collage.py` + `render/paper.py`.

- Birds are packed by their alpha silhouette so opaque pixels never overlap and nothing clips; halos are normalized and feathered onto paper at render time, assets untouched.
- The packer works in whole pixels (`_STEP`, `_OVERLAP_PX`), so it is not scale-invariant: it packs at `_PACK_SHORT` and scales the placements to the output. Packing at the output size instead swapped birds between the panel and the kiosk. Sprites and labels are redrawn from source at the target size, never resampled from the packed raster, and a label is centred in the box `_with_label` reserved for it since a re-rasterized font is not exactly `width × scale`.
- Packing is ~90% of a render and both outputs pack identically, so `_placements` caches it (`_layouts`, keyed on the species and their artwork, the pack size, and the resolved label strings). The loop's panel render pays for the kiosk's: 5.4s to 0.5s here. The lock is held across the pack so the second caller waits rather than packing its own copy.
- No-artwork species are omitted. An empty window draws one branch from the style's own `perches/`, chosen by day (`collage.perch_day`, in both cache keys).
- `selected_species` is the single answer to which birds are on the page: it drops what the style cannot draw, then applies the admin's limit under the admin's ranking - `rarest_ever` costs a second summary call, since a resident heard twice today is only a rarity by the window's reckoning. There is no ceiling of the frame's own - a fresh frame ships at `settings.DEFAULT_LIMIT`, and `NO_LIMIT` really draws every species the window holds, so a long lookback at a busy station is the admin's to bound. The key reads *that* list, not the window's - under a limit two birds can trade places across it while the set of species heard sits still.
- A label's box joins its bird's collision mask, so it tucks under the body and never lands on a neighbour. A second language stacks below in parentheses.
- On the panel labels are hard-thresholded to pure black: antialiased grey dithers into colour speckle.

## The buttons are settings writes (`buttons.py`)

- Plain GPIO read with `gpiod` on a daemon thread; pins key off `Panel.driver` (the 13.3" moves C to line 25).
- A press only ever calls `SettingsStore.update`, so nothing crosses threads and presses during a refresh coalesce.
- A cycles display modes, B toggles names, C rotates a quarter turn clockwise, and D walks styles.
