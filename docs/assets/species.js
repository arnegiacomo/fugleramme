// The species page's search: fuzzy over the list species.json carries, so a
// visitor can check a bird by any of its names, with or without a frame.
//
// The region filter asks GBIF, not eBird: it needs no key, answers
// cross-origin, and for birds is largely eBird re-published, so nothing
// regional is vendored here. Rows are matched by name, and species.json
// already carries the current spelling beside the label's, so a reclassified
// bird is found under either and no alias map is shipped twice.
(function () {
  const box = document.getElementById("species-search");
  if (!box) return;
  const arts = document.getElementById("species-art"); // the with / without / all toggle
  const only = () => (arts.querySelector("input:checked") || { value: "all" }).value;
  const status = document.getElementById("species-status");
  const body = document.getElementById("species-rows");
  const country = document.getElementById("species-country");
  const sub = document.getElementById("species-sub");
  const vagrants = document.getElementById("species-vagrants");
  const clear = document.getElementById("species-clear");
  const LIMIT = 500;
  const FILES = "https://github.com/arnegiacomo/fugleramme/blob/main/assets/artwork/";
  const GBIF = "https://api.gbif.org/v1";
  const REGULAR = 25; // records in a decade. Below it a bird is a vagrant, not a neighbour

  const cell = (...content) => {
    const td = document.createElement("td");
    td.append(...content);
    return td;
  };
  const link = (href, text) => Object.assign(document.createElement("a"), { href, textContent: text });
  const art = (row) => {
    if (!row.plates.length) return ["no art"];
    const links = row.plates.flatMap((file, i) => [i ? ", " : "", link(FILES + file, `plate ${i + 1}`)]);
    return row.detectable === false ? [...links, " (BirdNET cannot detect it)"] : links;
  };
  const name = (row) => {
    if (!row.label) return [row.name];
    return [row.name, document.createElement("br"), Object.assign(document.createElement("small"), { textContent: `BirdNET label: ${row.label}` })];
  };
  const render = (rows, seen) => {
    body.replaceChildren(
      ...rows.slice(0, LIMIT).map((row) => {
        const tr = document.createElement("tr");
        tr.append(cell(...name(row)), cell(row.common), cell(...art(row)), cell(seen ? seen.get(row).toLocaleString() : ""));
        return tr;
      }),
    );
    status.textContent = rows.length > LIMIT ? `Showing ${LIMIT} of ${rows.length} matches` : `${rows.length} ${rows.length === 1 ? "match" : "matches"}`;
  };

  const key = (text) => text.trim().toLowerCase().replace(/ /g, "-");
  const iso3 = new Map();
  const json = (path, params = "") =>
    fetch(`${GBIF}/${path}?${params}`).then((response) => {
      if (!response.ok) throw new Error(`GBIF answered ${response.status}`);
      return response.json();
    });

  // A facet caps at 1200 values, so a whole country is paged and a full last
  // page means the tail is missing. Each region is asked once and kept, so
  // going back to a filter already looked at costs GBIF nothing.
  const answers = new Map();
  const recorded = async () => {
    const where = sub.value ? { gadmGid: sub.value } : { country: country.value };
    const floor = vagrants.checked ? 1 : REGULAR;
    const region = `${sub.value || country.value}|${vagrants.checked}`;
    if (answers.has(region)) return answers.get(region);
    const year = new Date().getFullYear();
    const counts = new Map();
    let full = false;
    for (let offset = 0; offset < 3600; offset += 1200) {
      const params = new URLSearchParams({
        taxonKey: 212, // Aves
        facet: "scientificName",
        facetLimit: 1200,
        facetOffset: offset,
        facetMincount: floor,
        limit: 0,
        occurrenceStatus: "PRESENT",
        basisOfRecord: "HUMAN_OBSERVATION", // not an 1890s museum skin, and not a machine
        hasCoordinate: true,
        year: `${year - 9},${year}`,
        ...where,
      });
      const page = await json("occurrence/search", params);
      const values = page.facets?.[0]?.counts || [];
      values.forEach(({ name: scientific, count }) => {
        if (/ x |\u00d7/.test(scientific)) return; // a hybrid, which no label names
        const binomial = /^[A-Z][a-z]+ [a-z-]+/.exec(scientific); // GBIF appends the author
        if (binomial) counts.set(binomial[0], (counts.get(binomial[0]) || 0) + count);
      });
      full = values.length === 1200;
      if (!full) break;
    }
    const answer = { counts, full };
    answers.set(region, answer);
    return answer;
  };

  // GADM's own subdivisions, so a country is split the way it splits itself.
  // Clicking through the list fires one of these each time, and a slow answer
  // must not fill the select for a country the reader has already left.
  const splits = new Map();
  const subdivisions = () => {
    sub.replaceChildren(new Option("Anywhere in the country", ""));
    const picked = country.value;
    if (!picked) return;
    const known = splits.get(picked);
    const asked = known
      ? Promise.resolve(known)
      : json(`geocode/gadm/${iso3.get(picked)}/subdivisions`, "limit=400").then((rows) => {
          const level1 = rows.filter((row) => row.gadmLevel === 1).sort((a, b) => a.name.localeCompare(b.name));
          splits.set(picked, level1);
          return level1;
        });
    asked
      .then((level1) => {
        if (picked !== country.value) return;
        sub.append(...level1.map((row) => new Option(row.name, row.id)));
      })
      .catch(() => {});
  };

  fetch("../species.json")
    .then((response) => response.json())
    .then((all) => {
      const fuse = new Fuse(all, { keys: ["name", "common", "label"], threshold: 0.3, ignoreLocation: true, minMatchCharLength: 2 });
      const byKey = new Map();
      all.forEach((row) => {
        byKey.set(key(row.name), row);
        (row.label || "").split(", ").filter(Boolean).forEach((old) => byKey.set(key(old), row));
      });
      const withArt = all.filter((row) => row.plates.length).length;
      let seen = null; // row -> records where the reader is, or null for everywhere
      let summary = "";
      let asked = 0; // a slow answer to an older region must not land on a newer one

      const update = () => {
        const query = box.value.trim();
        const wanted = only();
        let rows = query ? fuse.search(query).map((hit) => hit.item) : all;
        if (wanted === "with") rows = rows.filter((row) => row.plates.length);
        if (wanted === "without") rows = rows.filter((row) => !row.plates.length);
        if (seen) rows = rows.filter((row) => seen.has(row)); // seen is built in record order
        render(rows, seen);
        if (!query && wanted === "all" && !seen)
          status.textContent =
            `${withArt} of ${all.length} species have art.` +
            (rows.length > LIMIT ? ` Showing the first ${LIMIT}.` : "");
        if (seen && !query) status.textContent = summary;
      };

      const locate = () => {
        seen = null;
        const question = ++asked; // bumped before the early return, so Clear also strands a reply
        if (!country.value) return update();
        status.textContent = "Asking GBIF what has been seen there…";
        recorded()
          .then(({ counts, full }) => {
            if (question !== asked) return;
            const here = new Map();
            counts.forEach((count, scientific) => {
              const row = byKey.get(key(scientific));
              // A bird v2.4 has no label for is present but unhearable, so it is
              // not one of the species the frame could draw from a detection.
              if (row && row.detectable !== false) here.set(row, (here.get(row) || 0) + count);
            });
            // Most heard first, once: a Map keeps its order, so the table is
            // sorted by inserting in it rather than on every keystroke.
            seen = new Map([...here].sort((a, b) => b[1] - a[1]));
            const where = (sub.selectedIndex > 0 ? `${sub.selectedOptions[0].text}, ` : "") + country.selectedOptions[0].text;
            const covered = [...seen.keys()].filter((row) => row.plates.length).length;
            summary =
              `${where}: ${covered} of the ${seen.size} species BirdNET can name here have art.` +
              (full ? " GBIF's facet limit leaves the rarest out." : "");
            update();
          })
          .catch((error) => {
            if (question !== asked) return;
            update(); // the table cannot keep showing a region the page just lost
            status.textContent = `GBIF could not be reached (${error.message}), so the whole list is shown.`;
          });
      };

      let soon;
      const settle = () => {
        clearTimeout(soon);
        soon = setTimeout(locate, 250);
      };

      box.addEventListener("input", update);
      arts.addEventListener("change", update);
      clear.addEventListener("click", () => {
        box.value = "";
        arts.querySelector("input[value=all]").checked = true;
        vagrants.checked = false;
        country.value = "";
        subdivisions();
        locate();
      });
      country.addEventListener("change", () => {
        subdivisions();
        settle();
      });
      [sub, vagrants].forEach((control) => control.addEventListener("change", settle));
      update();

      json("enumeration/country")
        .then((rows) => {
          rows.forEach((row) => iso3.set(row.iso2, row.iso3));
          country.append(...rows.map((row) => new Option(row.title, row.iso2)).sort((a, b) => a.text.localeCompare(b.text)));
        })
        .catch(() => {});
    })
    .catch(() => {
      status.textContent = "The species list could not be loaded.";
    });
})();
