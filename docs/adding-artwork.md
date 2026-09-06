# Adding artwork

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

It supports dry-running:

```bash
uv run python tools/add_bird.py ~/Desktop/bird.png \
  --preview /tmp/bird-preview.png \
  --dry-run
```

Run `uv run python tools/add_bird.py --help` for options such as `--style`,
`--species`, `--source`, and `--url`.
