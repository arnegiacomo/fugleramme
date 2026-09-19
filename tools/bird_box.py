"""Review and adjust a style's bird boxes, one plate at a time, in the browser.

The collage scales a cut-out's longest side to what the species' mass asks for,
which is the bird's own length only when the plate is one bird cut tight. A bird
box says where the bird actually sits in the file, and `sizes.span_ratio` turns
that into how much bigger the plate has to be drawn. The boxes are detected in
bulk on a workstation; the ones that come back from review wrong are fixed here.

Dragging a rectangle tells you nothing on its own, so the page renders the bird
at the size the box implies beside three birds of known weight. That row, not
the rectangle, is what says whether a box is right.

Usage:
    uv run python tools/bird_box.py
    uv run python tools/bird_box.py --only ~/Desktop/wrong.txt
    uv run python tools/bird_box.py --style custom --port 8090

`--only` takes a file of plate filenames, one per line ("cyanistes-caeruleus.webp"),
which is the review queue; with none given the whole style is the queue. Edits are
saved as you make them, so there is nothing to confirm and Ctrl-C is the way out.
"""

from __future__ import annotations

import argparse
import functools
import io
import json
import logging
import os
import re
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from PIL import Image

from fugleramme.names import BIRDS, artwork_in
from fugleramme.render import collage, sizes
from fugleramme.render.page import trim
from fugleramme.render.paper import PAD, paper_texture, process_sprite
from fugleramme.render.sizes import GEOMETRY, geometry_of

log = logging.getLogger(__name__)

REPO = Path(__file__).resolve().parents[1]
ARTWORK = REPO / "assets" / "artwork"

HOST = "127.0.0.1"  # a workstation GUI that writes to the tree: never off this machine
DEFAULT_PORT = 8081  # 8080 is the kiosk's

HTML = "text/html; charset=utf-8"
JSON = "application/json"
PNG = "image/png"
TEXT = "text/plain"

# The company the bird keeps in the preview: tightly boxed plates, goldcrest to heron.
COMPANIONS = (
    "regulus-regulus.webp",
    "pyrrhula-pyrrhula.webp",
    "emberiza-citrinella.webp",
    "turdus-merula.webp",
    "garrulus-glandarius.webp",
    "pica-pica.webp",
    "strix-aluco.webp",
    "buteo-buteo.webp",
    "corvus-corax.webp",
    "ardea-cinerea.webp",
)
FULL = (0.0, 0.0, 1.0, 1.0)  # the whole plate: the neutral box, ratio 1.0

CHECK_SIZE = (760, 520)  # the preview page, scaled into the column by the browser

Box = tuple[float, float, float, float]

_VARIANT = re.compile(r"-\d+$")


@functools.lru_cache(maxsize=8)
def _art(path: Path) -> Image.Image:
    """The trimmed cut-out a box is measured against. Small cache: the three
    references are re-read on every size check, the plates are not."""
    return trim(path)


@functools.cache
def _size(path: Path) -> tuple[int, int]:
    return _art(path).size


def _species(path: Path) -> str:
    """The plate's species key, which is what `sizes.mass_of` is keyed on."""
    return _VARIANT.sub("", path.stem)


def _ratio(box: Box, size: tuple[int, int]) -> float:
    """`sizes.span_ratio`'s arithmetic for a box being dragged rather than the one
    on disk. The saved boxes go through `span_ratio` itself."""
    width, height = size
    span = max((box[2] - box[0]) * width, (box[3] - box[1]) * height)
    return max(width, height) / span if span > 0 else 1.0


def _parse(text: str) -> Box | None:
    """A box from "x0,y0,x1,y1", or None when it is not four ordered fractions."""
    parts = text.split(",")
    if len(parts) != 4:
        return None
    try:
        x0, y0, x1, y1 = (float(part) for part in parts)
    except ValueError:
        return None
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        return None
    return (x0, y0, x1, y1)


def saved_box(style: Path, name: str) -> Box:
    """The box on record, or the whole plate. A box drawn on a crop that has since
    moved is not shown - it points somewhere else now, so it is worth no more than
    a fresh start."""
    plate = style / BIRDS / name
    found = geometry_of(plate)
    return found.box if found is not None and found.cut == _size(plate) else FULL


