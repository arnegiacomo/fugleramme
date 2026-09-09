# Display

What the frame shows, and how to change it. Open the admin page at
`http://<host>.local:8080/admin` and use the **Display** tab.

## Modes

| Mode | What it shows |
| --- | --- |
| Collage (default) | Every bird heard in the lookback window, packed nicely together |
| Latest bird | The previous bird heard |
| Newest arrival | The most recent new bird heard |

Press **A** on the panel to step through the modes, or pick one in the admin page.

| Collage | Latest bird | Newest arrival |
| :---: | :---: | :---: |
| ![Collage of the birds heard recently](assets/mode-collage.jpg) | ![A European Robin, the last bird heard](assets/mode-latest.jpg) | ![A Eurasian Wigeon, the most recent new arrival](assets/mode-newest.jpg) |

**Newest arrival** stays put until something new is heard, so it can
sit on the same bird for weeks, but will update whenever a new species is observed.

**Latest bird** only changes when a different species is heard. The same bird
calling again all afternoon leaves the page alone. (Like "Newest arrival" but with repeats.)

Heard nothing at all in the lookback window? The page draws a bare perch.

![An empty page showing a bare perch](assets/frame-empty.jpg)

## Settings

### Lookback window

How far back the collage looks, from the last 6 hours to all time. Default is
**Today (24 hours)**. Only the collage uses it.

**All time** never drops a species, so the page only grows.

### Species on the page

How many species the collage shows, and which ones it keeps when the window
holds more than that. Default is **No limit**. Only the collage uses it.

A busy garden can hear thirty species in a day, and thirty birds on one sheet
are thirty *small* birds. Set a limit and pick which end to keep:

| Which ones to keep | Good for |
| --- | --- |
| The most heard | The birds that really live around you |
| The rarest | The one-off visitors, where the surprises are |

**The rarest** is worth a try if your list is the same residents every day. A
hoopoe that passed through once is easy to miss among thirty birds and hard to
miss among eight.

The frame draws at most 40 species whatever you pick, so **No limit** means
"everything the window heard, up to 40" - the 40 most heard, if it comes to
that.

### Bird size

What decides how big each bird is drawn - and with it how central, since the
bigger birds are laid down first, in the middle. Only the collage uses it.

| Decided by | What you get |
| --- | --- |
| Real body size (default) | A swan is drawn bigger than a wren, from its real body mass |
| Body size, and how often heard | The same, but the birds you hear most grow and move to the middle |

The second is for when the page doesn't look like what you actually hear: a
sparrow heard three hundred times a day drawn small, off in a corner, next to a
heron that passed over once. Body size still has its say - the two pull about
equally hard, so a swan does not shrink away for being quiet.

**Redraw the panel for a size change** is there on the e-ink panel's behalf, so
it is greyed out on a frame that has no panel. A refresh takes 20-30 seconds and
you notice it happening, so by default the frame holds a size change back and
lets it ride along with the next page that has a new bird on it. Pick a wait
instead if you would rather see it sooner. The web view never waits either way.

### Species names

**Show species names** turns the labels on and off, same as **B** on the panel.

Names come from BirdNET-Go, one dictionary per language. Pick a **primary
language** and optionally a second, which stacks underneath in parentheses. Only
downloaded dictionaries are offered - on a fresh install that may be the
scientific name alone.

**Typeface** and **size** apply to every label.
