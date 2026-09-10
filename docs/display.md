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

How far back the collage looks, from the last hour to all time. Default is
**Today (24 hours)**. Only the collage uses it.

**All time** never drops a species, so the page only grows.

### Species on the page

How many species the collage shows at once, and which it keeps when the window holds more than that. Default is **At most 40**. (Only the collage-mode uses this).

A busy installation can hear over thirty species in a day, and thirty birds on one sheet become very small. Set a limit and pick which to keep:

| Which ones to keep | Good for |
| --- | --- |
| The most heard | Most detections within a window |
| The rarest in the window | Least detections within a window |
| The rarest all time | Least detections ever recorded |

**Show all** means **all of them**. A long lookback at a busy station is yours to bound - past forty or so
the birds get small and the labels crowd (but at least you get a cool mosaic!).

**Only birds**, whatever the setting. BirdNET-Go's labels also cover frogs,
crickets and squirrels, and a bat model adds bats - the frame leaves all of it
out. They are still detected, and still on its own dashboard at `:8090`. The
log names each one the first time it is heard:

```bash
journalctl -u fugleramme-frame | grep "Not a bird"
```

### Species names

**Show species names** turns the labels on and off, same as **B** on the panel.

Names come from BirdNET-Go, one dictionary per language. Pick a **primary
language** and optionally a second, which stacks underneath in parentheses. Only
downloaded dictionaries are offered - on a fresh install that may be the
scientific name alone.

**Typeface** and **size** apply to every label.
