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
// Sign out is not one of those: unsaved edits are still there to be warned about.
for (const f of document.querySelectorAll("form:not(.signout)")) {
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
// A remembered tab that no longer exists would hide every section at once.
const names = [...tabs].map((tab) => tab.dataset.tab);
const remembered = localStorage.getItem("tab");
showTab(names.includes(remembered) ? remembered : names[0]);

// A setting one tab cannot offer, pointing at the tab that fixes it: open that
// one first, then the href's fragment scrolls to the field itself.
for (const link of document.querySelectorAll("a[data-tab]")) {
  link.addEventListener("click", () => showTab(link.dataset.tab));
}

// A hint is a span inside its <label>, so a touch has no hover to open the bubble
// with and the label passes the tap on to its select. Cancelling the click stops that.
let openHint = null;
function closeHint() {
  if (openHint) openHint.classList.remove("open");
  openHint = null;
}
for (const hint of document.querySelectorAll(".hint")) {
  hint.addEventListener("click", (e) => {
    e.preventDefault();
    e.stopPropagation();
    const opening = hint !== openHint;
    closeHint();
    if (opening) {
      hint.classList.add("open");
      openHint = hint;
    }
  });
}
document.addEventListener("click", closeHint);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeHint(); });

// The check runs inside its own POST, so the spinner only has to outlive the navigation.
const check = document.querySelector("dd.update form.check");
if (check) {
  check.addEventListener("submit", () => {
    check.insertAdjacentHTML("beforebegin", '<span class="spinner inline"></span>');
    check.querySelector("button").disabled = true;
  });
}

// A session can end while this page is open - it expires, or a sign-out elsewhere
// revoked it. The reload lands on the login page rather than leaving the page here
// showing yesterday's birds.
const signedOut = (response) => {
  if (response.status !== 401) return false;
  location.reload();
  return true;
};

