# Hardware

There are two ways of assembling a fugleramme frame. Other hardware variants and
combinations might work, but haven't been verified. If you come up with
something cool, let me know!

## Full build (with BirdNET-Go)

The full build, from hearing the birds in your own garden to drawing them on the display. If you already run
BirdNET-Go somewhere, skip to [Frame only](#frame-only-external-or-existing-birdnet-go) below.

| Part | What I recommend |
| --- | --- |
| Board | [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/), 2 GB |
| Storage | [microSD card](https://www.raspberrypi.com/products/sd-cards/) (32 GB or more) |
| Cooling | [Raspberry Pi Active Cooler](https://www.raspberrypi.com/products/active-cooler/) |
| Panel | [Inky Impression 13.3"](https://shop.pimoroni.com/products/inky-impression) (Spectra 6, 1600x1200) |
| Mic | [Clippy EM272Z1 mono](https://micbooster.com/product/clippy-em272-microphone/), the 3.5 mm one (in the EU it's easier from [Veldshop](https://www.veldshop.nl/en/clippy-em272z1-mono-microphone.html)) |
| Sound card | [UGREEN USB audio adapter](https://www.amazon.co.uk/dp/B01N905VOY), model US205 (article number 30724) |
| Power | [Official Raspberry Pi 27W USB-C power supply](https://www.raspberrypi.com/products/27w-power-supply/) |
| Frame | [IKEA RÖDALM 21x30](https://www.ikea.com/gb/en/p/roedalm-frame-oak-effect-50566393/) (A4) |

### Why these

- **2 GB RAM** is enough to run everything. BirdNET-Go does the classifying and the frame only
  renders a collage every few minutes, and at the time of writing Pis with more
  RAM are very expensive.
- **32 GB or more storage**, to hold the sound clips and the artwork.
- **The active cooler is not optional.** BirdNET-Go runs the classifier
  continuously, and the Pi 5 runs surprisingly hot.
- **The official power supply.** Anything weaker and the Pi throttles or browns
  out under load.
- **The mic matters more than the Pi.** Detection is BirdNET-Go's job, and how
  well it does comes down mostly to the mic, how you configure it and where you
  put it. The EM272Z1 is the gold standard for the birding and field-recording
  crowd - see [Microphones](#microphones) below.
- **The sound card, because the Clippy is analogue.** The Pi has no audio input,
  and the mic needs plug-in power on a 3.5 mm jack. The UGREEN supplies it and
  needs no drivers.

BirdNET-Go has [its own hardware page](https://github.com/tphakala/birdnet-go/wiki/hardware),
which goes deeper on the audio side than I do here (more sound cards, a DIY
capsule, and what you need if you want to hear bats).

## Frame only (external or existing BirdNET-Go)

No mic, no sound card, no BirdNET-Go on the Pi. It reads from one
you already run elsewhere on the network, so the frame can hang anywhere.

| Part | What works |
| --- | --- |
| Board | [Raspberry Pi 5](https://www.raspberrypi.com/products/raspberry-pi-5/) (1 GB is plenty), [Pi 4](https://www.raspberrypi.com/products/raspberry-pi-4-model-b/), or a [Pi Zero 2 W](https://www.raspberrypi.com/products/raspberry-pi-zero-2-w/) with the 40-pin header installed |
| Storage | [microSD card](https://www.raspberrypi.com/products/sd-cards/), 16 GB or more |
| Panel | [Inky Impression 13.3"](https://shop.pimoroni.com/products/inky-impression) (Spectra 6, 1600x1200) |
| Power | The official supply for whichever board - [27 W USB-C](https://www.raspberrypi.com/products/27w-power-supply/) for a Pi 5, [5 V micro-USB](https://www.raspberrypi.com/products/micro-usb-power-supply/) for a Zero |
| Frame | [IKEA RÖDALM 21x30](https://www.ikea.com/gb/en/p/roedalm-frame-oak-effect-50566393/) (A4) |

- **Any 40-pin Pi drives the panel** - thanks to Pimoroni's
  [`inky`](https://github.com/pimoroni/inky) library. A Zero 2 W renders more
  slowly, which you might not notice on a panel that takes half a minute anyway.
  [Alternatives](#alternatives) says what's verified.
- **The cooler is optional.** Nothing is classifying around the clock here, so
  the Pi pretty much idles between renders.
- **Less storage.** No sound clips, no detection database.
- **You do need a BirdNET-Go it can reach.** Give its address during the install
  (see [Where BirdNET-Go "lives"](install.md#where-birdnet-go-lives)), or set it
  later on the admin page.

## Microphones

Any USB mic works - `run.sh` picks the capture device from `arecord -l`, and you
select it in [BirdNET-Go's own settings](birdnetgo-config.md#setting-up-the-microphone-required).
Re-run `./run.sh` after swapping mics. It's still the one part worth spending
money on:

| Mic | Connection | Notes |
| --- | --- | --- |
| [Clippy EM272Z1 mono](https://micbooster.com/product/clippy-em272-microphone/) | 3.5 mm, needs the sound card | What I recommend. Low noise, high sensitivity, 1 m cable. |
| Boya BY-M3 | USB-C, so a USB-C to USB-A adapter | What I originally built with (no longer made). |
| [Neewer USB lapel mic](https://www.amazon.co.uk/dp/B0DP48MZ4Q) | USB-A | Pimoroni's recommended stand-in for the BY-M3. Untested. |
| Boya BY-M1 | 3.5 mm TRRS, needs the sound card | Cheap, 6 m cable, LR44 battery in camera mode (untested). |
| [Clippy Ultra XLR](https://www.veldshop.nl/en/clippy-ultra-xlr-microphone-Single.html) | XLR, needs an interface with phantom power | Up to 110 kHz, so bats too (reported a little behind the EM272Z1 on birds). |
| [AudioMoth USB microphone](https://groupgets.com/products/audiomoth-usb-microphone) | USB-A | Bats too. Pricey, but people like it. |

Whatever you pick, put a windshield (and environmental protection) on it if it lives outdoors (wind straight on
the capsule drowns out everything else).

## Alternatives

- **Other boards.** A **Pi 4** and a **Pi Zero 2 W** both work - people are running them, the Zero just renders more slowly. A **Pi 5 with 1 GB** should be plenty for a frame that isn't also classifying. (None of these are officially supported
  yet, only because I don't have units to verify on).
- **NVMe instead of microSD** spares the card BirdNET-Go's constant writes, but the HAT/Base adds cost, height and heat for a mostly idle workload - and the drives are crazy expensive right now.
- **Other Inky displays** work, you just lose resolution and size. Alternatively skip the panel: the frame serves the same view as a web kiosk, over HDMI or headless - see [Showing the frame without the e-ink panel](operations.md#showing-the-frame-without-the-e-ink-panel).

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

### Cutting the passepartout (mostly relevant for full build)

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
