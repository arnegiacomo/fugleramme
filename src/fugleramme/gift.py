"""Gift mode (#355): ready a working frame to be given, with a splash on it in the box.

The last step after an install that works. `fugleramme-gift` borrows the frame: it stops the
frame service, asks where the frame is going, when it arrives, a note and the giver's
favourite birds, and draws the splash on the panel itself. Wrapping deletes this place's
history, writes the recipient's place into BirdNET-Go's config, saves their Wi-Fi, can clear
the admin password, and leaves the frame service stopped with the splash on the glass.

The frame service knows nothing of any of it. It is still enabled, so the next boot, at the
recipient's, starts an ordinary frame: their birds, or the Wi-Fi setup if it has no network.
BirdNET-Go comes back with it because wrapping sets the container to restart always.

What `unwrap` needs lives in /dev/shm, which is memory: it is there until the power goes, and
so is the undo. Bundled BirdNET-Go only (`detector/.env` marks an appliance).
"""

from __future__ import annotations

import contextlib
import difflib
import json
import logging
import os
import re
import shutil
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, fields
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

from . import languages, taxa
from .config import DEFAULT_CONFIG_PATH, REPO_ROOT
from .names import canonical, normalize

log = logging.getLogger(__name__)

UNIT = "fugleramme-frame"  # run.sh's systemd unit
CONTAINER = "birdnet-go"  # detector/docker-compose.yml's container_name
SPLASH_BIRDS = 8  # favourites first, then the likeliest with a plate
SSID_BYTES = 32
PSK_CHARS = (8, 63)  # WPA2's passphrase
PLACES = "https://photon.komoot.io/api/?limit=5&q="  # the admin's station finder asks the same
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")  # date.fromisoformat also takes 20270512
_LAT_LON = re.compile(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*")


@dataclass(frozen=True)
class Paths:
    """Where an appliance keeps what wrapping changes. Fields, not constants, for the tests."""

    data: Path = DEFAULT_CONFIG_PATH.parent  # BirdNET-Go's /data, settings.json beside it
    detector: Path = REPO_ROOT / "detector"
    undo: Path = Path("/dev/shm/fugleramme-gift.json")  # memory: gone with the power

    @property
    def settings(self) -> Path:
        return self.data / "settings.json"

    @property
    def birdnet_config(self) -> Path:
        return self.detector / "config" / "config.yaml"

    @property
    def env(self) -> Path:
        return self.detector / ".env"


@dataclass(frozen=True)
class Splash:
    """What the splash shows."""

    month: str  # the arrival's, for the subtitle
    notes: tuple[str, ...]
    birds: tuple[str, ...]  # scientific names, the spotlight among them
    spotlight: str | None  # the first favourite


@dataclass(frozen=True)
class Restore:
    """What `unwrap` puts back, recorded before the step that changes it. The history is not
    in it: wrapping deletes that."""

    restart: str = ""  # the container's restart policy before wrapping set it to always
    latitude: str = ""
    longitude: str = ""
    wifi: str = ""  # the saved profile's uuid
    admin_password: str | None = None  # None: left alone


def read_undo(path: Path) -> Restore | None:
    """The undo record, or None. One that is not exactly what `write_undo` writes is deleted
    and said so: half a record would put back half a frame."""
    try:
        return _undo(json.loads(path.read_text()))
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError) as error:
        log.warning("Deleting %s, it is not an undo record: %s", path, error)
        with contextlib.suppress(OSError):
            path.unlink()
        return None


def _undo(raw: Any) -> Restore:
    """`write_undo`'s output read back strictly: every key, no others, each of its type."""
    if not isinstance(raw, dict) or set(raw) != {f.name for f in fields(Restore)}:
        raise ValueError("not the keys an undo record has")
    password = raw.pop("admin_password")
    if not all(isinstance(v, str) for v in raw.values()) or not isinstance(password, str | None):
        raise TypeError("a value is not text")
    for key in ("latitude", "longitude"):
        if raw[key]:
            float(raw[key])  # written back into config.yaml as it stands
    return Restore(**raw, admin_password=password)


