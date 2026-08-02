# Hardware

The build this project runs on.

## Parts

| Part | What I recommend |
| --- | --- |
| Board | Raspberry Pi 5, 2 GB |
| Storage | microSD card (32 GB or more) |
| Cooling | Raspberry Pi Active Cooler |
| Panel | [Inky Impression 13.3"](https://shop.pimoroni.com/products/inky-impression) (Spectra 6, 1600x1200) |
| Mic | Boya BY-M3, plus a USB-C to USB-A adapter |
| Power | Official Raspberry Pi 5 USB-C power supply |

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

- **Pi 4** should work but is untested.
- **Other USB mics** are fine, as long as they go in a USB-A port - the USB-C
  port is the power input. `setup.sh` picks the capture device from `arecord -l`,
  so anything ALSA sees will do; re-run it after swapping mics.
- **NVMe instead of microSD** works and spares the card BirdNET-Go's constant
  writes, but we don't recommend it here: the HAT adds cost, height and heat for
  a workload that is mostly idle - and at the time of writing NVMe drives are
  crazy expensive.
- **Other Inky displays** are supported but not recommended - you lose
  resolution and size. The panel is optional entirely: the frame serves the same
  view as a web kiosk, so you can run it on an HDMI display or fully headless.

## Enclosure/Frame

To be written.
