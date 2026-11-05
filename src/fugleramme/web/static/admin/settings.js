// The Display and Frame form: which of its fields apply follows what else the
// form holds, and an edit re-renders the preview.
import {cfg, dim, reveal, signedOut} from "./common.js";
import {form, glass, holdRender, queueRender, shadeMat} from "./preview.js";

const lock = form.web_lock;

// Fields the chosen mode ignores.
const lookback = document.getElementById("lookback");
const limit = document.getElementById("limit");
const ranking = document.getElementById("ranking");
const layout = document.getElementById("layout");
const windowed = () => !form.mode.value || cfg.windowedModes.includes(form.mode.value);
function syncMode() {
  const on = windowed();
  dim(lookback, on);
  dim(limit, on);
  dim(layout, on);
  // Nothing to rank while every bird the window heard is already on the page.
  const capped = form.limit_mode.value === "some";
  form.species_limit.disabled = !(on && capped);  // after dim(limit)
  dim(ranking, on && capped);
}

// Without a panel there is nothing to turn or lock to.
function syncPanel() {
  reveal(document.getElementById("panel-size"), form.external_panel.checked);
  dim(form.rotation.closest("label"), Boolean(glass()));
  dim(document.getElementById("web-lock"), Boolean(glass()));
  const hint = document.getElementById("lock-hint");
  hint.setAttribute("aria-label", glass() ? hint.dataset.on : hint.dataset.off);
}

// Locked to the panel, the web view has no shape of its own to pick.
const shape = document.getElementById("web-shape");
const syncShape = () => dim(shape, !(glass() && lock.checked));

// With names off there is no label to set a language, typeface or size for.
const showNames = form.show_names;
const nameKey = form.name_key;
const keyCap = document.getElementById("key-cap");
const faceNote = document.getElementById("face-note");
function syncNames() {
  document.querySelectorAll("#names .sub").forEach((l) => dim(l, showNames.checked));
  dim(document.getElementById("name-key"), showNames.checked && windowed());  // collage only
  const all = form.limit_mode.value === "all";
  const over = all || Number(form.species_limit.value) > cfg.keyLimit;
  keyCap.hidden = !(nameKey.checked && !nameKey.disabled && over);
  const said = cfg.faceNotes[form.label_font.value];
  const note = said[form.primary_language.value] || said[form.secondary_language.value] || "";
  faceNote.hidden = !note;
  faceNote.setAttribute("aria-label", note);
}

// The size each Resolution renders at, as settings.web_size works it out from the form.
const sizeOf = (height) => {
  const locked = glass() && lock.checked;
  const [a, b] = locked ? glass() : form.web_aspect.value.split(":").map(Number);
  const turned = locked ? form.rotation.value % 180 : form.web_portrait.checked;
  const wide = Math.round(height * a / b);
  return turned ? [height, wide] : [wide, height];
};
function syncSizes() {
  for (const o of form.web_resolution.options) o.textContent = `${o.value} (${sizeOf(cfg.webHeights[o.value]).join("×")})`;
}

const margin = form.margin;
const one = document.getElementById("margin-one");
const uniform = document.getElementById("margin-uniform");
const edgeLock = form.margin_lock;
const edgeBox = document.getElementById("margin-edges");
const edges = [...edgeBox.querySelectorAll("input")];  // the glass's top, right, bottom, left
const SIDES = ["Top", "Right", "Bottom", "Left"];
// Only the panel's page has edges of its own.
const unlocked = () => Boolean(glass()) && !edgeLock.checked;
const turns = () => form.rotation.value / 90;  // counter-clockwise: the glass's left comes to the top

function hungMargins() {
  if (!unlocked()) return SIDES.map(() => Number(margin.value));
  return SIDES.map((_, i) => Number(edges[(i - turns() + 4) % 4].value));
}

// The edge sliders are named for the glass, so they are relabelled and
// reordered to read as the frame hangs.
function syncMargin() {
  const open = unlocked();
  dim(uniform, Boolean(glass()));
  reveal(edgeBox, open);
  // Unlocked, only a web view off the panel uses the one margin.
  reveal(one, !open || !lock.checked);
  one.querySelector(".caption").textContent = open ? "Web view" : "All edges";
  edges.forEach((edge, i) => {
    const side = (i + turns()) % 4;
    edge.closest("label").style.order = side;
    edge.closest("label").querySelector(".caption").textContent = SIDES[side];
  });
}

function sync() {
  syncMode();
  syncPanel();
  syncShape();
  syncNames();
  syncSizes();
  syncMargin();
}

// A slider renders on release, or a keyboard step. A changed margin also shows
// in black on the panel and the web view, for holding a mat up to it, debounced
// like the preview: a keyboard step is a change of its own.
let matTimer = null;
form.addEventListener("change", (e) => {
  if (e.target.type === "range") queueRender();
  if (!e.target.name.startsWith("margin")) return;
  clearTimeout(matTimer);
  matTimer = setTimeout(async () => {
    try {
      signedOut(await fetch("/mat-test", {method: "POST", body: new URLSearchParams(new FormData(form))}));
    } catch (e) {}  // the preview still shows the margin
  }, 500);
});

// Capture, so a mode change settles which fields still submit before the shared
// dirty check reads them - a round trip back to the saved mode is not a change.
form.addEventListener("input", (e) => {
  if (e.target.type === "range") {
    e.target.closest("label").querySelector("small").textContent = e.target.value + "%";
    // Locked, the edges follow, so unlocking starts them at the one margin.
    if (e.target === margin && edgeLock.checked) edges.forEach((edge) => { edge.value = margin.value; });
    shadeMat(hungMargins());  // on the page already on screen, until the render catches up
  }
  sync();
  if (e.target.type === "range") return holdRender();  // a drag renders on release only
  // A panel's page does not change with the web view's own settings, so with a
  // panel those need no render.
  if (glass() && e.target.closest("#web-view")) return;
  queueRender();
}, true);

sync();
