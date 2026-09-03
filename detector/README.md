# Detector (issue #3)

The detector half of the appliance: a USB mic feeds **BirdNET-Go**, which
classifies bird sounds and logs them to its own SQLite. The frame reads that DB
directly (issue #7); the halves meet at the DB file, plus BirdNET-Go's API for
species names.

```
USB mic --> BirdNET-Go (container) --> birdnet.db (disk/NVMe, bind mount) --> frame (#1, read-only)
                                   --> :8090 /api/v2 (species names) ----------^
```

## The frame reads BirdNET-Go's DB directly

BirdNET-Go's schema is GORM-migrated and normalized: the species name comes from
a `labels`/`label_types` join and the timestamp is a Unix epoch. The frame's read
adapter (`db.py`) is the one place that knows this schema; nothing else in the
renderer sees BirdNET-Go SQL. The adapter opens the file `mode=ro`.

Two decisions make the direct read work:

- **Disk, not tmpfs.** BirdNET-Go's DB used to live on a RAM tmpfs to spare the
  SD card, which forced a second durable DB and a copying sync process. On NVMe
  the SD-wear concern is gone, so the DB persists on disk and the sync step is
  deleted.
- **Bind mount, not a named volume.** BirdNET-Go's DB is bind-mounted from the
  container to a host path (`detector/data`, gitignored). The frame runs on the
  *host* and reads the same file; named volumes aren't cleanly host-accessible.

See issue #7 for the full rationale.

## Species names come over the API, not the DB

BirdNET-Go's `labels` table holds the scientific name alone - no common names, no
locale table - so the frame's language settings read them from the container's
own API on `:8090` instead: `/api/v2/settings/locales` for the list,
`/api/v2/species/dictionary/<code>` for `{scientific name: common name}`. Only
some locales have a dictionary, so the admin offers the ones a `HEAD` confirms.
Dictionaries are cached under `data/names/` and revalidated by ETag; with the
container stopped and nothing cached, names fall back to the scientific name.

## Layout

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | BirdNET-Go container: mic via `/dev/snd`, birdnet.db bind-mounted from `./data` (persistent), web UI on `:8090` |
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
  it is vendored - the compose pulls a prebuilt image and `db.py` only knows the
  schema - which is what keeps this repo MIT. Don't fork it into the tree.
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
