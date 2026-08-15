// Read from the page, not interpolated in: keeps this file static and cacheable.
const cfg = JSON.parse(document.getElementById("config").textContent);

// Same host as this page, BirdNET-Go's own port - the bind host (0.0.0.0) is not reachable.
document.getElementById("birdnet").href =
  location.protocol + "//" + location.hostname + ":" + cfg.birdnetPort + "/";

// Every button posts and redirects, so a save reloads: the tab and the scroll
// position have to be carried across by hand.
for (const f of document.querySelectorAll("form")) {
  f.addEventListener("submit", () => sessionStorage.setItem("scroll", String(window.scrollY)));
}
const scrolled = sessionStorage.getItem("scroll");
sessionStorage.removeItem("scroll");

// The install reloads the page as a new version, so the tab is what remembers
// the old one - long enough to say the update landed.
const was = sessionStorage.getItem("version");
const state = document.getElementById("state");
sessionStorage.setItem("version", cfg.version);
if (state && was && was !== cfg.version) state.textContent = "updated to v" + cfg.version;

const tabs = document.querySelectorAll("nav.tabs button");
function showTab(name) {
  for (const tab of tabs) {
    const on = tab.dataset.tab === name;
    tab.setAttribute("aria-selected", on);
    document.getElementById("tab-" + tab.dataset.tab).hidden = !on;
  }
  localStorage.setItem("tab", name);
}
for (const tab of tabs) tab.addEventListener("click", () => showTab(tab.dataset.tab));
showTab(localStorage.getItem("tab") === "system" ? "system" : "settings");

// The check runs inside its own POST, so the spinner only has to outlive the navigation.
const check = document.querySelector("dd.update form.check");
if (check) {
  check.addEventListener("submit", () => {
    check.insertAdjacentHTML("beforebegin", '<span class="spinner inline"></span>');
    check.querySelector("button").disabled = true;
  });
}

// An install ends with systemd restarting us, so the poll rides out a dead
// server and reloads once one answers with the work done - or failed.
if (document.getElementById("bar")) {
  const phase = document.getElementById("phase");
  const bar = document.getElementById("bar");
  (function poll() {
    setTimeout(async () => {
      try {
        const state = await (await fetch("/update", {cache: "no-store"})).json();
        if (!state.updating) {
          location.reload();
          return;
        }
        if (state.phase) {
          phase.textContent = state.phase + (state.percent === null ? "" : " " + state.percent + "%");
        }
        if (state.percent === null) bar.removeAttribute("value");
        else bar.value = state.percent;
      } catch (e) {}
      poll();
    }, 1000);
  })();
}

const preview = document.getElementById("preview");
const shot = document.getElementById("shot");
const caption = document.querySelector(".rendering");
const captionHTML = caption.innerHTML;
const form = document.querySelector("form.settings");
const save = form.querySelector("button[type=submit]");
const serialize = () => new URLSearchParams(new FormData(form)).toString();
const saved = serialize();
const dirty = () => serialize() !== saved;
let saving = false, shown = null, seq = 0, timer = null;

function loadPreview() {
  const query = serialize();
  if (query === shown) return;
  const id = ++seq;
  preview.classList.add("loading");
  caption.innerHTML = captionHTML;
  const next = new Image();  // decode off-screen, so the img is never stale or broken
  next.onload = () => {
    if (id !== seq) return;  // a later edit already superseded this render
    shown = query;
    shot.src = next.src;
    preview.classList.remove("loading");
  };
  next.onerror = () => {
    if (id !== seq) return;
    caption.textContent = "Preview unavailable";
  };
  next.src = "/preview.png?" + query;
  loadSpecies(query, id);
}

// The list under the preview is of the page being previewed, not the saved one.
async function loadSpecies(query, id) {
  try {
    const body = await (await fetch("/species?" + query, {cache: "no-store"})).json();
    if (id !== seq) return;
    document.getElementById("count").textContent = body.count;
    document.getElementById("species").innerHTML = body.html;
  } catch (e) {}  // the preview alone is worth showing
}

// Settings the chosen mode ignores go dim and stop being submitted, so the
// saved value survives a trip through a mode that has no use for it.
const lookback = document.getElementById("lookback");
function syncMode() {
  const mode = form.querySelector("input[name=mode]:checked");
  const on = !mode || cfg.windowedModes.includes(mode.value);
  lookback.querySelector("select").disabled = !on;
  lookback.classList.toggle("off", !on);
}

form.addEventListener("input", () => {
  syncMode();
  save.disabled = !dirty();
  clearTimeout(timer);  // debounced: a render is expensive on the Pi
  timer = setTimeout(loadPreview, 500);
});
form.addEventListener("submit", () => { saving = true; });
window.addEventListener("beforeunload", (e) => {
  if (saving || !dirty()) return;
  e.preventDefault();
  e.returnValue = "";
});

syncMode();
save.disabled = true;
loadPreview();
if (scrolled !== null) window.scrollTo(0, Number(scrolled));
