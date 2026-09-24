# FAQ

The questions that have been asked the most. If what you're wondering isn't here, see [the end of this page](#i-have-a-question-a-bug-or-something-to-contribute).

## Do I need a Raspberry Pi?

Only for the panel. It plugs straight onto a Pi's pins and uses Pimoroni's driver.

Everything else runs wherever Python or Docker does - a NAS, a homelab, an old laptop. See [Container](container.md).

## Do I need the e-ink panel?

No. It is what makes this look like a picture frame instead of a screen, but fugleramme serves the same page over HTTP either way, in the shape of whatever shows it - a TV, an HDMI display straight from the Pi, any device on the network, or even your desktop wallpaper/screensaver. See [Screens](screens.md).

## Which Raspberry Pi?

A Pi 5 for the full build, because BirdNET-Go classifies around the clock. For a frame that only draws, any 40-pin Pi does - people are running a Pi 4 and a Pi Zero 2 W, and render time varies by model. See [Frame only](hardware.md#frame-only-external-or-existing-birdnet-go).

## Can I use a smaller or a different Inky?

Yes. Other Inky Impressions work and fugleramme reads the resolution automatically. You lose size and sharpness, and below 13.3" the birds get small fast - so cap how many birds land on the page, under [Species on the page](display.md#species-on-the-page-collage-only). See [Alternatives](hardware.md#alternatives).

## What does it cost?

The panel is most of it. Here are some rough ranges (prices fluctuate a lot at the time of writing):

| Build | Roughly |
| --- | --- |
| **Full 13.3"** - Pi 5, cooler, PSU, card, Inky Impression 13.3", Clippy EM272Z1 + sound card, frame | €380-450 / $420-500 |
| **Full build, cheaper** - the same on a Pi 4, with an Inky Impression 7.3" and a USB lavalier mic | €170-220 / $190-240 |
| **Frame only**, reading a BirdNET-Go you already run - Pi Zero 2 W, PSU, card, panel, frame | €110-270 / $120-300, depending on the panel |

[Hardware](hardware.md#full-build-with-birdnet-go) has what I actually use, recommend and why.

## Will it work where I live?

BirdNET works basically everywhere. The artwork is the limiting factor. Northern/Central Europe is covered the best right now, but wider support is in the works. See [Species coverage](species.md).

If your local regulars never show up, open a [Missing bird](https://github.com/arnegiacomo/fugleramme/issues/new/choose) issue - that is how the list grows. Better still, [cut one yourself](adding-artwork.md) and open a PR.

## Why isn't a bird I heard on the page?

Three possibilities, in the order worth checking:

- **There is no artwork for it.** The admin page greys the species out with "no art", and the log names them. See [Adding artwork](adding-artwork.md).

  ```bash
  journalctl -u fugleramme-frame | grep "No artwork"
  ```

- **It isn't a bird.** See [What about bats, frogs and squirrels?](#what-about-bats-frogs-and-squirrels)

  ```bash
  journalctl -u fugleramme-frame | grep "Not a bird"
  ```

- **BirdNET-Go never recorded it.** Open its dashboard on `:8090`. If it isn't there either, it's a detection question rather than a frame one.

## I'm getting birds that can't possibly be here

That is BirdNET-Go's side, and mostly comes down to your location, gear and its confidence thresholds - see [Avoiding false detections](birdnetgo-config.md#avoiding-false-detections). Marking a detection as a false positive in BirdNET-Go also removes it from fugleramme.

## What about bats, frogs and squirrels?

Fugleramme currently only draws birds - it's a bird frame, and there isn't the historic plate coverage to do the rest justice. See [Species on the page](display.md#species-on-the-page-collage-only).

Let me know if you have some good ideas for how to get other animals up too.

## Which microphone?

Any USB mic works, but it's worth spending a little extra on, and it needs a windshield and some weather protection - see [Microphones](hardware.md#microphones).

## Where does the artwork come from?

Public-domain natural-history plates, mostly from Wikimedia Commons and rawpixel. Every cut-out records the plate it came from in its style's [manifest.json](https://github.com/arnegiacomo/fugleramme/blob/main/assets/artwork/classic/manifest.json), and the works and their terms are listed in [ATTRIBUTION.md](https://github.com/arnegiacomo/fugleramme/blob/main/assets/artwork/classic/ATTRIBUTION.md).

## Is any of the included art AI-generated?

No. Every bird is cut from a plate drawn by a real person.

AI tools for cleaning up or editing a scan are fine. The art underneath has to be human-made and properly attributed.

## Can I use my own images?

Yes. Drop them in `assets/artwork/custom/` on your own frame and they are picked up, named for the scientific name BirdNET-Go uses. Nothing is checked there - it's your frame, put what you like on it.

Artwork meant for the repo has a higher bar - see [Artwork](https://github.com/arnegiacomo/fugleramme/blob/main/CONTRIBUTING.md#artwork).

## Can I point it at a BirdNET-Go I already run?

Yes. It can be on the same machine or anywhere on your network, so the frame can hang in a nice room while the mic sits wherever the birds are. Set it during the [install](install.md#where-birdnet-go-lives), later in the [settings](operations.md#pointing-the-frame-at-a-different-birdnet-go), or with an environment variable in the [container](container.md#just-the-frame).

Already using `:8080` for BirdNET-Go? The installer lets you put the frame on [another port](install.md#ports).

## Where are the settings?

On `http://<host>.local:8080/admin`. The root path is the kiosk, which is deliberately just the picture.

## What's planned?

The [open issues](https://github.com/arnegiacomo/fugleramme/issues) are the roadmap. Anything still half-formed is in [Discussions](https://github.com/arnegiacomo/fugleramme/discussions).

## I have a question, a bug, or something to contribute

- **Something is broken** - see [Troubleshooting](troubleshooting.md), then a [bug report](https://github.com/arnegiacomo/fugleramme/issues/new/choose)
- **A question, an idea, or a frame you have built** - [Discussions](https://github.com/arnegiacomo/fugleramme/discussions)
- **A fix, a doc change, or a bird you have cut** - open a PR, no issue needed

This is a hobby project maintained by one person, so replies may take a few days. [CONTRIBUTING.md](https://github.com/arnegiacomo/fugleramme/blob/main/CONTRIBUTING.md) has the details.
