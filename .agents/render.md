# Rendering

Covers `service.py`, `panel.py`, `buttons.py` and the `render/` package.

## Render once, fan out (`service.py`)

- The loop re-renders only when its inputs change: the species on the page, panel size, style, rotation, names + language + typeface.
- `settings.refresh_minutes` floors how often the *birds* may change the page (#64): at a busy station the species either side of the limit's cutoff trade on every call, and each trade is a full e-ink refresh. A changed `Settings` bypasses the floor, so a save is never held back by it.
- It dithers to 6 colors and pushes to the panel; the kiosk serves the same page full-color at its own pixel count while it is locked to the panel, else its own page. No panel means web-only, the same path as `--preview`.

## The panel sizes itself (`panel.py`)

- `resolution_of` is the single answer to how big the page is: the attached Inky, or `FALLBACK_PANEL_RESOLUTION`. The panel's render derives from it; the kiosk's only while locked.
- The admin resolution setting picks the kiosk's **height**. Locked to the panel (`web_lock`, the default), `settings.web_size` takes the width from the panel's aspect; unlocked, or with no panel, the kiosk takes its own shape from `web_aspect` and `web_portrait` and ignores the rotation (the admin dims Rotation when there is no panel). The collage packs into whatever rectangle it is handed, so a different shape is a different page, not a scaled one: the birds land elsewhere. The admin preview shows the panel's page when there is a panel, the kiosk's when there is none.
- `settings.rotation` (counter-clockwise) shapes the panel and a locked kiosk, but only `push` turns pixels - the driver takes native landscape only.
- `inky.set_image` re-dithers anything that is not already a 6-color "P" image, so `render.dither.dither` must hand it a palette mapping 1:1 onto the driver's. `tests/test_panel.py` pins this.

## The render package

- `render/` is the PIL work: the collage and the plate, the packers behind the collage (`packing.py`), the furniture they share (`page.py`, `paper.py`, `fonts.py`, `sizes.py`), and `dither.py` for the panel's six colors.

## The collage is the product, not a dashboard

`render/collage.py` + `render/paper.py`.

- Birds are packed by their alpha silhouette so opaque pixels never overlap and nothing clips; halos are normalized and feathered onto paper at render time, assets untouched.
- A bird's size is its mass compressed by `SIZE_EXPONENT` times its plate's `sizes.span_ratio`. The ratio rides in the weight, not in `dim` alone, so `base`'s area estimate and its 70% cap still measure what gets drawn. `_layouts` does not key on the boxes, so a tool that changes them at runtime has to clear it.
- The packer works in whole pixels (`packing._STEP`, `collage._OVERLAP_PX`), so it is not scale-invariant: it packs at `_PACK_SHORT` and scales the placements to the output. Packing at the output size instead swapped birds between the panel and the kiosk. Sprites and labels are redrawn from source at the target size, never resampled from the packed raster, and a label is centred in the box `_with_label` reserved for it since a re-rasterized font is not exactly `width × scale`.
- Packing is ~90% of a render and both outputs pack identically while the kiosk is locked to the panel, so `_placements` caches it (`_layouts`, keyed on the species and their artwork, the pack size, the layout, and the resolved label strings). The loop's panel render pays for the kiosk's: 5.4s to 0.5s here. An unlocked kiosk is its own entry and packs on its first request after a change. The lock is held across the pack so the second caller waits rather than packing its own copy.
- `settings.margin` is bare paper along the edge, a percent of the short side (`modes.context` hands the render a fraction), for a mat whose cutout covers the panel: the collage packs inside it, and the plate takes the larger of it and its own `_MARGIN`, so a setting under 8% leaves a plate alone. It is in `state_key` and the collage cache key like anything else the page is a function of, and unconditionally, unlike the layout, since every mode can read it.
- No-artwork species are omitted. An empty window draws one branch from the style's own `perches/`, chosen by day (`collage.perch_day`, in both cache keys).
- `selected_species` is the single answer to which birds are on the page: it drops what the style cannot draw, then applies the admin's limit under the admin's ranking - `rarest_ever` costs a second summary call, since a resident heard twice today is only a rarity by the window's reckoning. There is no ceiling of the frame's own - a fresh frame ships at `settings.DEFAULT_LIMIT`, and `NO_LIMIT` really draws every species the window holds, so a long lookback at a busy station is the admin's to bound. The key reads *that* list, not the window's - under a limit two birds can trade places across it while the set of species heard sits still.
- A label's box joins its bird's collision mask, so it tucks under the body and never lands on a neighbour. A second language stacks below in parentheses.
- On the panel labels are hard-thresholded to pure black: antialiased grey dithers into colour speckle.
- The numbered key (`settings.name_key`) is a way of drawing names, not a mode. `_fit_key` takes its strip first - below on a portrait page, beside on a landscape one, at most `_KEY_SHARE` deep, dropping the second language if even the smallest type overflows - and the birds pack into the rest. Numbers go in reading order, which is only known after the pack, so every bird reserves the widest number. `modes.context` caps the page at `KEY_LIMIT` while it is on.

## How the birds are placed is a setting

`render/packing.py`, `settings.layout`.

- `LAYOUTS` is the one table the admin menu and the settings coercion read; each entry carries its packer, the label and blurb the admin shows, and how far the size search may push it. `docs/display.md` lists the layouts by hand, so a new entry has to be written there too. Only the collage has a layout, so `state_key` carries it for windowed modes alone and the admin dims it beside the lookback for the rest.
- `spiral` takes the first non-colliding position on an outward walk from the centre. It is the default, and the reason a page reads as a round blob with bare corners: a disc grows into a rectangle badly. `voids` scores every legal position at once out of one FFT, by which paper is emptiest, so an aesthetic rule costs no more than a collision test.
- `voids` packs on a grid of `packing.K` pack pixels, max-pooled from the footprint. Pooling can over-report a collision but never miss one, and it hands each bird up to a cell of padding: the same `collage._OVERLAP_PX` nestles looser under it than under the spiral.
- The size search descends by 0.9 to the first fit, then bisects into the size that failed (`Layout.refine`). Three more packs buy 4-10% larger birds where a pack is cheap; a spiral pack costs three times as much, so it keeps its first fit. Nothing failed means `base` was already the ceiling, and bisecting from there would shrink a page that fitted.

## The buttons are settings writes (`buttons.py`)

- Plain GPIO read with `gpiod` on a daemon thread; pins key off `Panel.driver` (the 13.3" moves C to line 25).
- A press only ever calls `SettingsStore.update`, so nothing crosses threads and presses during a refresh coalesce.
- A cycles display modes, B toggles names, C rotates a quarter turn clockwise, and D walks styles.
