// The species page's search: fuzzy over the list species.json carries, so a
// visitor can check a bird by any of its names, with or without a frame.
//
// The region filter asks GBIF, not eBird: no key, and it answers cross-origin.
// species.json carries each row's old spelling, so the join needs no alias map.
(function () {
  const box = document.getElementById("species-search");
  if (!box) return;
  const arts = document.getElementById("species-art");
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
  // Returns the table's line; the caller owns what goes in front of it.
  const render = (rows, seen) => {
    body.replaceChildren(
      ...rows.slice(0, LIMIT).map((row) => {
        const tr = document.createElement("tr");
        tr.append(cell(...name(row)), cell(row.common), cell(...art(row)), cell(seen ? seen.get(row).toLocaleString() : ""));
        return tr;
      }),
    );
    return rows.length > LIMIT ? `Showing ${LIMIT} of ${rows.length} matches.` : `${rows.length} ${rows.length === 1 ? "match" : "matches"}.`;
  };

  const key = (text) => text.trim().toLowerCase().replace(/ /g, "-");
  const iso3 = new Map();
  const json = (path, params = "") =>
    fetch(`${GBIF}/${path}?${params}`).then((response) => {
      if (!response.ok) throw new Error(`GBIF answered ${response.status}`);
      return response.json();
    });

  // A facet caps at 1200 values: page it, and a full last page means a missing tail.
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

  // A slow answer must not fill the select for a country already left.
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
      let seen = null; // row -> records here, or null for everywhere
      let summary = "";
      let asked = 0; // a slow answer must not land on a newer region

      const update = () => {
        const query = box.value.trim();
        const wanted = only();
        let rows = query ? fuse.search(query).map((hit) => hit.item) : all;
        if (wanted === "with") rows = rows.filter((row) => row.plates.length);
        if (wanted === "without") rows = rows.filter((row) => !row.plates.length);
        if (seen) rows = rows.filter((row) => seen.has(row)); // seen is built in record order
        const counted = render(rows, seen);
        if (seen && !query) status.textContent = `${summary} ${counted}`;
        else if (!query && wanted === "all") status.textContent = `${withArt} of ${all.length} species have art. ${counted}`;
        else status.textContent = counted;
      };

      const locate = () => {
        seen = null;
        const question = ++asked; // bumped before the early return, so Clear strands a reply too
        if (!country.value) return update();
        status.textContent = "Asking GBIF what has been seen there…";
        recorded()
          .then(({ counts, full }) => {
            if (question !== asked) return;
            const here = new Map();
            counts.forEach((count, scientific) => {
              const row = byKey.get(key(scientific));
              // A bird v2.4 has no label for is present but unhearable.
              if (row && row.detectable !== false) here.set(row, (here.get(row) || 0) + count);
            });
            // Sorted once here: a Map keeps its order, so keystrokes never re-sort.
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

      // Fetched on the first reach for a filter, so merely reading asks GBIF nothing.
      let countries;
      const listCountries = () => {
        countries ||= json("enumeration/country")
          .then((rows) => {
            rows.forEach((row) => iso3.set(row.iso2, row.iso3));
            country.append(...rows.map((row) => new Option(row.title, row.iso2)).sort((a, b) => a.text.localeCompare(b.text)));
          })
          .catch(() => {});
      };
      const filters = document.getElementById("species-filters");
      ["pointerenter", "focusin"].forEach((event) => filters.addEventListener(event, listCountries, { once: true }));
    })
    .catch(() => {
      status.textContent = "The species list could not be loaded.";
    });
})();
