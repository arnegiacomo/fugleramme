# Fugleramme

E-ink bird frame for Raspberry Pi - real-time bird detection by audio.

A USB mic feeds [BirdNET-Go](https://github.com/tphakala/birdnet-go), which runs
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
hand-curated for this project. Each detected species is matched to its
illustration and packed onto a textured paper page - larger birds toward the
centre, sized by real body mass.

For more display options see [Display](display.md).

## Docs

- **[Hardware](hardware.md)** - the parts, and what's swappable
- **[Install](install.md)** - from a blank SD card to a running frame
- **[Display](display.md)** - modes, settings and names
- **[Operations](operations.md)** - buttons, services, logs and updates
- **[Configuring BirdNET-Go](birdnetgo-config.md)** - avoiding incorrect detections
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