def write_undo(path: Path, restore: Restore) -> None:
    """Atomic, and 0600: it can hold the admin password."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(asdict(restore), indent=2) + "\n")
    os.replace(tmp, path)


# -- what goes on the splash -------------------------------------------------


def week(day: date) -> int:
    """BirdNET's 48-week year, four weeks a month (`calculateWeek` in upstream's range.go)."""
    return (day.month - 1) * 4 + min((day.day - 1) // 7 + 1, 4)


def splash_birds(
    scores: Iterable[tuple[str, float]], favourites: Iterable[str], drawable: set[str]
) -> tuple[str, ...]:
    """Favourites first whatever the range model thinks of them, then the likeliest birds
    the style has a plate for, up to SPLASH_BIRDS."""
    chosen: dict[str, str] = {}
    for name in [*favourites, *(name for name, _score in scores)]:
        key = normalize(name)
        if key in drawable and key not in chosen:
            chosen[key] = canonical(name)
    return tuple(chosen.values())[:SPLASH_BIRDS]


# -- the form's checks: each returns what is wrong, "" when nothing is --------


@dataclass(frozen=True)
class Place:
    label: str
    latitude: float
    longitude: float


def find_place(text: str, fetch: Callable[[str], Any] | None = None) -> Place | None:
    """A typed `lat, lon`, else the first place Photon has by that name. Raises OSError
    when Photon cannot be asked."""
    typed = _LAT_LON.fullmatch(text)
    if typed:
        lat, lon = float(typed[1]), float(typed[2])
        return Place(text.strip(), lat, lon) if abs(lat) <= 90 and abs(lon) <= 180 else None
    features = (fetch or _photon)(text.strip()).get("features") or []
    if not features:
        return None
    props, (lon, lat) = features[0]["properties"], features[0]["geometry"]["coordinates"]
    parts = [props.get("name"), props.get("city") or props.get("county"), props.get("state")]
    label = ", ".join(dict.fromkeys(p for p in [*parts, props.get("country")] if p))
    return Place(label, float(lat), float(lon))


def _photon(text: str) -> Any:
    with urlopen(PLACES + quote(text), timeout=10) as answer:
        return json.load(answer)


def arrival(text: str, today: date) -> tuple[date | None, str]:
    if not _DATE.fullmatch(text.strip()):
        return None, "use YYYY-MM-DD"
    try:
        day = date.fromisoformat(text.strip())
    except ValueError:
        return None, "not a date"
    return (None, "in the past") if day < today else (day, "")


def ssid_problem(name: str) -> str:
    return "too long" if len(name.encode()) > SSID_BYTES else ""


def password_problem(password: str) -> str:
    low, high = PSK_CHARS
    return "" if not password or low <= len(password) <= high else f"WPA2 needs {low}-{high}"


@dataclass(frozen=True)
class Names:
    """Every name a favourite can be typed as, against its scientific name."""

    by_name: dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, cache_dir: Path, language: str) -> Names:
        """The labels' English and scientific names, and the frame's own language's from
        the dictionary cached beside the settings."""
        english = {common: _scientific(key) for key, common in taxa.labels().items() if common}
        scientific = {_scientific(key): _scientific(key) for key in taxa.labels()}
        local, _version = languages.dictionary(language, cache_dir)
        by_name = {**{n: s for s, n in local.items()}, **english, **scientific}
        return cls({_folded(name): canonical(sci) for name, sci in by_name.items()})


def _scientific(key: str) -> str:
    """ "cyanocitta-stelleri" -> "Cyanocitta stelleri"."""
    return key.replace("-", " ").capitalize()


def _folded(name: str) -> str:
    """Case, apostrophes and hyphens are not worth a ✗: "stellers jay" is Steller's Jay."""
    return re.sub(r"[\s\-]+", " ", re.sub(r"['’]", "", name.lower())).strip()


def favourite(
    text: str, names: Names, drawable: set[str], scores: dict[str, float]
) -> tuple[str | None, str]:
    """(scientific name, problem). A typo gets the likeliest bird with a plate it could
    mean, by the range model's score where the frame is going: "robin" is an American
    Robin in Ohio, not a Rose Robin."""
    typed = _folded(text)
    exact = names.by_name.get(typed)
    if exact:
        return (exact, "") if normalize(exact) in drawable else (None, f"no plate for {text}")
    near = difflib.get_close_matches(typed, names.by_name, n=20, cutoff=0.6)
    # Word by word too, or "cardnal" never reaches "northern cardinal" as a whole.
    vocabulary = {word for name in names.by_name for word in name.split()}
    meant = [
        {word, *difflib.get_close_matches(word, vocabulary, n=5, cutoff=0.8)}
        for word in typed.split()
    ]
    worded = [
        name
        for name in names.by_name
        if meant and all(options & set(name.split()) for options in meant)
    ]
    guesses = [
        names.by_name[name]
        for name in dict.fromkeys([*near, *worded])
        if normalize(names.by_name[name]) in drawable
    ]
    if not guesses:
        return None, f"no bird called {text}"
    best = max(guesses, key=lambda sci: scores.get(sci, 0.0))
    return None, f"no match - {taxa.common_of(best) or best}?"


# -- wrapping and unwrapping -------------------------------------------------


def appliance(paths: Paths) -> str:
    """Why this frame cannot be wrapped, "" when it can."""
    if not paths.env.exists():
        return "gift mode needs the BirdNET-Go that install.sh sets up on this Pi"
    if not paths.birdnet_config.exists():
        return f"no {paths.birdnet_config}: run run.sh first"
    return ""


def docker(*args: str) -> str:
    """A docker command's output, through sudo where the docker group has not taken yet,
    as run.sh does."""
    command = ["docker"]
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:
        command = ["sudo", "-n", "docker"]
    done = subprocess.run([*command, *args], capture_output=True, text=True, check=False)
    if done.returncode != 0:
        raise RuntimeError(f"docker {' '.join(args[:2])}: {done.stderr.strip()}")
    return done.stdout.strip()


