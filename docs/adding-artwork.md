# Adding artwork

## Find what is missing

The admin page marks a bird the current style cannot draw with "no art". The
frame logs the same list whenever re-renders:

```bash
journalctl -u fugleramme-frame | grep "No artwork"
```

## Source an image

Wikimedia Commons is a good place to find public domain artwork. Search for the scientific
name followed by "illustrations", for example [Streptopelia decaocto illustrations](https://commons.wikimedia.org/w/index.php?search=Streptopelia+decaocto+illustrations&title=Special%3AMediaSearch&type=image).

Choose public-domain or openly licensed artwork whose terms are compatible with
the style. Keep the artist or work name, licence, and link to the original image
for its manifest and `ATTRIBUTION.md` entries.

## Prepare the image

(WIP)

Krita is my preferred tool of choice here (its free and easy to use)

### Cut out the bird

Use the Polygonal Selection Tool with anti-aliasing enabled.

Select the bird or the excess. Invert the selection if necessary, then delete
the background.

### Add the halo

The ring of paper around the bird helps us blend it to the page. The frame retones it to the sheet's own colour and feathers its edge, so the join disappears instead of reading as a cut-out pasted on. It also allows for less precise cutouts, backgrounds between legs or behind feathers, and gives some natural spacing.

Use **Image > Flatten Image** first.

1. Set the foreground colour to `#F0ECE5`.
2. Use **Select > Select Opaque**.
3. Use **Select > Grow Selection...** with a radius of about 18 px, depending on the image size.
4. Use **Layer > New > Paint Layer**, then drag the layer below the bird.
5. Use **Edit > Fill with Foreground Color**.
6. Use **Select > Deselect**, then **Image > Flatten Image**.
7. Export as PNG and tick **Store alpha channel**.

## Add the bird to a style

Use the artwork tool to give a finished cut-out a BirdNET-compatible filename,
place it in a style, and record its artist/source and original plate:

```bash
uv run python tools/add_bird.py ~/Desktop/bird.png
```

The tool asks for anything not supplied as an input parameter. Species and existing
artist/source keys are searched interactively. It uses `fzf` if available. Attribution is required; the link to the original source is optional (but strongly recommended).

Export from your editor in whatever format suits you and the tool re-encodes the asset as WebP.
Transparency is kept, and the file becomes about a sixth the size of the same image as PNG (keep repo and container image smaller).

PNG are still supported. Drop one into your own `custom/` folder and the frame picks it up. WebP is only a rule for artwork commited to the repo.

It supports dry-running:

```bash
uv run python tools/add_bird.py ~/Desktop/bird.png \
  --preview /tmp/bird-preview.png \
  --dry-run
```

Run `uv run python tools/add_bird.py --help` for options such as `--style`,
`--species`, `--source`, and `--url`.

## Tips

- Hand-drawn birds on paper cut out best. Painted scenery doesn't, because the background bleeds into the feathers and there's no clean edge to follow.
- Commons often files a bird under an older name than BirdNET uses. If the scientific name finds nothing, search the English one.
- Leave anti-aliasing on. Soft edges survive, and they stop the bird looking cut out with scissors.
- No need to trim the empty space around the bird. The tool crops to the cut-out.
- Always look at `--preview` before you commit. It puts the bird on the frame's own paper with the frame's own halo, which is the only honest check of whether it blends.
- Nothing that separates the bird from the page: no drop shadows, no glows
- A second (or more) plate of the same bird is worth adding - the frame keeps one pick per bird per window, so variants show up over days rather than all at once. (e.g. variation for male/females, or different coats or scenery)
