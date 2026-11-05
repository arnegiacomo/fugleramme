"""Gift mode (#355): ready a working frame to be given, and hold a splash on it in the box.

The last step after an install that works: `fugleramme-gift` asks where the frame is going,
when it arrives, a note and the giver's favourite birds, and wraps it. Wrapping stops the
bundled detector, sets this place's history aside, writes the recipient's place into
BirdNET-Go's config, saves their Wi-Fi and can clear the admin password. The service then
draws the splash and freezes until it is unplugged; its first boot after that ends gift mode
and it is an ordinary frame from there, with the Wi-Fi setup if it has no network.

The CLI never draws. It writes `gift.json` beside `settings.json` and the service, which owns
the panel, reads it on every tick. With no such file the service is exactly what it was.

Bundled BirdNET-Go only (`detector/.env` marks an appliance): the history and the place
being changed are its own.
"""

from __future__ import annotations

import contextlib
import difflib
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, field, replace
from datetime import date
from pathlib import Path
from typing import Any
from urllib.parse import quote
from urllib.request import urlopen

from . import languages, taxa
from .config import DEFAULT_CONFIG_PATH, REPO_ROOT
from .names import canonical, normalize

log = logging.getLogger(__name__)

PREVIEW = "preview"  # the splash is on the glass for a look; nothing else has changed
WRAPPING = "wrapping"  # everything is done but the final draw, which the service owes
WRAPPED = "wrapped"  # drawn and synced: frozen until the power goes

SPLASH_BIRDS = 8  # favourites first, then the likeliest with a plate
SSID_BYTES = 32
PSK_CHARS = (8, 63)  # WPA2's passphrase
PLACES = "https://photon.komoot.io/api/?limit=5&q="  # the admin's station finder asks the same
_BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")  # date.fromisoformat also takes 20270512
_LAT_LON = re.compile(r"\s*(-?\d+(?:\.\d+)?)\s*,\s*(-?\d+(?:\.\d+)?)\s*")


@dataclass(frozen=True)
class Paths:
    """Where an appliance keeps what wrapping changes. Fields, not constants, for the tests."""

    data: Path = DEFAULT_CONFIG_PATH.parent  # BirdNET-Go's /data, settings.json beside it
    detector: Path = REPO_ROOT / "detector"

    @property
    def gift(self) -> Path:
        return self.data / "gift.json"

    @property
    def settings(self) -> Path:
        return self.data / "settings.json"

    @property
    def history(self) -> Path:
        """This place's detections and clips while the frame is wrapped."""
        return self.data / "gift-history"

    @property
    def birdnet_config(self) -> Path:
        return self.detector / "config" / "config.yaml"

    @property
    def env(self) -> Path:
        return self.detector / ".env"


@dataclass(frozen=True)
class Restore:
    """What `unwrap` puts back. Recorded before the step that changes it."""

    latitude: str = ""
    longitude: str = ""
    admin_password: str | None = None  # None: left alone
    wifi: str = ""  # the profile's uuid
    stopped: bool = False  # the detector, so unwrap starts it again


@dataclass(frozen=True)
class Gift:
    state: str
    month: str  # the arrival's, for the splash's subtitle
    notes: tuple[str, ...]
    birds: tuple[str, ...]  # scientific names, the spotlight first if there is one
    spotlight: str | None  # the first favourite
    error: str = ""  # the service's reason it cannot draw it
    boot: str = ""  # the boot the wrap finished in; another one means it has been given
    restore: Restore | None = None

    def splash_key(self) -> tuple:
        """What the splash is a function of."""
        return (self.month, self.notes, self.birds, self.spotlight)


def read(path: Path) -> Gift | None:
    """The gift on this frame, or None. An unreadable file is no gift: a frame whose file
    broke shows its birds rather than a splash it cannot draw."""
    try:
        raw = json.loads(path.read_text())
        restore = raw.get("restore")
        return Gift(
            state=str(raw["state"]),
            month=str(raw["month"]),
            notes=tuple(str(n) for n in raw.get("notes", ())),
            birds=tuple(str(b) for b in raw.get("birds", ())),
            spotlight=raw.get("spotlight") or None,
            error=str(raw.get("error", "")),
            boot=str(raw.get("boot", "")),
            restore=Restore(**restore) if isinstance(restore, dict) else None,
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError, TypeError, KeyError, AttributeError) as error:
        log.warning("Ignoring %s: %s", path, error)
        return None


