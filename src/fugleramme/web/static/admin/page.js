// The page around the sections: the nav, the tabs, the hints, the copy buttons
// and the theme.
import {birdnet, keep, recall, showLogos} from "./common.js";

const detectorLink = document.getElementById("birdnet");  // several stations are a list instead
if (detectorLink) detectorLink.href = birdnet + "/";
showLogos(document);

// Plain http has no clipboard API, so copy through a selected scratch textarea.
for (const button of document.querySelectorAll("button.copy")) {
  button.addEventListener("click", () => {
    const scratch = document.createElement("textarea");
    scratch.value = button.dataset.copy;
    document.body.append(scratch);
    scratch.select();
    document.execCommand("copy");
    scratch.remove();
    button.textContent = "Copied";
    setTimeout(() => { button.textContent = "Copy"; }, 1500);
  });
}

// Each tab and the pane it shows. Display and Frame are panes of one section.
export const tabs = [...document.querySelectorAll("nav.tabs button")]
  .map((tab) => ({tab, name: tab.dataset.tab, pane: document.getElementById("tab-" + tab.dataset.tab)}));
const settings = document.getElementById("settings");
export function showTab(name) {
  for (const {tab, pane, name: own} of tabs) {
    const on = own === name;
    tab.setAttribute("aria-selected", on);
    tab.tabIndex = on ? 0 : -1;  // the tab list is one stop; the arrows move within it
    pane.hidden = !on;
  }
  settings.hidden = !settings.contains(document.getElementById("tab-" + name));
  keep("localStorage", "tab", name);
}
for (const {tab, name} of tabs) tab.addEventListener("click", () => showTab(name));
document.querySelector("nav.tabs").addEventListener("keydown", (e) => {
  const step = {ArrowLeft: -1, ArrowRight: 1}[e.key];
  if (!step) return;
  const at = tabs.findIndex(({tab}) => tab === document.activeElement);
  const next = tabs[(at + step + tabs.length) % tabs.length];
  showTab(next.name);
  next.tab.focus();
});
// A remembered tab that no longer exists would hide every section at once.
const remembered = recall("localStorage", "tab");
showTab(tabs.some(({name}) => name === remembered) ? remembered : tabs[0].name);

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

const menu = document.getElementById("menu");
const closeMenu = () => menu.setAttribute("aria-expanded", "false");
menu.addEventListener("click", (e) => {
  e.stopPropagation();
  menu.setAttribute("aria-expanded", String(menu.getAttribute("aria-expanded") !== "true"));
});

// A click anywhere else, or Escape, closes an open hint and the menu.
const closeAll = () => { closeHint(); closeMenu(); };
document.addEventListener("click", closeAll);
document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });

// The theme, kept in this browser. base.html applies it before the page paints.
for (const radio of document.querySelectorAll("input[name=theme]")) {
  radio.checked = radio.value === (document.documentElement.dataset.theme || "");
  radio.addEventListener("change", () => {
    const theme = radio.value;
    if (theme) document.documentElement.dataset.theme = theme;
    else delete document.documentElement.dataset.theme;
    keep("localStorage", "theme", theme || null);
  });
}
