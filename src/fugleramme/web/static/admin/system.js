// The System tab: an update's progress, and the reboot.
import {cfg, keep, recall, signedOut} from "./common.js";
import {anyDirty} from "./forms.js";

// The install reloads the page as a new version, so the tab is what remembers
// the old one - long enough to say the update landed.
const was = recall("sessionStorage", "version");
const state = document.getElementById("state");
keep("sessionStorage", "version", cfg.version);
if (state && was && was !== cfg.version) state.textContent = "updated to v" + cfg.version;

// The check runs inside its own POST, so the spinner only has to outlive the
// navigation. Not with unsaved edits: the browser asks whether to leave, and
// staying would leave the spinner turning.
const check = document.querySelector("dd.update form.check");
check?.addEventListener("submit", () => {
  if (anyDirty()) return;
  check.insertAdjacentHTML("beforebegin", '<span class="spinner inline"></span>');
  check.querySelector("button").disabled = true;
});

// An install ends with systemd restarting us, so the poll rides out a dead
// server and reloads once one answers with the work done - or failed.
const bar = document.getElementById("bar");
if (bar) {
  const phase = document.getElementById("phase");
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

document.querySelector("form.reboot")?.addEventListener("submit", (e) => {
  if (!confirm("Are you sure you want to reboot?")) e.preventDefault();
});