def compose(paths: Paths, *args: str) -> str:
    """`docker compose` on the bundled detector."""
    files = ["--env-file", str(paths.env), "-f", str(paths.detector / "docker-compose.yml")]
    return docker("compose", *files, *args)


_SECTION = re.compile(r"(?m)^birdnet:[ \t]*$")
_NEXT_SECTION = re.compile(r"(?m)^\S")
_COORD = r"(?m)^([ \t]+{}:[ \t]*)(\S+)"


def located(text: str, latitude: str, longitude: str) -> tuple[str, str, str]:
    """BirdNET-Go's config with `birdnet.latitude`/`longitude` replaced, and the two old
    values. By line, not by YAML, to leave the rest of the file as BirdNET-Go wrote it."""
    section = _SECTION.search(text)
    if section is None:
        raise ValueError("no birdnet section in config.yaml")
    start = section.end()
    after = _NEXT_SECTION.search(text, start + 1)
    end = after.start() if after else len(text)
    block, old = text[start:end], []
    for key, value in (("latitude", latitude), ("longitude", longitude)):
        match = re.search(_COORD.format(key), block)
        if match is None:
            raise ValueError(f"no birdnet.{key} in config.yaml")
        old.append(match[2])
        block = block[: match.start(2)] + value + block[match.end(2) :]
    return text[:start] + block + text[end:], old[0], old[1]


def forget_history(paths: Paths) -> None:
    """Delete this place's detections and clips, with the detector stopped. BirdNET-Go
    starts an empty database at the recipient's."""
    for name in ("birdnet.db", "birdnet.db-wal", "birdnet.db-shm"):
        (paths.data / name).unlink(missing_ok=True)
    shutil.rmtree(paths.data / "clips", ignore_errors=True)


@dataclass(frozen=True)
class Wrapping:
    """What the form hands `wrap`, every field already checked."""

    place: Place
    splash: Splash
    ssid: str = ""
    password: str = ""
    clear_admin: bool = False


Step = Callable[[str], None]


def wrap(
    paths: Paths,
    wrapping: Wrapping,
    save_wifi: Callable[[str, str], str],
    clear_admin: Callable[[], str],
    draw: Callable[[Splash], None],
    done: Step = lambda line: None,
) -> None:
    """Ready the frame for its new home and draw the splash, with the frame service already
    stopped. The undo record is written before each step that changes something, so
    `unwrap` can put back what a wrap that failed half way had done. `save_wifi` returns the
    profile's uuid, `clear_admin` the password it cleared."""
    restore = Restore()

    def record(**changes: Any) -> None:
        nonlocal restore
        restore = Restore(**{**asdict(restore), **changes})
        write_undo(paths.undo, restore)

    # `unless-stopped` would leave a container stopped by hand stopped at every boot from
    # here; `always` brings it back at the recipient's first one.
    policy = docker("inspect", "-f", "{{.HostConfig.RestartPolicy.Name}}", CONTAINER)
    record(restart=policy)
    docker("update", "--restart", "always", CONTAINER)
    compose(paths, "stop")
    done("Detector stopped; it starts again on the first boot")
    forget_history(paths)
    done("This place's birds deleted")
    place = wrapping.place
    text = paths.birdnet_config.read_text()
    new, lat, lon = located(text, f"{place.latitude:.4f}", f"{place.longitude:.4f}")
    record(latitude=lat, longitude=lon)
    paths.birdnet_config.write_text(new)
    done(f"Location set to {place.label}")
    if wrapping.ssid:
        record(wifi=save_wifi(wrapping.ssid, wrapping.password))
        done(f"Wi-Fi {wrapping.ssid} saved")
    if wrapping.clear_admin:
        record(admin_password=clear_admin())
        done("Admin password cleared")
    draw(wrapping.splash)
    os.sync()  # the card has everything before anyone pulls the plug
    done("Splash drawn")


def unwrap(
    paths: Paths, forget_wifi: Callable[[str], None], restore_admin: Callable[[str], None]
) -> bool:
    """Put back what `wrap` changed, before the frame is unplugged: the place, the Wi-Fi,
    the admin password and the detector. Not the history, which is gone. False when there
    is nothing to undo."""
    restore = read_undo(paths.undo)
    if restore is None:
        return False
    if restore.latitude and restore.longitude:
        text = paths.birdnet_config.read_text()
        new, _lat, _lon = located(text, restore.latitude, restore.longitude)
        paths.birdnet_config.write_text(new)
    if restore.wifi:
        forget_wifi(restore.wifi)
    if restore.admin_password is not None:
        restore_admin(restore.admin_password)
    if restore.restart:
        docker("update", "--restart", restore.restart, CONTAINER)
        compose(paths, "start")
    paths.undo.unlink(missing_ok=True)
    return True