def write(path: Path, gift: Gift) -> None:
    """Atomic, and 0600: the restore record can hold the admin password."""
    tmp = path.with_name(path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(json.dumps(asdict(gift), indent=2) + "\n")
    os.replace(tmp, path)


def boot_id() -> str:
    """This boot's id, "" off Linux. A dev machine never sees a gift opened."""
    try:
        return _BOOT_ID.read_text().strip()
    except OSError:
        return ""


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


# -- wrapping, unwrapping and opening ----------------------------------------


def appliance(paths: Paths) -> str:
    """Why this frame cannot be wrapped, "" when it can."""
    if not paths.env.exists():
        return "gift mode needs the BirdNET-Go that install.sh sets up on this Pi"
    if not paths.birdnet_config.exists():
        return f"no {paths.birdnet_config}: run run.sh first"
    return ""


def compose(paths: Paths, *args: str) -> None:
    """`docker compose` on the bundled detector, through sudo where the docker group has
    not taken yet, as run.sh does."""
    files = ["--env-file", str(paths.env), "-f", str(paths.detector / "docker-compose.yml")]
    docker = ["docker"]
    if subprocess.run(["docker", "info"], capture_output=True, check=False).returncode != 0:
        docker = ["sudo", "-n", "docker"]
    done = subprocess.run(
        [*docker, "compose", *files, *args], capture_output=True, text=True, check=False
    )
    if done.returncode != 0:
        raise RuntimeError(f"docker compose {' '.join(args)}: {done.stderr.strip()}")


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


def _db_files(data: Path) -> list[Path]:
    return [data / name for name in ("birdnet.db", "birdnet.db-wal", "birdnet.db-shm")]


def set_aside(paths: Paths) -> None:
    """Move this place's detections and clips out of the detector's sight. The database is
    copied with sqlite's backup, which is consistent under WAL, before the files go."""
    paths.history.mkdir(exist_ok=True)
    db = paths.data / "birdnet.db"
    if db.exists():
        source = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        target = sqlite3.connect(paths.history / "birdnet.db")
        try:
            source.backup(target)
        finally:
            target.close()
            source.close()
        for path in _db_files(paths.data):
            path.unlink(missing_ok=True)
    clips = paths.data / "clips"
    if clips.exists():
        clips.rename(paths.history / "clips")


def put_back(paths: Paths) -> None:
    """`set_aside` undone, over anything the detector wrote meanwhile."""
    if not paths.history.exists():
        return
    kept = paths.history / "birdnet.db"
    if kept.exists():
        for path in _db_files(paths.data):
            path.unlink(missing_ok=True)
        kept.rename(paths.data / "birdnet.db")
    clips = paths.history / "clips"
    if clips.exists():
        shutil.rmtree(paths.data / "clips", ignore_errors=True)
        clips.rename(paths.data / "clips")
    shutil.rmtree(paths.history)


@dataclass(frozen=True)
class Wrapping:
    """What the form hands `wrap`, every field already checked."""

    place: Place
    month: str
    notes: tuple[str, ...]
    birds: tuple[str, ...]
    spotlight: str | None
    ssid: str = ""
    password: str = ""
    clear_admin: bool = False


Step = Callable[[str], None]


def wrap(
    paths: Paths,
    wrapping: Wrapping,
    save_wifi: Callable[[str, str], str],
    clear_admin: Callable[[], str],
    done: Step = lambda line: None,
) -> None:
    """Everything but the final draw, which the service does on reading WRAPPING. The
    restore record is written before each step that changes something, so `unwrap` can
    undo a wrap that fails half way. `save_wifi` returns the profile's uuid, `clear_admin`
    the password it cleared."""
    gift = Gift(
        PREVIEW,
        wrapping.month,
        wrapping.notes,
        wrapping.birds,
        wrapping.spotlight,
        restore=Restore(),
    )

    def record(**changes: Any) -> None:
        nonlocal gift
        assert gift.restore is not None
        gift = replace(gift, restore=replace(gift.restore, **changes))
        write(paths.gift, gift)

    record(stopped=True)
    compose(paths, "stop")
    done("Detector stopped")
    set_aside(paths)
    done("This place's birds set aside")
    text = paths.birdnet_config.read_text()
    place = wrapping.place
    new, lat, lon = located(text, f"{place.latitude:.4f}", f"{place.longitude:.4f}")
    record(latitude=lat, longitude=lon)
    paths.birdnet_config.write_text(new)
    done(f"Location set to {wrapping.place.label}")
    if wrapping.ssid:
        record(wifi=save_wifi(wrapping.ssid, wrapping.password))
        done(f"Wi-Fi {wrapping.ssid} saved")
    if wrapping.clear_admin:
        record(admin_password=clear_admin())
        done("Admin password cleared")
    write(paths.gift, replace(gift, state=WRAPPING))


def unwrap(
    paths: Paths,
    gift: Gift,
    forget_wifi: Callable[[str], None],
    restore_admin: Callable[[str], None],
) -> None:
    """Undo `wrap` on a frame that has not been unplugged since."""
    restore = gift.restore or Restore()
    put_back(paths)
    if restore.latitude and restore.longitude:
        text = paths.birdnet_config.read_text()
        new, _lat, _lon = located(text, restore.latitude, restore.longitude)
        paths.birdnet_config.write_text(new)
    if restore.wifi:
        forget_wifi(restore.wifi)
    if restore.admin_password is not None:
        restore_admin(restore.admin_password)
    paths.gift.unlink(missing_ok=True)
    if restore.stopped:
        compose(paths, "start")


def opened(paths: Paths, gift: Gift | None, boot: str) -> bool:
    """On the service's start: a wrapped gift in a boot other than the one it was wrapped
    in has been given. The detector starts, the set-aside history goes, and the frame is
    ordinary from here. True when it was opened."""
    if gift is None or gift.state != WRAPPED or not boot or gift.boot == boot:
        return False
    with contextlib.suppress(OSError):
        shutil.rmtree(paths.history)
    paths.gift.unlink(missing_ok=True)
    try:
        compose(paths, "start")
    except (RuntimeError, OSError) as error:
        log.warning("Gift opened, but the detector did not start: %s", error)
    return True
