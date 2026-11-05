// The Detector tab: the connection test, the type's own fields, and the
// BirdWeather stations with their search.
import {reveal, showLogos, signedOut} from "./common.js";
import {isDirty} from "./forms.js";

const detectorForm = document.getElementById("detector");

// Tests the values in the form, not the saved ones, so a fix can be tried first.
const test = document.getElementById("test");
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
    // "names" is a working detector holding back one thing, and "partial"
    // stations BirdWeather has only some of, so they warn rather than fail.
    outcome.className = {ok: "ok", names: "warn", partial: "warn"}[result.state] || "bad";
    outcome.textContent = result.text;
    // The row is about the detector the frame reads from, so only a test of
    // the saved values speaks for it - edited ones may never be saved.
    if (!isDirty(detectorForm)) {
      row.innerHTML = result.status;
      showLogos(row);  // a station's line carries its own
    }
  } catch (e) {
    outcome.className = "bad";
    outcome.textContent = "the frame did not answer";
  }
  test.disabled = false;
});

// Each type's own fields: BirdNET-Go's address and password, BirdWeather's stations.
for (const kind of detectorForm.querySelectorAll("input[name=detector_kind]")) {
  kind.addEventListener("input", () => {  // before the form's own dirty check reads it
    for (const field of detectorForm.querySelectorAll("label[data-kind], div[data-kind]")) {
      reveal(field, field.dataset.kind === kind.value);
    }
  });
}

// A row per BirdWeather station. The last row's × empties it rather than leaving
// nothing to type into, and Add stops at the most the frame reads.
const stations = detectorForm.querySelector(".stations");
const add = stations.querySelector("button.add");
const most = Number(stations.dataset.most);
const rows = () => stations.querySelectorAll(".station");
const fields = () => [...stations.querySelectorAll(".station input")];
const sync = () => { add.hidden = rows().length >= most; };
const edited = () => {
  sync();
  stations.dispatchEvent(new Event("input", {bubbles: true}));  // for the form's dirty check
};
const append = (value) => {
  const fresh = rows()[0].cloneNode(true);
  fresh.querySelector("input").value = value;
  add.before(fresh);
  return fresh;
};
const drop = (row) => {
  if (rows().length > 1) row.remove();
  else row.querySelector("input").value = "";
};
stations.addEventListener("click", (e) => {
  if (e.target.matches("button.remove")) {
    drop(e.target.closest(".station"));
  } else if (e.target === add) {
    append("").querySelector("input").focus();
  } else {
    return;
  }
  edited();
});
sync();

// Find stations near a place, in a dialog: Photon suggests places as one
// types, fuzzily, and picking one lists the stations nearest it, each with an Add.
const near = stations.querySelector("dialog.near");
const field = near.querySelector("input");
const places = near.querySelector(".places");
const said = near.querySelector(".note");
const found = near.querySelector(".found");
stations.querySelector("button.find").addEventListener("click", () => near.showModal());
near.querySelector("button.close").addEventListener("click", () => near.close());
const tell = (text, tone = "") => {
  said.className = "note " + tone;
  said.textContent = text;
};
const cell = (tag, props) => Object.assign(document.createElement(tag), props);
// A row holds an ID or a station's page, which ends in it.
const holds = (id) => fields().some((field) => field.value.trim().replace(/\/+$/, "").split("/").pop() === id);
let listed = [];
const list = () => {
  const empty = fields().some((field) => !field.value.trim());
  const full = !empty && rows().length >= most;
  const lines = listed.map((station) => {
    const li = document.createElement("li");
    const action = holds(station.id)
      ? cell("em", {textContent: "added"})
      : cell("button", {type: "button", textContent: "Add", disabled: full, onclick: () => {
        const free = fields().find((field) => !field.value.trim());
        if (free) free.value = station.id;
        else append(station.id);
        edited();
      }});
    li.append(
      cell("div", {className: "name", textContent: station.name, title: station.name}),
      cell("div", {textContent: "#" + station.id}),
      cell("div", {textContent: (station.km < 1 ? "<1" : Math.round(station.km)) + " km"}),
      action,
    );
    return li;
  });
  if (full && !listed.every((station) => holds(station.id))) {
    lines.push(cell("li", {className: "full",
      textContent: `The frame reads at most ${most} stations: remove one to add another.`}));
  }
  found.replaceChildren(...lines);
};
stations.addEventListener("input", list);  // a row typed, added or removed
const pick = async (place) => {
  places.replaceChildren();
  field.value = place.label;
  listed = [];
  list();
  tell("searching…");
  try {
    const answer = await fetch(`/stations?lat=${place.lat}&lon=${place.lon}`);
    if (signedOut(answer)) return;
    const result = await answer.json();
    listed = result.stations;
    list();
    tell(result.text || `Stations nearest ${place.label}`, result.text ? "bad" : "");
  } catch (e) {
    tell("the frame did not answer", "bad");
  }
};
let typed = 0;  // an answer to older typing is dropped
let pause;
const suggest = async () => {
  const query = field.value.trim();
  const mine = ++typed;
  if (query.length < 3) {
    places.replaceChildren();
    return;
  }
  try {
    const answer = await fetch("https://photon.komoot.io/api/?limit=5&q=" + encodeURIComponent(query));
    const {features} = await answer.json();
    if (mine !== typed) return;
    tell(features.length ? "" : `no place called "${query}"`, "bad");
    if (!features.length) {
      places.replaceChildren();
      return;
    }
    places.replaceChildren(...features.map(({properties: p, geometry}) => {
      const label = [...new Set([p.name, p.city || p.county, p.state, p.country].filter(Boolean))]
        .join(", ");
      const [lon, lat] = geometry.coordinates;
      const li = document.createElement("li");
      li.append(cell("button", {type: "button", textContent: label,
        onclick: () => pick({label, lat, lon})}));
      return li;
    }), cell("li", {className: "credit", textContent: "Places © OpenStreetMap, via Photon"}));
  } catch (e) {
    tell("the place search did not answer", "bad");
  }
};
field.addEventListener("input", () => {
  clearTimeout(pause);
  pause = setTimeout(suggest, 300);  // a pause in typing, not every key
});
field.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  e.preventDefault();  // or the form saves
  places.querySelector("button")?.click();
});