def save_box(style: Path, name: str, box: Box) -> None:
    """Write one key, rewritten whole through a temp file so a crash never leaves
    half a record. Re-read every time: this is the only writer, but a tool that
    holds the file in memory would undo an edit made beside it."""
    path = style / GEOMETRY
    listed = json.loads(path.read_text()) if path.exists() else {}
    listed[f"{BIRDS}/{name}"] = {"box": list(box), "cut": list(_size(style / BIRDS / name))}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(listed, indent=1, sort_keys=True) + "\n")
    os.replace(tmp, path)
    # Every edit saves itself, so the terminal is the only record of what changed.
    print(f"  {name}  {' '.join(f'{value:.4f}' for value in box)}")


def _png(img: Image.Image) -> bytes:
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


@functools.lru_cache(maxsize=16)
def plate_png(style: Path, name: str) -> bytes:
    """The plate on the frame's own paper, at its own pixel count.

    Drawn the way the page draws it: the halo is scan paper, opaque and off-tone,
    and only looks like part of the sheet once it has been retoned and feathered
    onto one. Exactly the cut-out's pixels and no others - the box is normalised
    to them, so a pad or an inset here would shift every box by its width. The
    feather bleeds off the edges instead, which is where it goes on the page too.
    """
    art = _art(style / BIRDS / name)
    canvas = paper_texture(*art.size)
    origin = (-PAD, -PAD)
    processed = process_sprite(art, origin)
    canvas.paste(processed, origin, processed)
    return _png(canvas)


def check_png(style: Path, name: str, box: Box) -> bytes:
    """The plate on a page with a few birds of known size, drawn the way the frame
    draws it.

    A real collage, packer and all, because placement is half of whether a size
    looks right - a bird reads against the birds it is nestled into, not against a
    ruler. The box under review is read off disk like every other, so the page
    commits before it asks for this.
    """
    company = [file for file in COMPANIONS if file != name]  # never twice on one page
    paths = [style / BIRDS / name, *(style / BIRDS / file for file in company)]
    entries: list[tuple[str, Path | None]] = [(_species(path), path) for path in paths]
    # Both caches key on the species and the page, not on the box that is changing.
    sizes._boxes.clear()
    collage._layouts.clear()
    page = collage.render_collage(entries, resolution=CHECK_SIZE, show_names=False)
    return _png(page)


def named(birds: Path, only: Path) -> list[Path]:
    """The plates a list names, by filename or by path - `git ls-files` gives one,
    a hand-written list the other. `-` reads the list from stdin."""
    text = sys.stdin.read() if str(only) == "-" else only.read_text()
    names = dict.fromkeys(Path(line.strip()).name for line in text.splitlines() if line.strip())
    unknown = [name for name in names if not (birds / name).exists()]
    if unknown:
        sys.exit(f"not in {birds.parent.name}: {', '.join(unknown)}")
    return [birds / name for name in names]


def queue(style: Path, only: Path | None, unboxed: bool) -> list[Path]:
    """The plates to work through: the listed ones, or the whole style, narrowed
    to those with no usable box if asked - which includes one gone stale."""
    birds = style / BIRDS
    plates = artwork_in(birds) if only is None else named(birds, only)
    return [path for path in plates if saved_box(style, path.name) == FULL] if unboxed else plates


def _route(path: str) -> tuple[str, str]:
    parts = urlparse(path).path.strip("/").split("/", 1)
    return parts[0], unquote(parts[1]) if len(parts) > 1 else ""


def listing(style: Path, plates: list[Path]) -> list[dict[str, object]]:
    """The queue and the box each plate is wearing. No ratio: it needs the alpha
    bbox, which is eight seconds of decoding over a whole style, and the page has
    the plate's own pixel count in front of it anyway."""
    return [{"name": path.name, "box": list(saved_box(style, path.name))} for path in plates]


