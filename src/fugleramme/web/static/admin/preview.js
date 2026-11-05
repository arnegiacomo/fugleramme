// The preview beside the Display and Frame tabs, and the species list under it,
// both of the page the form is holding rather than the saved one.
import {cfg, linkSpecies, serialize, signedOut} from "./common.js";

export const form = document.querySelector("form.settings");
const preview = document.getElementById("preview");
const shot = document.getElementById("shot");
const mat = document.getElementById("mat");
const caption = document.querySelector(".rendering");
const captionHTML = caption.innerHTML;

// Once the preview has scrolled out of sight, as it does above the form on a
// phone, a thumbnail of it stands in at the corner, and a tap shows it whole.
const thumb = document.getElementById("thumb");
const full = document.getElementById("full");
let inSight = true;
// Also once a render lands: a save's reload puts the page back mid-form, out of sight before there was an image.
const syncThumb = () => { thumb.hidden = inSight || !shot.getAttribute("src"); };
new IntersectionObserver(([entry]) => {
  inSight = entry.isIntersecting;
  syncThumb();
}).observe(preview);
thumb.addEventListener("click", () => full.showModal());
full.addEventListener("click", () => full.close());

// The panel the page is laid out for: an Inky, else the external one at its size while it is ticked.
export const glass = () => (cfg.detected ? cfg.panel : form.external_panel.checked ? cfg.panelSizes[form.external_panel_size.value] : null);

let shown = null, seq = 0, timer = null;
let page = null;  // the kiosk's token: new birds move the preview too
export const queueRender = () => {
  clearTimeout(timer);  // debounced: a render is expensive on the Pi
  timer = setTimeout(loadPreview, 500);
};
export const holdRender = () => clearTimeout(timer);

function loadPreview() {
  mat.hidden = true;  // the band only stands in until the render starts
  const query = serialize(form);
  if (query === shown) return;
  const id = ++seq;
  // The panel's page where there is one, else the web view's own shape.
  const [w, h] = glass() || form.web_aspect.value.split(":");
  const turned = glass() ? form.rotation.value % 180 : form.web_portrait.checked;
  // Turned now rather than when the render lands, so the box does not jump.
  preview.style.setProperty("--aspect", turned ? `${h} / ${w}` : `${w} / ${h}`);
  preview.classList.add("loading");
  thumb.classList.add("stale");
  caption.innerHTML = captionHTML;
  const next = new Image();  // decode off-screen, so the img is never stale or broken
  next.onload = () => {
    if (id !== seq) return;  // a later edit already superseded this render
    shown = query;
    shot.src = thumb.firstElementChild.src = full.firstElementChild.src = next.src;
    preview.classList.remove("loading");
    thumb.classList.remove("stale");
    syncThumb();
  };
  next.onerror = () => {
    if (id !== seq) return;
    caption.textContent = "Preview unavailable";
  };
  // The token busts the browser's in-page image cache, which ignores no-cache.
  next.src = "/preview.png?" + query + (page ? "&page=" + page : "");
  loadSpecies(query, id);
}

async function loadSpecies(query, id) {
  try {
    const answer = await fetch("/species?" + query, {cache: "no-store"});
    if (signedOut(answer)) return;
    const body = await answer.json();
    if (id !== seq) return;
    document.getElementById("count").textContent = body.count;
    document.getElementById("species").innerHTML = body.html;
    linkSpecies();
  } catch (e) {}  // the preview alone is worth showing
}

// Shade the band a mat would cover on the page already on screen, so the margin
// can be judged before the render catches up. `margins` are top, right, bottom
// and left as the frame hangs, in percent of the short side.
export function shadeMat(margins) {
  const box = preview.getBoundingClientRect();
  const short = Math.min(box.width, box.height);
  mat.style.borderWidth = margins.map((m) => short * m / 100 + "px").join(" ");
  mat.hidden = preview.classList.contains("loading");  // no page on screen to shade
}

export function start() {
  linkSpecies();
  loadPreview();
  (async function follow() {
    try {
      const state = await (await fetch("/state", {cache: "no-store"})).json();
      const moved = page !== null && state.token !== page;
      page = state.token;
      if (!moved) return;
      shown = null;  // the same form, a different page
      loadPreview();
    } catch (e) {  // a missed poll is caught by the next
    } finally {
      setTimeout(follow, 5000);
    }
  })();
}
