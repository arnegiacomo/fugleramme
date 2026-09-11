# Container

Fugleramme as a container image, for a homelab or any machine with docker.
Connect it to a BirdNET-Go you already run, or bring both up together, and see
the collage in a browser.

> [!NOTE]
> The container is web only. It can't run an e-ink panel over SPI yet, so on a
> Pi with a panel attached, use the [normal install](install.md).

## Both at once

```bash
mkdir fugleramme && cd fugleramme
curl -fsSL https://raw.githubusercontent.com/arnegiacomo/fugleramme/main/examples/docker-compose.yml -o docker-compose.yml
docker compose up -d
```

The collage is on `:8080` with settings on `:8080/admin`, and BirdNET-Go's own
dashboard on `:8090`. Configure your location and audio source next: [Configuring BirdNET-Go](birdnetgo-config.md).

> [!NOTE]
> The mic reaches the container through `/dev/snd` (only works on linux)

## Just the frame

```yaml
services:
  fugleramme:
    image: ghcr.io/arnegiacomo/fugleramme:latest
    environment:
      FUGLERAMME_DETECTOR_URL: http://birdnet.local:8080
      TZ: Europe/Oslo
    ports:
      - "8080:8080"
    volumes:
      - fugleramme:/data
    restart: unless-stopped

volumes:
  fugleramme:
```

`docker compose up -d`, then the kiosk is on `:8080` and the admin on
`:8080/admin`. `TZ` sets the frame's date on a plate, and defaults to UTC.

> [!NOTE]
> `127.0.0.1` inside a container is the container itself. Point it at your
> machine's name or network address (or BirdNET-Go's container name, if both
> are on the same Docker network). `network_mode: host` also works, and then the
> `ports` lines can go.

## Settings from environment variables

Every setting on the admin page can be seeded with `FUGLERAMME_<NAME>`:

```yaml
    environment:
      FUGLERAMME_DETECTOR_URL: http://birdnet.local:8080
      FUGLERAMME_DETECTOR_PASSWORD: my-secret-password
      FUGLERAMME_DETECTOR_USERNAME: birdnet-client   # only if you changed BirdNET-Go's client id
      FUGLERAMME_MODE: collage                       # collage | latest | arrival
      FUGLERAMME_WEB_RESOLUTION: 1080p               # 720p | 1080p | 1440p | 4K
      FUGLERAMME_ROTATION: 0                         # 0 | 90 | 180 | 270
      FUGLERAMME_LOOKBACK_HOURS: 24                  # 0.25 … 720, or 0 for all time
      FUGLERAMME_REFRESH_MINUTES: 0                  # 0 | 5 | 10 | 15 | 30 | 60
      FUGLERAMME_SPECIES_LIMIT: 40                   # 0 for no limit
      FUGLERAMME_RANKING: heard                      # heard | rarest | rarest_ever
      FUGLERAMME_STYLE: classic
      FUGLERAMME_SHOW_NAMES: "true"
      FUGLERAMME_PRIMARY_LANGUAGE: nb                # a BirdNET-Go locale, or sci
      FUGLERAMME_SECONDARY_LANGUAGE: ""              # empty for none
      FUGLERAMME_LABEL_FONT: gentium                 # gentium | garamond | cormorant | baskerville | playfair | alegreya | bitter
      FUGLERAMME_LABEL_SIZE: medium                  # small | medium | large | xlarge
```

A value the frame doesn't recognise falls back to the default (same as it would for a
hand-edited settings file).

> [!IMPORTANT]
> These are a **seed, not an override**. A variable only applies to a setting you
> haven't saved yet. Once you save it on the admin page, the variable will be ignored -
> otherwise your changes would be undone on the next `up -d`.

Use the seed values to bring a fresh frame up the way you want it, and the admin page for
everything afterwards. To start over, delete the volume (no detections will be lost - only your settings).

## The volume

`/data` holds the settings, the current artwork picks, the cached species names dictionaries and
the rendered page. A bind mount instead of a named volume has to be writable by
uid 1000:

```bash
mkdir -p ./data && sudo chown 1000:1000 ./data
```

## Updates

The System tab will still notify if there's a new update, but an image is replaced rather
than updated in place, so there is no Install button:

```bash
docker compose pull && docker compose up -d
```

The volume is untouched. The artwork is split across many layers, so an update
only pulls the part that changed.

If you want that automated, [Watchtower](https://containrrr.dev/watchtower/) can
do it on a schedule. Set it up yourself if you want it as the compose above
doesn't update on its own.

## Tags

| Tag | Moves |
| --- | --- |
| `latest` | every release |
| `0.20` | patches within a minor version |
| `0.20.1` | never |