"""What rendering costs in memory, measured in a process of its own so nothing another
test left behind is in the numbers: it does not build up from one render to the
next, and one render peaks under a ceiling. On Linux with glibc only, since the
first is about glibc's allocator and both read /proc."""

from __future__ import annotations

import json
import platform
import shutil
import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

pytestmark = pytest.mark.skipif(
    platform.libc_ver()[0] != "glibc", reason="measures glibc's allocator, through /proc"
)

# Starts as a frame does, up to where its web server would start, and reads its own
# memory in MB. VmHWM is the peak of this process alone; getrusage's starts out at the
# peak of the test run that spawned it.
_START = """
import json, sys, threading
from pathlib import Path

from PIL import Image

from fugleramme import cli, service
from fugleramme.render.collage import render_collage
from fugleramme.render.dither import dither
from fugleramme.render.paper import PANEL_PAPER


class Up(Exception):
    pass


def up(*_args):
    raise Up


home = sys.argv[1]
service.init_panel = lambda: None
service._wifi_setup = lambda *_args: None
service.serve = up
try:
    cli.main(["--images", home, "--config", home + "/settings.json", "--port", "0"])
except Up:
    pass
entries = [(path.stem, path) for path in sorted(Path(home).glob("*.webp"))]

def mb(field):
    status = Path("/proc/self/status").read_text()
    return int(status.split(field + ":")[1].split()[0]) / 1024
"""

# Every render on a thread of its own that stays alive, as requests that overlap do:
# glibc gives each such thread its own arena, and one thread after another would share one.
# Each draws plates no render before it drew, so what is kept for a plate shows as well.
_RENDERS = """
drawn, parked = threading.Semaphore(0), threading.Event()

def request(plates):
    render_collage(plates, (1000, 750), show_names=False)
    drawn.release()
    parked.wait()

sizes = []
for n in range(0, len(entries), 16):
    threading.Thread(target=request, args=(entries[n : n + 16],), daemon=True).start()
    drawn.acquire()
    sizes.append(mb("VmRSS"))
print(json.dumps(sizes))
"""

# The dither first, on bare paper: a peak is never taken back, and the draw's is the higher.
_PANEL_PAGE = """
page = Image.new("RGB", (1600, 1200), PANEL_PAPER)
before = mb("VmRSS")
dither(page)
dithered = mb("VmHWM") - before
before = mb("VmRSS")
render_collage(entries[:36], (1600, 1200), show_names=False, textured=False)
print(json.dumps([dithered, mb("VmHWM") - before]))
"""


@pytest.fixture(scope="module")
def plates(tmp_path_factory):
    """96 made-up plates the size of the largest shipped ones, 1200 by 900: a bird in a
    ring of scan paper, as lossless WebP. One picture under 96 names, since a plate is
    known by its file."""
    folder = tmp_path_factory.mktemp("plates")
    y, x = np.ogrid[:900, :1200]
    out = np.hypot((x - 600) / 600, (y - 450) / 450)
    art = np.zeros((900, 1200, 4), np.uint8)
    art[out < 0.95] = (228, 221, 204, 255)
    art[out < 0.6] = (40, 90, 200, 255)
    Image.fromarray(art).save(folder / "genus-species0.webp", lossless=True, method=0)
    for n in range(1, 96):
        shutil.copy(folder / "genus-species0.webp", folder / f"genus-species{n}.webp")
    return folder


def _measured(script: str, plates):
    done = subprocess.run(
        [sys.executable, "-c", _START + script, str(plates)],
        check=True,
        stdout=subprocess.PIPE,
        timeout=120,
    )
    return json.loads(done.stdout)


def test_memory_does_not_build_up_from_one_render_to_the_next(plates):
    """glibc kept what a render freed, 15 MB on each thread for a page like these, until
    the service pinned its mmap threshold (#396). A thread that has rendered still keeps
    2 MB of small blocks. Silhouettes kept from one render to the next would be 17 MB a
    page, each page being of plates no page before it drew."""
    sizes = _measured(_RENDERS, plates)
    assert sizes[-1] - sizes[0] < 35, sizes


def test_a_render_peaks_under_its_ceiling(plates):
    """Two tripwires, each with room for a library to grow in. The dither takes the
    process 40 MB above where it stood, and 80 MB or more with its pre-pass over the
    whole page at once, or with one more copy of the page in float64. Packing and
    drawing this page takes 57 MB, and 157 MB with every decoded plate kept to the end
    of the draw."""
    dithered, drawn = _measured(_PANEL_PAGE, plates)
    assert dithered < 55
    assert drawn < 75
