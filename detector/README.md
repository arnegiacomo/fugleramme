# Detector (issue #3)

The detector half of the appliance: a USB mic feeds **BirdNET-Go**, which
classifies bird sounds and records them. The frame reads its API; the halves
meet at `/api/v2` and nowhere else (issue #29).

```
USB mic --> BirdNET-Go (container) --> :8090 /api/v2 --> frame (#1)
```

This container is the default, not a requirement. Because the interface is the
API, a frame can equally read a BirdNET-Go you installed yourself on the same
machine, or one on another machine entirely - the same code path, a different
`detector_url`. The install asks which.

## What the frame asks for

- `/analytics/species/summary` - per-species counts with first and last heard,
  false positives already excluded. Drives the collage and the life list.
- `/detections/recent` - the newest rows, false positives included and flagged,
  so the frame drops them itself.
- `/settings/locales` and `/species/dictionary/<code>` - the language list and
  `{scientific name: common name}`. Only some locales have a dictionary, so the
  admin offers the ones a `HEAD` confirms. Dictionaries cache under
  `data/names/` and revalidate by ETag; with nothing answering and nothing
  cached, names fall back to the scientific name.

`Security.PrivateMode` gates the whole API, so an instance with it on needs a
username and password in the admin's Detector section.

## The database is BirdNET-Go's alone

`detector/data` is a bind mount, not a named volume, so the file stays on the
host where it can be backed up and where the container's entrypoint can chown it
to the host user. The frame never opens it. The one thing that touches it is
`updates._backup_db`, which copies it to `birdnet.db.bak` before a release moves
the image pin - upstream has shipped migrations that lost the database, and the
detections are the one thing here that cannot be fetched again.

## Layout

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | BirdNET-Go container: mic via `/dev/snd`, data bind-mounted from `./data` (persistent), web UI on `${BIRDNET_PORT:-8090}` |
| `config/config.yaml.template` | Tracked template; `run.sh` copies it to a gitignored per-Pi `config.yaml`. Bergen lat/lon + range/week filter, `interval` debounce, analysis defaults (#15), clips on, SQLite at `/data/birdnet.db`, log levels pinned to `info` |
| `preflight.sh` | Checks that an ALSA capture device exists; `install.sh` can confirm a bypass |

## Deploy

`run.sh` brings the detector up as part of the appliance bootstrap - see the
[install guide](../docs/install.md). When running it directly, a missing capture
device is fatal unless `--skip-mic-check` is passed. Follow the logs with:

```bash
docker logs -f birdnet-go                     # detector
journalctl -u fugleramme-frame -f            # frame
```

## Deployment notes

- **Image pin:** upstream tags releases by date (`20260823`; the `nightly-`
  prefix is gone since mid-2026). A release carries the pin to every frame -
  `updates.apply` runs `compose up -d` after the checkout - so test a bump on the
  Pi before tagging one.
- **Licence:** BirdNET-Go and the BirdNET model are CC BY-NC-SA 4.0. Nothing from
  it is vendored - the compose pulls a prebuilt image and the frame only calls
  its API - which is what keeps this repo MIT. Don't fork it into the tree.
- **Mic device:** `run.sh` writes the first card from `arecord -l` into
  `detector/.env` as `ALSA_CARD` (by card name, so it survives reboots/replugs),
  making the USB mic ALSA's default - HDMI takes cards 0/1 and has no capture
  stream. Which mic BirdNET-Go actually opens is picked in its own UI on `:8090`.
- **Container user:** BirdNET-Go's entrypoint chowns `/config` and `/data`, so
  `run.sh` runs it as the host user (`BIRDNET_UID`/`BIRDNET_GID` = `id -u`/`id -g`)
  to avoid leaving the bind-mounted `config`/`data` files owned by a foreign uid.
- **Audio group:** the container needs the host `audio` group to read `/dev/snd`.
  If `group_add: audio` fails, substitute the numeric GID from
  `getent group audio`.
- **Location:** lat/lon is hardcoded to Bergen here; the admin panel (#2) will
  own it later.
- **Logs are in RAM (`tmpfs`), and go on restart.** BirdNET-Go defaults all 23
  modules to `debug`, rotating at 100MB and keeping 10 - a ~26GB ceiling that
  kills an SD card. The template pins them to `info`; the compose keeps
  `/data/logs` and the HLS segments off the disk.
