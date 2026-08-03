# fugleramme
E-ink bird frame for Raspberry Pi - real-time bird detection by audio.

Built on top of [BirdNET-Go](https://github.com/tphakala/birdnet-go), which handles
the mic, the BirdNET classifier and the detection settings. Fugleramme reads
the detections and renders recently-seen birds on an [Inky-Impression](https://shop.pimoroni.com/products/inky-impression) e-ink panel, and also serves the same view as a web kiosk.

> [!TIP]
> The e-ink panel is not required, although its recommended for the inteded experience. Without one, Fugleramme runs web-only - show the
> kiosk on a display over HDMI, or open it from any device on the network.

Hardware, install and operations docs: **[arnegiacomo.dev/fugleramme](https://arnegiacomo.dev/fugleramme/)**

## Art

(WIP)

The birds are cut-outs from historic, public-domain natural-history drawings,
hand-curated for this project. Each detected species is matched to its
illustration, background-removed, and packed onto a textured paper page - larger
birds toward the centre, sized by real body mass. Species with no illustration
are currently left off, and an empty window shows a bare perch.

| No detections | A few visitors | A full garden |
| :---: | :---: | :---: |
| ![No birds detected](docs/samples/empty.png) | ![A few garden birds](docs/samples/few.png) | ![Many garden birds](docs/samples/many.png) |

## Run locally

```bash
uv sync                                       # set up venv
uv run python -m fugleramme.seed --count 40   # seed db (no BirdNET-Go in dev)
uv run fugleramme-dev                         # start service on :8080 with hot-reload
```

Open the kiosk (no SPI-panel needed):

```bash
open -na "Google Chrome" --args --kiosk --app=http://localhost:8080/
```

## Run on a Raspberry Pi

Clone the repo on the Pi and run the idempotent one-command bootstrap:

```bash
./setup.sh          # add -y to auto-accept dependency installs (uv, docker, etc...)
```

It installs any missing deps, brings up BirdNET-Go (container + mic), and enables
the frame as a systemd service that pushes to the Inky panel and serves the kiosk
on `:8080`. It also enables SPI and I2C, so the first run needs a **reboot**
before the panel will drive - if it stays blank after that, see
[Troubleshooting](docs/troubleshooting.md#panel-stays-blank).

From a blank SD card, start at the [install guide](docs/install.md).

## License

- Code: MIT - see [`LICENSE`](LICENSE).
- Bird images: each style folder carries its own terms and sources, and every
  file names the plate it was cut from in its PNG metadata. `classic` is
  CC BY-SA 4.0 - see
  [`assets/birds/classic/ATTRIBUTION.md`](assets/birds/classic/ATTRIBUTION.md).
- Label fonts (`assets/fonts/`): SIL OFL 1.1 - see
  [`assets/fonts/ATTRIBUTION.md`](assets/fonts/ATTRIBUTION.md).
- Bird sizes (`assets/bird_sizes.csv`): body mass from AVONET (Tobias et al.
  2022, Ecology Letters, [doi:10.1111/ele.13898](https://doi.org/10.1111/ele.13898)),
  CC BY 4.0.
