# Fugleramme

E-ink bird frame for Raspberry Pi - real-time bird detection by audio, fully local AI, rendered as real, hand-cut 1800s bird illustrations.

A mic feeds [BirdNET-Go](https://github.com/tphakala/birdnet-go), which runs
the BirdNET classifier and owns all detection config. Fugleramme reads its
detections and renders the recently-seen birds as a collage on an
[Inky Impression](https://shop.pimoroni.com/products/inky-impression) e-ink
panel, and serves the same view as a web kiosk.

Fugleramme can install BirdNET-Go for you, or read from one you already run - on the
same machine or elsewhere.

| No detections | A few visitors | A full garden |
| :---: | :---: | :---: |
| ![No birds detected](assets/empty.png) | ![A few garden birds](assets/few.png) | ![Many garden birds](assets/many.png) |

> [!TIP]
> Live on **[fugleramme.arnegiacomo.dev](https://fugleramme.arnegiacomo.dev)**
> running from my kitchen window and displaying the actual birds currently
> heard in my garden (Bergen, Norway).

The birds are cut-outs from historic, public-domain natural-history drawings,
hand-curated for this project - over 800 of them across more than 400 species.
Each detected species is matched to its illustration and packed onto a textured paper page - larger birds toward the centre, sized by real body mass.

For more display options see [Display](display.md).

> [!NOTE]
> Still in early development: expect the odd bug and a few unpolished edges, with
> plenty more features to come. Bug reports and suggestions are very welcome on
> [GitHub](https://github.com/arnegiacomo/fugleramme/issues).

## Docs

- **[Hardware](hardware.md)** - the parts list with alternatives
- **[Install](install.md)** - from a blank SD card to a running frame
- **[Configuring BirdNET-Go](birdnetgo-config.md)** - the mic, your location, and
  avoiding incorrect detections
- **[Display](display.md)** - modes, settings and names
- **[Operations](operations.md)** - buttons, services, logs and updates
- **[Container](container.md)** - running Fugleramme with Docker
- **[Adding artwork](adding-artwork.md)** - cutting a bird the frame can't draw yet
- **[Troubleshooting](troubleshooting.md)** - symptom to cause

> [!NOTE]
> These docs are written from macOS. Everything on the Pi itself is the same
> whatever you drive it from - it's the host-side steps, like Internet Sharing
> over the USB cable, that differ. If you set yours up from Linux or Windows, a
> PR extending them is very welcome.

## Prebuilt frames

I've built a few of these. If you'd like one rather than building it yourself,
please [get in touch](https://arnegiacomo.dev/).

---

Source: [github.com/arnegiacomo/fugleramme](https://github.com/arnegiacomo/fugleramme)
