// What every settings form shares: one save bar, shown once any of them differs
// from what the server served, which saves every changed form or drops them all.
import {cfg, keep, recall, serialize} from "./common.js";
import {showTab, tabs} from "./page.js";

// A save or a discard reloads the page, so the scroll position is carried
// across by hand; page.js remembers the tab.
let leaving = false;
const scrolled = recall("sessionStorage", "scroll");
keep("sessionStorage", "scroll", null);
export function restoreScroll() {
  if (scrolled !== null) window.scrollTo(0, Number(scrolled));
}
const keepScroll = () => keep("sessionStorage", "scroll", String(window.scrollY));
function leave(url) {
  leaving = true;
  keepScroll();
  location.assign(url);
}
// An action (Check, Install, Reboot) posts and redirects too; sign out lands on
// the login page instead.
for (const f of document.querySelectorAll("form.inline:not(.signout)")) f.addEventListener("submit", keepScroll);

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

// The settings forms, in the order they are saved: the access form last, since a
// new admin password ends this session and nothing posted after it would be let in.
const forms = [...document.querySelectorAll("form.settings, form.block")]
  .sort((a, b) => a.matches(".access") - b.matches(".access"));
const served = new Map();
export const isDirty = (form) => serialize(form) !== served.get(form);
export const anyDirty = () => forms.some(isDirty);

// What a pane holds of the settings forms, as a form would post it, so each tab
// can say whether it has changes: Display and Frame are one form, System two.
const posted = (pane) => [...pane.querySelectorAll("input[name], select[name]")]
  .filter((el) => served.has(el.form) && !el.disabled && (!/^(checkbox|radio)$/.test(el.type) || el.checked))
  .map((el) => el.name + "=" + el.value)
  .join("&");
const servedPanes = new Map();

const bar = document.getElementById("savebar");
const said = bar.querySelector(".said");
const save = document.getElementById("save");
const discard = document.getElementById("discard");
let saving = false;
function sync() {
  if (saving) return;
  bar.hidden = !anyDirty();
  said.textContent = "Unsaved changes";
  said.className = "said";
  for (const {tab, pane} of tabs) tab.classList.toggle("dirty", posted(pane) !== servedPanes.get(pane));
}

// Each changed form posts as it would have on its own, in turn, and the page
// reloads once they all have. A refused detector save redirects to a page that
// says so, which is where the reload goes instead.
async function saveAll() {
  // A focused password placeholder is empty until it blurs and fills back in;
  // saved like that, it would clear the password.
  document.activeElement?.blur();
  sync();
  const dirty = forms.filter(isDirty);
  if (!dirty.length) return;
  // The browser's own checks, which a fetch skips: open the tab with the first
  // field that fails them, so its message has somewhere to show.
  const invalid = dirty.flatMap((form) => [...form.querySelectorAll(":invalid")])[0];
  if (invalid) {
    showTab(invalid.closest("[role=tabpanel]").id.slice("tab-".length));
    invalid.reportValidity();
    return;
  }
  saving = save.disabled = discard.disabled = true;
  said.textContent = "Saving…";
  let next = "/admin";
  try {
    for (const form of dirty) {
      const answer = await fetch("/admin", {method: "POST", body: new URLSearchParams(new FormData(form))});
      if (answer.status === 401) break;  // signed out, or a new password just ended the session
      if (!answer.ok) throw new Error(answer.status);
      const landed = new URL(answer.url);
      if (landed.searchParams.has("refused")) next = landed.pathname + landed.search;
    }
  } catch (e) {
    saving = save.disabled = discard.disabled = false;
    said.textContent = "Not saved. The frame did not answer.";
    said.className = "said bad";
    return;
  }
  leave(next);
}
save.addEventListener("click", saveAll);
discard.addEventListener("click", () => leave("/admin"));
// Enter in a field is a Save of everything. Not left to the browser: a form with
// several fields and no submit button does not submit on Enter at all.
for (const form of forms) {
  form.addEventListener("submit", (e) => e.preventDefault());
  form.addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.defaultPrevented || e.target.closest("dialog")) return;
    if (!e.target.matches("input[type=text], input[type=password], input[type=number]")) return;
    e.preventDefault();
    saveAll();
  });
}

// Snapshots each form as served.
export function track() {
  for (const form of forms) served.set(form, serialize(form));
  for (const {pane} of tabs) servedPanes.set(pane, posted(pane));
  document.addEventListener("input", sync);
  sync();
}

// An untouched form is never dirty, so this only fires over edits the user
// would actually lose - a typed password among them.
window.addEventListener("beforeunload", (e) => {
  if (leaving || !anyDirty()) return;
  e.preventDefault();
  e.returnValue = "";
});
