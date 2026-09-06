// Read from the page, not interpolated in: keeps this file static and cacheable.
const cfg = JSON.parse(document.getElementById("config").textContent);

// A loopback detector is only loopback from the Pi, so a remote browser follows
// this page's own host on its port; anything else is linked as configured.
document.getElementById("birdnet").href = cfg.birdnetPort
  ? location.protocol + "//" + location.hostname + ":" + cfg.birdnetPort + "/"
  : cfg.birdnetUrl;

// Every button posts and redirects, so a save reloads: the tab and the scroll
// position have to be carried across by hand.
let saving = false;
for (const f of document.querySelectorAll("form")) {
  f.addEventListener("submit", () => {
    saving = true;
    sessionStorage.setItem("scroll", String(window.scrollY));
  });
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

// A setting one tab cannot offer, pointing at the tab that fixes it: open that
// one first, then the href's fragment scrolls to the field itself.
for (const link of document.querySelectorAll("a[data-tab]")) {
  link.addEventListener("click", () => showTab(link.dataset.tab));
}

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

// Save stays disabled until a form differs from what the server served. An
// untouched password placeholder serializes the same both times, so it needs no
// case of its own. The action forms (Check, Install) are not settings and stay out.
const serialize = (f) => new URLSearchParams(new FormData(f)).toString();
const changed = new Map();
for (const f of document.querySelectorAll("form.settings, form.block")) {
  const button = f.querySelector("button[type=submit]");
  const served = serialize(f);
  const dirty = () => serialize(f) !== served;
  changed.set(f, dirty);
  f.addEventListener("input", () => { button.disabled = !dirty(); });
  button.disabled = true;
}

// Tests the values in the form, not the saved ones, so a fix can be tried first.
const test = document.getElementById("test");
if (test) {
  const detectorForm = document.getElementById("detector");
  const outcome = document.getElementById("test-result");
  const row = document.getElementById("detector-state");
  const creds = document.getElementById("credentials");
  test.addEventListener("click", async () => {
    test.disabled = true;
    outcome.className = "";
    outcome.textContent = "testing…";
    try {
      const body = new URLSearchParams(new FormData(detectorForm));
      const answer = await fetch("/detector", {method: "POST", body});
      const result = await answer.json();
      // "names" is a working detector holding back one thing, so it warns
      // rather than fails - but it is fixed in the same box as "auth".
      outcome.className = {ok: "ok", names: "warn"}[result.state] || "bad";
      outcome.textContent = result.text;
      if (result.state === "auth" || result.state === "names") creds.open = true;
      // The row is about the detector the frame reads from, so only a test of
      // the saved values speaks for it - edited ones may never be saved.
      if (!changed.get(detectorForm)()) row.innerHTML = result.status;
    } catch (e) {
      outcome.className = "bad";
      outcome.textContent = "the frame did not answer";
    }
    test.disabled = false;
  });
}

const preview = document.getElementById("preview");
const shot = document.getElementById("shot");
const caption = document.querySelector(".rendering");
const captionHTML = caption.innerHTML;
const form = document.querySelector("form.settings");
let shown = null, seq = 0, timer = null;

function loadPreview() {
  const query = serialize(form);
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
const collageOnly = [...document.querySelectorAll(".collage-only")];
function syncMode() {
  const mode = form.querySelector("input[name=mode]:checked");
  const on = !mode || cfg.windowedModes.includes(mode.value);
  for (const field of collageOnly) {
    field.querySelector("select").disabled = !on;
    field.classList.toggle("off", !on);
  }
}

// Capture, so a mode change settles which fields still submit before the shared
// dirty check reads them - a round trip back to the saved mode is not a change.
form.addEventListener("input", () => {
  syncMode();
  clearTimeout(timer);  // debounced: a render is expensive on the Pi
  timer = setTimeout(loadPreview, 500);
}, true);

// An untouched form is never dirty, so this only fires over edits the user
// would actually lose - a typed password among them.
window.addEventListener("beforeunload", (e) => {
  if (saving || ![...changed.values()].some((dirty) => dirty())) return;
  e.preventDefault();
  e.returnValue = "";
});

syncMode();
loadPreview();
if (scrolled !== null) window.scrollTo(0, Number(scrolled));