// An install ends with systemd restarting us, so the poll rides out a dead
// server and reloads once one answers with the work done - or failed.
if (document.getElementById("bar")) {
  const phase = document.getElementById("phase");
  const bar = document.getElementById("bar");
  (function poll() {
    setTimeout(async () => {
      try {
        const answer = await fetch("/update", {cache: "no-store"});
        if (signedOut(answer)) return;
        const state = await answer.json();
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

// Tests the values in the form, not the saved ones, so a fix can be tried first.
const test = document.getElementById("test");
if (test) {
  const detectorForm = document.getElementById("detector");
  const outcome = document.getElementById("test-result");
  const row = document.getElementById("detector-state");
  test.addEventListener("click", async () => {
    test.disabled = true;
    outcome.className = "";
    outcome.textContent = "testing…";
    try {
      const body = new URLSearchParams(new FormData(detectorForm));
      const answer = await fetch("/detector", {method: "POST", body});
      if (signedOut(answer)) return;
      const result = await answer.json();
      // "names" is a working detector holding back one thing, so it warns
      // rather than fails.
      outcome.className = {ok: "ok", names: "warn"}[result.state] || "bad";
      outcome.textContent = result.text;
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

// A field standing in for a stored password empties on focus, so what is typed is
// a whole password rather than something appended to the bullets. Untouched, it
// fills back in - and having never fired an input event, it is not a change either.
for (const field of document.querySelectorAll("input[type=password]")) {
  if (field.value !== cfg.passwordSet) continue;  // nothing stored, nothing to stand in for
  let kept = true;  // false once anything is typed: emptying the field then clears the password
  field.addEventListener("input", () => { kept = false; });
  field.addEventListener("focus", () => { if (kept) field.value = ""; });
  field.addEventListener("blur", () => {
    if (kept && !field.value) field.value = cfg.passwordSet;
  });
}

// How hard the admin password would be to guess, in the rough terms a person can
// act on: how many characters, out of how big an alphabet. Shown while typing
// only - the stored password never reaches the page, and the placeholder standing
// in for it would score as something it is not.
const password = document.querySelector("input[name=admin_password]");
const strength = document.getElementById("strength");
if (password && strength) {
  const [bar, caption] = [strength.querySelector("span"), strength.querySelector("small")];
  const CLASSES = [[/[a-z]/, 26], [/[A-Z]/, 26], [/[0-9]/, 10], [/[^a-zA-Z0-9]/, 32]];
  // Generous: counting the alphabet cannot tell a passphrase from a dictionary
  // word, so the bands sit high enough that a guessable one does not read as safe.
  const FULL = 80;  // the "strong" threshold, so a strong password reads as a full bar
  const RATING = [
    [36, "weak", "guessable"],
    [60, "fair", "fine on a home network"],
    [FULL, "good", "holds up if the frame is exposed"],
    [Infinity, "strong", "hard to guess anywhere"],
  ];
  password.addEventListener("input", () => {
    const typed = password.value;
    strength.hidden = !typed;
    if (!typed) {
      strength.className = "strength";  // nothing of the last rating left behind
      caption.textContent = "";
      return;
    }
    const alphabet = CLASSES.reduce((n, [cls, size]) => n + (cls.test(typed) ? size : 0), 0);
    const bits = typed.length * Math.log2(alphabet);
    const [, rating, caveat] = RATING.find(([ceiling]) => bits < ceiling);
    strength.className = "strength " + rating;
    bar.style.width = Math.min(100, (bits / FULL) * 100) + "%";
    caption.textContent = rating + " · " + caveat;
  });
}

const preview = document.getElementById("preview");
const shot = document.getElementById("shot");
const mat = document.getElementById("mat");
const caption = document.querySelector(".rendering");
const captionHTML = caption.innerHTML;
const form = document.querySelector("form.settings");
let shown = null, seq = 0, timer = null;
const queueRender = () => {
  clearTimeout(timer);  // debounced: a render is expensive on the Pi
  timer = setTimeout(loadPreview, 500);
};

function loadPreview() {
  mat.hidden = true;  // the band only stands in until the render starts
  const query = serialize(form);
  if (query === shown) return;
  const id = ++seq;
  const [w, h] = cfg.panel;
  // Turned now rather than when the render lands, so the box does not jump.
  preview.style.setProperty("--aspect", form.rotation.value % 180 ? `${h} / ${w}` : `${w} / ${h}`);
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
    const answer = await fetch("/species?" + query, {cache: "no-store"});
    if (signedOut(answer)) return;
    const body = await answer.json();
    if (id !== seq) return;
    document.getElementById("count").textContent = body.count;
    document.getElementById("species").innerHTML = body.html;
  } catch (e) {}  // the preview alone is worth showing
}

// Shade the mat band on the page already on screen, so the margin can be judged
// before the render catches up.
const margin = form.querySelector("input[name=margin]");
const readout = document.getElementById("margin-value");
margin.addEventListener("input", () => {
  readout.textContent = margin.value + "%";
  const box = preview.getBoundingClientRect();
  mat.style.borderWidth = Math.min(box.width, box.height) * margin.value / 100 + "px";
  mat.hidden = preview.classList.contains("loading");  // no page on screen to shade
});
margin.addEventListener("change", queueRender);  // on release, or a keyboard step

// Settings the chosen mode ignores go dim and stop being submitted, so the
// saved value survives a trip through a mode that has no use for it.
const lookback = document.getElementById("lookback");
const limit = document.getElementById("limit");
const ranking = document.getElementById("ranking");
const layout = document.getElementById("layout");
function dim(el, on) {
  el.querySelectorAll("select, input").forEach((c) => { c.disabled = !on; });
  el.classList.toggle("off", !on);
}
function syncMode() {
  const mode = form.querySelector("input[name=mode]:checked");
  const on = !mode || cfg.windowedModes.includes(mode.value);
  dim(lookback, on);
  dim(limit, on);
  dim(layout, on);
  // Nothing to rank while every bird the window heard is already on the page.
  const capped = form.querySelector("input[name=limit_mode]:checked")?.value === "some";
  form.querySelector("input[name=species_limit]").disabled = !(on && capped);  // after dim(limit)
  dim(ranking, on && capped);
}

// Capture, so a mode change settles which fields still submit before the shared
// dirty check reads them - a round trip back to the saved mode is not a change.
form.addEventListener("input", (e) => {
  syncMode();
  if (e.target === margin) return clearTimeout(timer);  // a drag renders on release only
  queueRender();
}, true);

syncMode();

// Save stays disabled until a form differs from what the server served. An
// untouched password placeholder serializes the same both times, so it needs no
// case of its own. The action forms (Check, Install) are not settings and stay out.
// Snapshot after syncMode - dimmed fields are already out of the form data.
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

// An untouched form is never dirty, so this only fires over edits the user
// would actually lose - a typed password among them.
window.addEventListener("beforeunload", (e) => {
  if (saving || ![...changed.values()].some((dirty) => dirty())) return;
  e.preventDefault();
  e.returnValue = "";
});

loadPreview();
if (scrolled !== null) window.scrollTo(0, Number(scrolled));
