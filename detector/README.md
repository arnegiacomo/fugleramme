# Detector (issue #3)

The detector half of the appliance: a USB mic feeds **BirdNET-Go**, which
classifies bird sounds and logs them to its own SQLite. A small host-side syncer
(`fugleramme-sync`) copies those into the frame's durable `detections.db`. The
two halves meet only at the DB.

```
USB mic --> BirdNET-Go (container) --> birdnet.db (tmpfs) --> fugleramme-sync --> detections.db (disk) --> frame (#1)
```

## Why a syncer instead of pointing the frame at BirdNET-Go's DB

BirdNET-Go's schema is not the frame's: it is GORM-migrated and normalized (the
species name comes from a `labels` join, the timestamp is a Unix epoch), and its
own table is confusingly also called `detections`. The syncer is the one place
that knows both, so:

- a BirdNET-Go schema change touches `sync.py` only, never the renderer;
- dev/prod parity holds - `detections` is a real table everywhere, so `seed.py`
  and the tests keep working unchanged;
- BirdNET-Go's DB can live on **tmpfs (RAM)** while `detections.db` stays durable
  on disk, keeping BirdNET-Go's writes off the SD card.

See issue #3 for the full rationale.

## Layout

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | BirdNET-Go container: mic via `/dev/snd`, birdnet.db on a tmpfs bind mount, web UI on `:8090` |
| `config/config.yaml` | BirdNET-Go config: Bergen lat/lon + range/week filter, `interval` debounce, clips off, SQLite at `/data/birdnet.db` |
| `preflight.sh` | Fatal check that an ALSA capture device exists |
| `fugleramme-tmpfiles.conf` | Recreates the tmpfs data dir on boot |

## Deploy

Pull the repo on the Pi and run one command:

```bash
./setup.sh          # add -y to auto-accept dependency installs
```

It installs anything missing (uv, docker, alsa-utils - prompting first), runs
`uv sync`, checks the mic, installs the tmpfiles rule, brings up BirdNET-Go, and
enables the `fugleramme-sync` and `fugleramme-frame` systemd services. Follow
them with:

```bash
journalctl -u fugleramme-sync -u fugleramme-frame -f
```

To run the syncer by hand instead:

```bash
uv run fugleramme-sync --source /dev/shm/fugleramme/birdnet.db --db data/detections.db
```

## Deployment notes

- **Image pin:** BirdNET-Go ships only nightlies; the compose pins a dated tag.
  Bump it deliberately after testing rather than tracking `nightly`.
- **Mic device:** `config.yaml` uses ALSA `default`, which may resolve to the
  wrong card on a headless Pi. If no detections appear, set the source `device`
  to the mic (e.g. `plughw:CARD=Device,DEV=0`); `preflight.sh` prints the
  capture devices to choose from.
- **Audio group:** the container needs the host `audio` group to read `/dev/snd`.
  If `group_add: audio` fails, substitute the numeric GID from
  `getent group audio`.
- **Location:** lat/lon is hardcoded to Bergen here; the admin panel (#2) will
  own it later.
