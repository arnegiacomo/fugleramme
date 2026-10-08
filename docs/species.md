# Species coverage

Every bird BirdNET can detect, and whether the frame has art for it. Missing
yours? Open a [Missing bird](https://github.com/arnegiacomo/fugleramme/issues/new/choose)
issue or [cut one yourself](adding-artwork.md) - more plates of a listed bird
are welcome too.

The map shows how much of each country's birdlife has art. Click one to list them.

<style>
#species-filters { display: flex; flex-direction: column; gap: .5rem; margin: 1.2rem 0; padding: .8rem; border: 1px solid var(--md-default-fg-color--lightest); border-radius: .2rem; background: var(--md-code-bg-color); }
#species-filters .row { display: flex; flex-wrap: wrap; gap: .5rem .8rem; align-items: center; }
#species-filters input[type="search"], #species-filters select { font: inherit; padding: .4rem .5rem; color: var(--md-default-fg-color); background: var(--md-default-bg-color); border: 1px solid var(--md-default-fg-color--lighter); border-radius: .2rem; }
#species-filters input[type="search"] { width: 100%; }
#species-filters select { flex: 1 1 12rem; min-width: 0; }
#species-filters .row > label { display: flex; gap: .3rem; align-items: center; margin: 0; font-size: .75rem; color: var(--md-default-fg-color--light); }
#species-art { position: relative; display: inline-flex; }
#species-art input { position: absolute; opacity: 0; pointer-events: none; }
#species-art label { margin: 0; padding: .3rem .6rem; font-size: .7rem; cursor: pointer; color: var(--md-default-fg-color--light); background: var(--md-default-bg-color); border: 1px solid var(--md-default-fg-color--lighter); border-left-width: 0; }
#species-art label:first-of-type { border-left-width: 1px; border-radius: .2rem 0 0 .2rem; }
#species-art label:last-of-type { border-radius: 0 .2rem .2rem 0; }
#species-art input:checked + label { color: var(--md-primary-bg-color); background: var(--md-primary-fg-color); border-color: var(--md-primary-fg-color); }
#species-art input:focus-visible + label { outline: 2px solid var(--md-accent-fg-color); outline-offset: -2px; }
#species-clear { margin-left: auto; font: inherit; font-size: .7rem; padding: .3rem .7rem; cursor: pointer; color: var(--md-typeset-a-color); background: var(--md-default-bg-color); border: 1px solid var(--md-default-fg-color--lighter); border-radius: .2rem; }
#species-clear:hover { color: var(--md-accent-fg-color); border-color: var(--md-accent-fg-color); }
#species-bar { display: flex; align-items: center; justify-content: space-between; gap: .5rem; margin: 1em 0; }
#species-status { margin: 0; font-size: .75rem; color: var(--md-default-fg-color--light); }
#species-sort { display: inline-flex; align-items: center; gap: .15rem; flex-shrink: 0; font-size: .75rem; color: var(--md-default-fg-color--light); }
#species-sort:has(select:disabled) { opacity: .5; }
#species-sort svg { width: 1.1em; height: 1.1em; fill: currentColor; }
#species-sort select { font: inherit; color: var(--md-default-fg-color); background: transparent; border: none; padding: .2rem 0; cursor: pointer; }
#species-sort select:disabled { cursor: default; }
#species-map { --bin-0: #86b6ef; --bin-1: #5598e7; --bin-2: #2a78d6; --bin-3: #1c5cab; --bin-4: #0d366b; --no-data: #e4e3df; position: relative; display: block; width: 100%; margin: 1.2rem 0 0; }
[data-md-color-scheme="slate"] #species-map { --bin-0: #1c5cab; --bin-1: #2a78d6; --bin-2: #5598e7; --bin-3: #86b6ef; --bin-4: #cde2fb; --no-data: #383835; }
#species-map-shapes svg { display: block; width: 100%; height: auto; }
#species-map-shapes [data-iso] { fill: var(--no-data); fill-rule: evenodd; stroke: var(--md-default-bg-color); stroke-width: .4px; vector-effect: non-scaling-stroke; }
#species-map-shapes [data-bin] { cursor: pointer; }
#species-map-shapes [data-bin="0"] { fill: var(--bin-0); }
#species-map-shapes [data-bin="1"] { fill: var(--bin-1); }
#species-map-shapes [data-bin="2"] { fill: var(--bin-2); }
#species-map-shapes [data-bin="3"] { fill: var(--bin-3); }
#species-map-shapes [data-bin="4"] { fill: var(--bin-4); }
#species-map-shapes .dot { stroke-width: 1px; }
#species-map-shapes .hover, #species-map-shapes .picked { stroke: var(--md-default-fg-color); stroke-width: 1.5px; }
#species-map-tip { position: absolute; z-index: 1; pointer-events: none; padding: .4rem .6rem; font-size: .7rem; line-height: 1.4; white-space: nowrap; color: var(--md-default-fg-color--light); background: var(--md-default-bg-color); border: 1px solid var(--md-default-fg-color--lightest); border-radius: .2rem; box-shadow: var(--md-shadow-z1); }
#species-map-tip strong { display: block; color: var(--md-default-fg-color); }
#species-map figcaption { max-width: none; margin: .5rem 0 0; font-size: .7rem; font-style: normal; color: var(--md-default-fg-color--light); }
#species-map ol { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .2rem .8rem; margin: 0; padding: 0; list-style: none; }
#species-map figcaption > div { display: flex; flex-wrap: wrap; justify-content: space-between; gap: .2rem 1rem; margin-top: .3rem; }
#species-map-by select { font: inherit; color: var(--md-default-fg-color); background: transparent; border: none; padding: 0; cursor: pointer; }
#species-map li { display: flex; align-items: center; gap: .3rem; margin: 0; }
#species-map li::before { content: ""; width: .8rem; height: .8rem; border-radius: 2px; background: var(--swatch); }
</style>

<figure id="species-map" hidden>
  <div id="species-map-shapes"></div>
  <div id="species-map-tip" hidden></div>
  <figcaption>
    <ol aria-label="Share with art">
      <li style="--swatch: var(--bin-0)">Under 20%</li>
      <li style="--swatch: var(--bin-1)">20-40%</li>
      <li style="--swatch: var(--bin-2)">40-60%</li>
      <li style="--swatch: var(--bin-3)">60-80%</li>
      <li style="--swatch: var(--bin-4)">80% or more</li>
      <li style="--swatch: var(--no-data)">No records</li>
    </ol>
    <div>
      <label id="species-map-by">Shaded by <select><option value="records">share of records</option><option value="species">share of species</option></select></label>
      <span id="species-map-date"></span>
    </div>
  </figcaption>
</figure>

<div id="species-filters">
  <input id="species-search" type="search" placeholder="Scientific or common name" autocomplete="off">
  <div class="row">
    <select id="species-country" aria-label="Country"><option value="">Any country</option></select>
    <select id="species-sub" aria-label="State or region"><option value="">Anywhere in the country</option></select>
  </div>
  <div class="row">
    <span id="species-art" role="radiogroup" aria-label="Artwork">
      <input type="radio" name="species-art" id="art-all" value="all" checked><label for="art-all">All</label>
      <input type="radio" name="species-art" id="art-with" value="with"><label for="art-with">With art</label>
      <input type="radio" name="species-art" id="art-without" value="without"><label for="art-without">Without art</label>
    </span>
    <label><input id="species-vagrants" type="checkbox"> Include vagrants</label>
    <button id="species-clear" type="button">Clear filters</button>
  </div>
</div>

<div id="species-bar">
  <p id="species-status" aria-live="polite">Loading.</p>
  <label id="species-sort">
    <svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 13h12v-2H3m0-5v2h18V6M3 18h6v-2H3v2Z"/></svg>
    <select id="species-order" aria-label="Sort" disabled><option value="name">A to Z</option><option value="records">Most common</option></select>
  </label>
</div>

<table>
  <thead><tr><th>Scientific name</th><th>Common name</th><th>Art</th><th>Records</th></tr></thead>
  <tbody id="species-rows"></tbody>
</table>

Records are sightings in the last ten years from [GBIF](https://www.gbif.org),
which for birds is largely eBird re-published, and the regions are
[GADM](https://gadm.org)'s. Pick a region to order the list by them, most common first.

<script src="../assets/fuse.min.js"></script>
<script src="../assets/species.js"></script>
