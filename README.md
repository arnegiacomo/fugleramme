# fugleramme
E-ink bird frame for Raspberry Pi - real-time bird detection by audio.

Built on top of [BirdNET-Go](https://github.com/tphakala/birdnet-go), which runs
the mic and the BirdNET classifier and owns all detection config. Fugleramme reads
its detections and renders the recently-seen birds as a collage on an [Inky-Impression](https://shop.pimoroni.com/products/inky-impression) e-ink panel, and serves the same view as a web kiosk.

Hardware, install and operations docs: **[arnegiacomo.dev/fugleramme](https://arnegiacomo.dev/fugleramme/)**

## Art

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
uv run fugleramme-frame                       # start service on :8080
uv run fugleramme-dev                         # same as above with hot-reload
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
on `:8080`. From a blank SD card, start at the [install guide](docs/install.md).

Want to update? Just pull and run ./setup.sh again

### The panel

Setup enables SPI and I2C and adds the overlays the `inky` driver needs, so the
first run needs a **reboot** before the panel will drive. After that:

```bash
journalctl -u fugleramme-frame -f    # "Inky panel initialised: inky.inky_el133uf1 1600x1200"
```

The panel's size comes from the panel itself - the admin resolution setting is
the web kiosk's only. Rotation (0/90/180/270) applies to both. If it still reads
"not detected", check `ls /dev/spidev*` and that your login has picked up the
`spi`/`i2c`/`gpio` groups (`id`); the frame serves the kiosk either way.

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
