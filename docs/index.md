# Fugleramme

Bird frame for Raspberry Pi or your homelab - real-time bird detection by audio, fully local AI, rendered as real, hand-cut 1800s bird illustrations. On an e-ink panel, a TV, or any screen.

A mic feeds [BirdNET-Go](https://github.com/tphakala/birdnet-go), which runs
the BirdNET classifier and owns all detection config. Fugleramme reads its
detections and renders the recently-seen birds as a collage on an
[Inky Impression](https://shop.pimoroni.com/discount/ARNE?redirect=/products/inky-impression) e-ink
panel, or on any screen.

Fugleramme can install BirdNET-Go for you, or read from one you already run - on the
same machine or elsewhere. No mic? It can use a public
[BirdWeather station](operations.md#using-birdweather-instead-of-birdnet-go) instead.

| No detections | A few visitors | A full garden |
| :---: | :---: | :---: |
| ![No birds detected](assets/empty.png) | ![A few garden birds](assets/few.png) | ![Many garden birds](assets/many.png) |

> [!TIP]
> Live demo: **[fugleramme.arnegiacomo.dev](https://fugleramme.arnegiacomo.dev)**
> shows the birds heard in my garden in Bergen, Norway, right now. More frames
> around the world in the [Showcase](showcase.md).

The birds are cut-outs from historic, public-domain natural-history drawings,
hand-curated for this project - nearly 1200 of them across over 650 species.
Each detected species is matched to its illustration and packed onto a textured paper page - larger birds toward the centre, sized by real body mass.

For more display options see [Display](display.md) and [Frame](frame.md), and for TVs, HDMI and desktops [Screens](screens.md).

Bug reports and suggestions are very welcome on
[GitHub](https://github.com/arnegiacomo/fugleramme/issues).

## Docs

- **[Showcase](showcase.md)** - public frames people are running
- **[FAQ](faq.md)** - Frequently asked questions
- **[Hardware](hardware.md)** - the parts list with alternatives
- **[Mounting](mounting.md)** - mounting the panel and the Pi in an IKEA frame
- **[Install](install.md)** - from a blank SD card to a running frame
- **[Wi-Fi](wifi.md)** - connecting the frame to Wi-Fi
- **[Configuring BirdNET-Go](birdnetgo-config.md)** - the mic, your location, and
  avoiding incorrect detections
- **[Display](display.md)** - modes, settings and names
- **[Frame](frame.md)** - panel refresh, web resolution and margin
- **[Languages](languages.md)** - language support
- **[Screens](screens.md)** - a browser, an HDMI screen, a TV or your desktop
- **[Operations](operations.md)** - buttons, updates, ports and authentication
- **[Container](container.md)** - running Fugleramme with Docker
- **[Species coverage](species.md)** - searchable list of currently supported species
- **[Adding artwork](adding-artwork.md)** - cutting a bird the frame can't draw yet
- **[Troubleshooting](troubleshooting.md)** - symptom to cause

> [!NOTE]
> These docs are written from macOS. Everything on the Pi itself is the same
> whatever you drive it from - it's the host-side steps, like Internet Sharing
> over the USB cable, that differ. If you set yours up from Linux or Windows, a
> PR extending them is very welcome.

## Contact

Questions and ideas about the project belong in
[Discussions](https://github.com/arnegiacomo/fugleramme/discussions). For anything
else, you can reach me through [arnegiacomo.dev](https://arnegiacomo.dev/). I've built
a few of these frames, but I currently don't have the capacity to build them for others.

---

Source: [github.com/arnegiacomo/fugleramme](https://github.com/arnegiacomo/fugleramme)