def make_handler(style: Path, plates: list[Path]) -> type[BaseHTTPRequestHandler]:
    queued = {path.name for path in plates}  # also stops a request naming a path of its own

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            log.debug("%s %s", self.address_string(), fmt % args)

        def _send(self, status: int, body: bytes, content_type: str):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _json(self, payload: object):
            self._send(200, json.dumps(payload).encode(), JSON)

        def _state(self, name: str, box: Box):
            self._json({"name": name, "box": list(box), "ratio": _ratio(box, _size(_plate(name)))})

        def do_GET(self):
            route, name = _route(self.path)
            if route == "":
                self._send(200, PAGE.encode(), HTML)
                return
            if route == "plates":
                self._json(listing(style, plates))
                return
            if name not in queued:
                self._send(404, b"not found", TEXT)
                return
            if route == "box":
                self._state(name, saved_box(style, name))
                return
            if route == "plate":
                self._send(200, plate_png(style, name), PNG)
                return
            if route != "check":
                self._send(404, b"not found", TEXT)
                return
            box = _parse(parse_qs(urlparse(self.path).query).get("box", [""])[0])
            if box is None:
                self._send(400, b"box must be x0,y0,x1,y1 in 0..1", TEXT)
                return
            self._send(200, check_png(style, name, box), PNG)

        def do_PUT(self):
            route, name = _route(self.path)
            if route != "box" or name not in queued:
                self._send(404, b"not found", TEXT)
                return
            length = int(self.headers.get("Content-Length", 0))
            box = _parse(self.rfile.read(length).decode())
            if box is None:
                self._send(400, b"box must be x0,y0,x1,y1 in 0..1", TEXT)
                return
            save_box(style, name, box)
            self._state(name, box)

    def _plate(name: str) -> Path:
        return style / BIRDS / name

    return Handler


def serve(style: Path, plates: list[Path], port: int = DEFAULT_PORT) -> None:
    """Run the review GUI until Ctrl-C, with a browser pointed at it."""
    httpd = ThreadingHTTPServer((HOST, port), make_handler(style, plates))
    url = f"http://{HOST}:{port}/"
    print(f"{len(plates)} plates in {style.name}  -  {url}")
    webbrowser.open(url)  # the socket is listening already, so a race here only queues
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--style", default="classic", help="style folder to review")
    parser.add_argument(
        "--only", type=Path, help="file listing the plates to review, one per line; - for stdin"
    )
    parser.add_argument(
        "--missing", action="store_true", help="only the plates that have no box yet"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, help=f"port to serve on (default {DEFAULT_PORT})"
    )
    args = parser.parse_args()

    style = ARTWORK / args.style
    if not (style / BIRDS).is_dir():
        sys.exit(f"no such style: {style}")
    plates = queue(style, args.only, args.missing)
    if not plates:
        sys.exit(f"no plates to review in {style.name}")
    serve(style, plates, args.port)


