# Install, update and the container image

Covers `install.sh`, `run.sh`, `updates.py` and the `Dockerfile`.

## Configuring a fresh install

**The environment seeds settings; it never overrides them** (`settings.from_env`). `FUGLERAMME_<FIELD>` for any field of `Settings`, read off the dataclass so a new setting needs nothing added. It exists for the container image, where a fresh `/data` has no `settings.json` and the detector's address has to come from somewhere. These become the store's *defaults*, exactly as `--detector` does: a key the file carries wins, so a variable goes quiet from the first Save on. Override-on-boot instead and the admin page - which offers to change every one of them - would be lying. Precedence is `settings.json` > `--detector` > environment > built-in default.

## The install splits at the reboot (`install.sh`, `run.sh`)

- `install.sh` is the curl'able one-time bootstrap: deps, clone, groups, SPI/I2C overlays, gadget mode. Everything in it only takes effect on boot, so it is the only script that prompts a reboot - and only if something actually changed. It must stay self-contained; it is fetched before the checkout exists.
- `install.sh` also asks where BirdNET-Go lives: installed here, already running on this machine, or on another. The answer plus the two ports land in a gitignored `frame.env` at the repo root, which `run.sh` sources. Only a bundled detector gets a `detector/.env`, so an external install skips the container everywhere by that one marker.
- `run.sh` is the idempotent converge: `uv sync`, config, compose up, systemd unit. Re-run after a pull or a repo move - it bakes `$REPO_ROOT`, the frame's port and the detector's URL into the unit.
- **`updates.apply` never re-runs `run.sh`.** A Pi that auto-updates keeps its old unit, its old `detector/.env` and its old `settings.json`, so every default a release introduces must reproduce the previous one's behaviour: frame on 8080, bundled detector on 8090, `detector_url` of `http://127.0.0.1:8090`. A new compose variable needs its default inline (`${BIRDNET_PORT:-8090}`), not only in `frame.env`. Get this wrong and working appliances break on update, which is the one failure nobody can recover from remotely.
- The self-update converges the detector too, so a release can move the image pin (`updates._converge_detector`). It is `up -d`, not run.sh's `--force-recreate`: an unchanged pin must not bounce a working detector. `detector/.env` is the marker for "an appliance, not a dev checkout", and a failure only logs - the frame is already on the new version by then. The DB is copied to `birdnet.db.bak` first and a failed copy skips the swap, since the new container migrates it in place on first start. Upstream tags by date and the pin reaches every frame, so test a bump on the Pi before tagging the release that carries it.
- With a reboot pending, `--no-start` leaves the frame enabled but stopped, since there is no SPI and no group membership yet. The container starts either way: `restart: unless-stopped` only revives a container that was already running.
- Prompts read `/dev/tty`, not stdin - under `curl | bash` stdin is the script itself. Same reason the body is wrapped in `main`, called on the last line.
- New machine-specific values must be detected or prompted for and written to gitignored per-Pi configuration, not hardcoded in tracked defaults.
- BirdNET-Go must run with the host user's UID and GID so its mounted config and data remain writable without changing checkout ownership.
- USB gadget access is documented in troubleshooting; do not assume `10.12.194.1` when macOS Internet Sharing may assign a leased address.

## The image is the kiosk alone

`Dockerfile`, `.dockerignore`, `.github/workflows/image.yml`.

- Pull it, point it at a BirdNET-Go you already run, read the collage on a web page. No panel (SPI, I2C and the buttons are the Pi's) and `install.sh` knows nothing about it - both their own follow-ups, not gaps to fill in passing.
- The *image* is the kiosk alone; `examples/docker-compose.yml` is what brings a detector up beside it, for a machine with a mic and no panel. It is documentation, curl'able straight from `main`, so it pins the same BirdNET-Go tag `detector/docker-compose.yml` does - `tests/test_container.py` holds the two together, since the pin only moves after it is tested on the Pi.
- **The checkout's shape has to survive into the image.** `config.REPO_ROOT` is derived from the package's own file, and the artwork, the fonts, the labels and `bird_sizes.csv` all hang off it, so the project is installed editable at `/app` with `/app/src/fugleramme` beside `/app/assets`. A build-time `RUN python -c` asserts it: fail the build, not the first render.
- The plates are split across a COPY layer per letter range so a release adding a species re-pulls that range instead of all 165 MB - the registry serves blobs by digest, so the letters that did not move are already on disk. The ranges must leave no letter out, and a range matching nothing fails the build; `tests/test_container.py` reads the globs back out of the Dockerfile and holds them to both.
- Everything mutable already derives from `--config`'s parent, so one volume at `/data` is the whole persistence story and no code knows about it. A fresh one is configured through `FUGLERAMME_<FIELD>`, which seeds and never overrides - see the settings rule above.
- **`updates.apply` refuses in a container** (`updates.in_container`, the image's own `FUGLERAMME_CONTAINER`): there is no checkout to move onto a tag, no systemd to restart it, and handing the frame the docker socket buys a button. `available()` still runs - knowing a release is out is the half that works - and the admin drops the Install button, shows the auto-update toggle disabled, and prints `updates.CONTAINER_COMMAND` in its place.
- **The panel half stays on systemd + git, not in an image.** A git update ships about 2.5 MB to a Pi on wifi; pulling a new image ships the whole artwork tree, near 1 GB, and layer ordering does not help because the assets layer is the one that keeps changing. The letter-range COPY layers above are what make that bearable for the kiosk image, where the machine is on ethernet.
- `image.yml` is a separate workflow from `release.yml`, fired by the tag that one pushes. The release's job is to cut the tag; a slow or broken image build must never delay or fail a version bump. Native runners per architecture, pushed by digest, with a merge job for the manifest list.
