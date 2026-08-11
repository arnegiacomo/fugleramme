# Hardware

The recommended build for this project - other hardware variants and
combinations might work, but haven't been verified. If you come up with
something cool, let me know!

## Parts

| Part | What I recommend |
| --- | --- |
| Board | [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/), 2 GB |
| Storage | [microSD card](https://www.raspberrypi.com/products/sd-cards/) (32 GB or more) |
| Cooling | [Raspberry Pi Active Cooler](https://www.raspberrypi.com/products/active-cooler/) |
| Panel | [Inky Impression 13.3"](https://shop.pimoroni.com/products/inky-impression) (Spectra 6, 1600x1200) |
| Mic | Boya BY-M3\*, plus a USB-C to USB-A adapter |
| Power | [Official Raspberry Pi 27W USB-C power supply](https://www.raspberrypi.com/products/27w-power-supply/) |
| Frame | [IKEA RÖDALM 21x30](https://www.ikea.com/gb/en/p/roedalm-frame-oak-effect-50566393/) (A4) |

\* No longer an active product, I'm looking for
an alternative to recommend - suggestions welcome!

### Why these

- **2 GB RAM** is enough. BirdNET-Go does the classifying and the frame only
  renders a collage every few minutes, and at the time of writing Pis with more
  RAM are very expensive.
- **32 GB or more storage**, to hold the sound clips and the artwork.
- **The active cooler is not optional.** BirdNET-Go runs the classifier
  continuously, and the Pi 5 runs surprisingly hot.
- **The official power supply.** Anything weaker and the Pi throttles or browns
  out under load.

## Alternatives

- **Pi 4** should work but is untested (will probably be a little slower - unsure about cooling)
- **Other USB mics** are fine, as long as they go in a USB-A port - the USB-C
  port is the power input. `run.sh` picks the capture device from `arecord -l`,
  so anything ALSA sees will do; re-run it after swapping mics.
- **NVMe instead of microSD** works and spares the card BirdNET-Go's constant
  writes, but we don't recommend it here: the HAT adds cost, height and heat for
  a workload that is mostly idle - and at the time of writing NVMe drives are
  crazy expensive.
- **Other Inky displays** are supported but not recommended - you lose
  resolution and size. The panel is optional entirely: the frame serves the same
  view as a web kiosk, so you can run it on an HDMI display or fully headless.

## Enclosure/Frame

The panel board is exactly A4 - 297 x 210 mm - so it fits any A4 picture frame.

I used the IKEA
[RÖDALM 21x30](https://www.ikea.com/gb/en/p/roedalm-frame-oak-effect-50566393/).
It sits pretty snug, and at 3 cm it is barely deep enough for the Pi to sit
inside without touching the wall.

> [!TIP]
> This frame is cheap, so it lets you mess up a few times without it costing
> your right kidney.

Front to back:

```
front                                                          back
  |
  +-- plastic front sheet (optional - adds glare, flattens the mat)
  +-- passepartout, cut down to fit
  +-- e-ink panel, with the Pi mounted to it on the included screws
  +-- the frame's own plastic spacer, tightened against the metal fasteners
  +-- open cavity (let the Pi breathe)
  x   no backing board
```

### Cutting the passepartout

The included mat is cut for a much smaller picture, so cut your own from it with
a sharp craft knife and a steel ruler: **20 mm along the short sides, 15 mm
along the long sides**. That leaves a border wide enough to hide the panel's
bezel and the edge of the board, without intruding too much on the image.

> [!TIP]
> Cut against the steel ruler in several light passes rather than one hard one -
> and buy a spare mat or two or three (recommended from experience).

### Airflow

Leave the backing board out, or cut a big hole in it.

> [!WARNING]
> The Pi and the active cooler sit in the cavity behind the panel, and the
> constant BirdNET inference gets them quite hot. Don't close the back up.

Rubber feet in the back corners give the frame some clearance from whatever it
rests against.

> [!NOTE]
> Hanging it is still an open problem for me - whatever you come up with has to
> hold it off the wall, not flat against it.
