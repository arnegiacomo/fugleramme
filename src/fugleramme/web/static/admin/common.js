// What every section of the admin reads.

// Read from the page, not interpolated in: keeps the scripts static and cacheable.
export const cfg = JSON.parse(document.getElementById("config").textContent);

// A loopback detector is only loopback from the Pi, so a remote browser follows
// this page's own host on its port; anything else is linked as configured.
export const birdnet = cfg.birdnetPort
  ? location.protocol + "//" + location.hostname + ":" + cfg.birdnetPort
  : cfg.birdnetUrl;

// Each detector's own favicon: BirdNET-Go's off its repository at a release tag,
// so it shows whether or not one is running. Shown once loaded, so one that
// cannot load - a browser offline - leaves no gap and no broken image.
const LOGOS = {
  "birdnet-go": "https://cdn.jsdelivr.net/gh/tphakala/birdnet-go@20261014/frontend/static/favicon-32x32.png",
  birdweather: "https://app.birdweather.com/favicon-32x32.png",
};
export function showLogos(root) {
  for (const img of root.querySelectorAll("img.logo")) {
    img.addEventListener("load", () => { img.hidden = false; });
    img.src = LOGOS[img.dataset.kind];
  }
}

// Not queryType=species: BirdNET-Go shows only today's for that. A BirdWeather
// station's page has no search to link into.
export function linkSpecies() {
  if (cfg.kind === "birdweather") return;
  for (const a of document.querySelectorAll("#species a[data-species]")) {
    a.href = birdnet + "/ui/detections?search=" + encodeURIComponent(a.dataset.species);
  }
}

// A session can end while this page is open - it expires, or a sign-out elsewhere
// revoked it. The reload lands on the login page rather than leaving the page here
// showing yesterday's birds.
export const signedOut = (response) => {
  if (response.status !== 401) return false;
  location.reload();
  return true;
};

// Blocked site data makes every touch of browser storage throw, which at a
// module's top level would stop the whole admin. What it held is a convenience.
export function recall(storage, key) {
  try { return window[storage].getItem(key); } catch (e) { return null; }
}
export function keep(storage, key, value) {
  try {
    if (value === null) window[storage].removeItem(key);
    else window[storage].setItem(key, value);
  } catch (e) {}
}

export const serialize = (f) => new URLSearchParams(new FormData(f)).toString();

// Hidden, a block's fields post nothing, so the stored values stand.
export function reveal(el, on) {
  el.hidden = !on;
  el.querySelectorAll("input, select").forEach((c) => { c.disabled = !on; });
}

// A setting that does not apply goes dim and stops being submitted, so the saved
// value survives a trip through a state that has no use for it.
export function dim(el, on) {
  el.querySelectorAll("select, input").forEach((c) => { c.disabled = !on; });
  el.classList.toggle("off", !on);
}