PAGE = """<!doctype html>
<html lang="en">
<meta charset="utf-8">
<title>Bird boxes</title>
<style>
  :root { color-scheme: light }
  body { margin: 0; height: 100vh; overflow: hidden; background: #e6e4df; color: #222;
         font: 15px/1.5 system-ui, -apple-system, sans-serif }
  /* One screenful: the plate scales to whatever room is left rather than the page growing. */
  main { display: grid; grid-template-columns: minmax(0, 1fr) 440px; gap: 24px; padding: 20px;
         height: 100vh; box-sizing: border-box }
  .plate { display: flex; align-items: center; justify-content: center; min-height: 0 }
  aside { min-height: 0; overflow-y: auto }
  h1 { font-size: 20px; margin: 0 }
  h2 { font-size: 14px; margin: 24px 0 6px; text-transform: none }
  #frame { position: relative; display: inline-block; line-height: 0; background: #fcfbf9;
           box-shadow: 0 0 0 1px #c9c5bc; max-height: 100% }
  #art { display: block; max-height: calc(100vh - 40px); max-width: 100%;
         width: auto; height: auto }
  #box { position: absolute; border: 2px solid #c0392b; box-sizing: border-box; cursor: move }
  .h { position: absolute; width: 13px; height: 13px; margin: -7px 0 0 -7px;
       background: #fff; border: 1px solid #c0392b; border-radius: 2px }
  .h.on { background: #c0392b }
  .h[data-h="nw"] { left: 0; top: 0; cursor: nwse-resize }
  .h[data-h="n"]  { left: 50%; top: 0; cursor: ns-resize }
  .h[data-h="ne"] { left: 100%; top: 0; cursor: nesw-resize }
  .h[data-h="w"]  { left: 0; top: 50%; cursor: ew-resize }
  .h[data-h="e"]  { left: 100%; top: 50%; cursor: ew-resize }
  .h[data-h="sw"] { left: 0; top: 100%; cursor: nesw-resize }
  .h[data-h="s"]  { left: 50%; top: 100%; cursor: ns-resize }
  .h[data-h="se"] { left: 100%; top: 100%; cursor: nwse-resize }
  .bar { display: flex; align-items: baseline; gap: 12px; margin-bottom: 12px }
  .bar b { font-size: 20px }
  .count { margin-left: auto; color: #6b6b6b; font-variant-numeric: tabular-nums }
  .state { margin-left: auto; display: inline-flex; align-items: center; gap: 6px;
           font-size: 13px; color: #6b6b6b; font-variant-numeric: tabular-nums }
  .state::before { content: ''; width: 7px; height: 7px; border-radius: 50%;
                   background: #5d9c61 }
  .state[data-s="unsaved"] { color: #96702a }
  .state[data-s="unsaved"]::before { background: #d3a03c }
  .state[data-s="saving"]::before { background: #9a968c }
  #preview { position: relative; line-height: 0 }
  #check { width: 100%; height: auto; display: block; box-shadow: 0 0 0 1px #c9c5bc;
           transition: opacity .15s }
  #preview.busy #check { opacity: .35 }
  #spin { position: absolute; inset: 0; display: none; align-items: center;
          justify-content: center }
  #preview.busy #spin { display: flex }
  #spin i { width: 22px; height: 22px; border: 2px solid #b9b4a9; border-top-color: #555;
            border-radius: 50%; animation: turn .7s linear infinite }
  @keyframes turn { to { transform: rotate(360deg) } }
  .acts { display: flex; gap: 8px; margin: 14px 0 18px }
  .acts svg { width: 14px; height: 14px; stroke: #555; stroke-width: 1.6; fill: none;
              stroke-linecap: round; stroke-linejoin: round }
  .acts button { display: inline-flex; align-items: center; gap: 7px; cursor: pointer;
                 background: #fff; border: 1px solid #c9c5bc; border-radius: 5px;
                 padding: 6px 10px; font: inherit; font-size: 13px; color: #222 }
  .acts button:hover { background: #f4f2ee }
  .acts button:active { background: #ebe8e2 }
  .acts kbd { background: #f0eee9; border-color: #d8d4cc; color: #6b6b6b }
  .above { margin-top: 18px }
  .help { color: #444 }
  .help ul { margin: 0; padding-left: 18px }
  .help li { margin: 4px 0 }
  kbd { background: #fff; border: 1px solid #bbb; border-bottom-width: 2px; border-radius: 3px;
        padding: 0 4px; font: 12px/1.4 ui-monospace, monospace }
</style>
<main>
  <section class="plate">
    <div id="frame">
      <img id="art" alt="">
      <div id="box" data-h="box">
        <i class="h" data-h="nw"></i><i class="h" data-h="n"></i><i class="h" data-h="ne"></i>
        <i class="h" data-h="w"></i><i class="h" data-h="e"></i>
        <i class="h" data-h="sw"></i><i class="h" data-h="s"></i><i class="h" data-h="se"></i>
      </div>
    </div>
  </section>
  <aside>
    <div class="bar">
      <h1 id="name">loading</h1>
      <span class="count"><span id="at">0</span> / <span id="count">0</span>
        &middot; <span id="done">0</span> done</span>
    </div>
    <div class="bar">ratio <b id="ratio">1.00</b>
      <span class="state" id="state" data-s="saved">saved</span></div>
    <h2 class="above">Preview</h2>
    <div id="preview"><img id="check" alt=""><span id="spin"><i></i></span></div>
    <div class="acts">
      <button data-do="prev">
        <svg viewBox="0 0 16 16"><path d="M10 3 5 8l5 5"/></svg>Previous <kbd>p</kbd></button>
      <button data-do="next">
        <svg viewBox="0 0 16 16"><path d="M6 3l5 5-5 5"/></svg>Next <kbd>n</kbd></button>
      <button data-do="revert">
        <svg viewBox="0 0 16 16"><path d="M5.5 3 2.5 6l3 3"/><path d="M2.5 6h6a4 4 0 0 1 0 8H6"/>
        </svg>Revert <kbd>u</kbd></button>
    </div>
    <section class="help">
      <h2>What to box</h2>
      <ul>
        <li>One whole bird, bill to tail and feet.</li>
        <li>Nothing else: no perch, branch, ground or second bird.</li>
        <li>Two birds or more on a plate? Choose the biggest one.</li>
        <li>Only the longest side matters. Slop on the short side is fine.</li>
      </ul>
      <h2>Controls</h2>
      <ul>
        <li><kbd>h</kbd><kbd>j</kbd><kbd>k</kbd><kbd>l</kbd> nudge by one pixel,
          <kbd>H</kbd><kbd>J</kbd><kbd>K</kbd><kbd>L</kbd> by ten. Arrows work too.</li>
        <li><kbd>tab</kbd> walks round the handles, <kbd>shift tab</kbd> back,
          <kbd>0</kbd> select the whole box.</li>
        <li>Or drag: the box to move it, a handle to resize.</li>
        <li>Next plate <kbd>n</kbd> <kbd>w</kbd> <kbd>]</kbd>,
          back one <kbd>p</kbd> <kbd>b</kbd> <kbd>[</kbd>.</li>
        <li>Saves as you go. <kbd>u</kbd> undoes back to how the plate opened.</li>
      </ul>
    </section>
  </aside>
</main>
<script>
const MIN = 0.02;  // never let an edge cross its opposite
const STEPS = {
  h: [-1, 0], j: [0, 1], k: [0, -1], l: [1, 0],
  H: [-1, 0], J: [0, 1], K: [0, -1], L: [1, 0],
  ArrowLeft: [-1, 0], ArrowDown: [0, 1], ArrowUp: [0, -1], ArrowRight: [1, 0],
};
// Tab order: round the box, not the order they are declared in.
const HANDLES = ['box', 'nw', 'n', 'ne', 'e', 'se', 's', 'sw', 'w'];
const art = document.getElementById('art');
const frame = document.getElementById('frame');
const boxEl = document.getElementById('box');
const checkEl = document.getElementById('check');
const previewEl = document.getElementById('preview');
const stateEl = document.getElementById('state');

// Nothing here has a save button, so the state says so as it happens.
function state(name, text) {
  stateEl.dataset.s = name;
  stateEl.textContent = text;
}

let plates = [];
let at = 0;
let box = [0, 0, 1, 1];
let picked = 'box';
let drag = null;
let checkTimer = 0;
let saveTimer = 0;
let opened = [0, 0, 1, 1];  // the box this plate was wearing on arrival, for revert

// Kept in the browser so a closed tab does not lose the sitting.
const DONE = 'bird-boxes-done';
const done = new Set(JSON.parse(localStorage.getItem(DONE) || '[]'));

function mark(name) {
  done.add(name);
  localStorage.setItem(DONE, JSON.stringify([...done]));
  document.getElementById('done').textContent = done.size;
}

function clamp(value, low, high) { return Math.min(Math.max(value, low), high); }

function moved(start, handle, dx, dy) {
  let [x0, y0, x1, y1] = start;
  if (handle === 'box') {
    const sx = clamp(dx, -x0, 1 - x1), sy = clamp(dy, -y0, 1 - y1);
    return [x0 + sx, y0 + sy, x1 + sx, y1 + sy];
  }
  if (handle.includes('w')) x0 = clamp(x0 + dx, 0, x1 - MIN);
  if (handle.includes('e')) x1 = clamp(x1 + dx, x0 + MIN, 1);
  if (handle.includes('n')) y0 = clamp(y0 + dy, 0, y1 - MIN);
  if (handle.includes('s')) y1 = clamp(y1 + dy, y0 + MIN, 1);
  return [x0, y0, x1, y1];
}

function ratio() {
  const w = art.naturalWidth || 1, h = art.naturalHeight || 1;
  const span = Math.max((box[2] - box[0]) * w, (box[3] - box[1]) * h);
  return span > 0 ? Math.max(w, h) / span : 1;
}

function draw() {
  boxEl.style.left = (box[0] * 100) + '%';
  boxEl.style.top = (box[1] * 100) + '%';
  boxEl.style.width = ((box[2] - box[0]) * 100) + '%';
  boxEl.style.height = ((box[3] - box[1]) * 100) + '%';
  document.getElementById('ratio').textContent = ratio().toFixed(2);
  for (const handle of boxEl.children) handle.classList.toggle('on', handle.dataset.h === picked);
}

// A full collage render, about a second, so it waits for the drag to end.
function check() {
  clearTimeout(checkTimer);
  previewEl.classList.add('busy');  // on straight away: the wait starts with the drag
  checkTimer = setTimeout(() => {
    checkEl.src = '/check/' + encodeURIComponent(plates[at].name) + '?box=' + box.join(',');
  }, 150);
}

function commit() {
  clearTimeout(saveTimer);
  saveTimer = 0;
  plates[at].box = box.slice();
  mark(plates[at].name);
  state('saving', 'saving');
  // The preview renders from the saved record, so it waits for the write to land.
  fetch('/box/' + encodeURIComponent(plates[at].name), {method: 'PUT', body: box.join(',')})
    .then(() => state('saved', 'saved ' + new Date().toLocaleTimeString()))
    .then(check);
}

function show(index) {
  if (saveTimer) commit();  // flush the pending nudge onto the plate it belongs to
  at = (index + plates.length) % plates.length;
  box = plates[at].box.slice();
  opened = box.slice();
  state('saved', 'saved');
  art.src = '/plate/' + encodeURIComponent(plates[at].name);
  document.getElementById('name').textContent = plates[at].name;
  document.getElementById('at').textContent = at + 1;
  draw();
  check();
}

const ACTIONS = {
  next() { mark(plates[at].name); show(at + 1); },
  prev() { show(at - 1); },
  revert() { box = opened.slice(); draw(); commit(); },
};

for (const button of document.querySelectorAll('.acts button')) {
  // Blur, or the button keeps the focus and swallows the keys it is a twin of.
  button.addEventListener('click', () => { ACTIONS[button.dataset.do](); button.blur(); });
}

frame.addEventListener('pointerdown', event => {
  const handle = event.target.dataset.h;
  if (!handle) return;
  picked = handle;
  drag = {handle, start: box.slice(), x: event.clientX, y: event.clientY,
          rect: frame.getBoundingClientRect()};
  frame.setPointerCapture(event.pointerId);
  event.preventDefault();
  draw();
});

frame.addEventListener('pointermove', event => {
  if (!drag) return;
  box = moved(drag.start, drag.handle,
              (event.clientX - drag.x) / drag.rect.width,
              (event.clientY - drag.y) / drag.rect.height);
  state('unsaved', 'unsaved');
  draw();
});

frame.addEventListener('pointerup', event => {
  if (!drag) return;
  drag = null;
  frame.releasePointerCapture(event.pointerId);
  commit();
});

addEventListener('keydown', event => {
  // Three pairs, since none is obviously right. Not J/K: a stray shift while
  // nudging would jump the plate and mark it done.
  const action = {
    w: 'next', ']': 'next', n: 'next',
    b: 'prev', '[': 'prev', p: 'prev',
    u: 'revert', U: 'revert',
  }[event.key];
  if (action) { ACTIONS[action](); return; }
  if (event.key === 'Tab') {
    event.preventDefault();
    const step = event.shiftKey ? HANDLES.length - 1 : 1;
    picked = HANDLES[(HANDLES.indexOf(picked) + step) % HANDLES.length];
    draw();
    return;
  }
  if (event.key === '0') { picked = 'box'; draw(); return; }
  const step = STEPS[event.key];
  if (!step) return;
  event.preventDefault();
  const px = event.shiftKey ? 10 : 1;
  box = moved(box, picked, step[0] * px / (art.naturalWidth || 1),
              step[1] * px / (art.naturalHeight || 1));
  state('unsaved', 'unsaved');
  draw();
  clearTimeout(saveTimer);
  saveTimer = setTimeout(commit, 300);
});

art.addEventListener('load', draw);  // the ratio needs the plate's own pixel count
for (const event of ['load', 'error']) {
  checkEl.addEventListener(event, () => previewEl.classList.remove('busy'));
}

fetch('/plates').then(response => response.json()).then(listed => {
  plates = listed;
  document.getElementById('count').textContent = plates.length;
  document.getElementById('done').textContent = done.size;
  show(0);
});
</script>
</html>
"""

if __name__ == "__main__":
    main()
