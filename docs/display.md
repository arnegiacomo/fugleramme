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

### Species names

**Show species names** turns the labels on and off, same as **B** on the panel.

Names come from BirdNET-Go, one dictionary per language. Pick a **primary
language** and optionally a second, which stacks underneath in parentheses. Only
downloaded dictionaries are offered - on a fresh install that may be the
scientific name alone.

**Typeface** and **size** apply to every label.
