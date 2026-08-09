# Fugleramme

E-ink bird frame for Raspberry Pi - real-time bird detection by audio.

A USB mic feeds [BirdNET-Go](https://github.com/tphakala/birdnet-go), which runs
the BirdNET classifier and owns all detection config. Fugleramme reads its
detections and renders the recently-seen birds as a collage on an
[Inky Impression](https://shop.pimoroni.com/products/inky-impression) e-ink
panel, and serves the same view as a web kiosk.

| No detections | A few visitors | A full garden |
| :---: | :---: | :---: |
| ![No birds detected](samples/empty.png) | ![A few garden birds](samples/few.png) | ![Many garden birds](samples/many.png) |

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
- **[Troubleshooting](troubleshooting.md)** - symptom to cause

> [!NOTE]
> These docs are written from macOS. Everything on the Pi itself is the same
> whatever you drive it from - it's the host-side steps, like Internet Sharing
> over the USB cable, that differ. If you set yours up from Linux or Windows, a
> PR extending them is very welcome.

Source: [github.com/arnegiacomo/fugleramme](https://github.com/arnegiacomo/fugleramme)
