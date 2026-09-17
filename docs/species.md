# Species coverage

Every bird BirdNET can detect, and whether the frame has art for it. Missing
yours? Open a [Missing bird](https://github.com/arnegiacomo/fugleramme/issues/new/choose)
issue or [cut one yourself](adding-artwork.md) - more plates of a listed bird
are welcome too.

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
#species-status { font-size: .75rem; color: var(--md-default-fg-color--light); }
</style>

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

<p id="species-status" aria-live="polite">Loading.</p>

<table>
  <thead><tr><th>Scientific name</th><th>Common name</th><th>Art</th><th>Records</th></tr></thead>
  <tbody id="species-rows"></tbody>
</table>

Records are sightings in the last ten years from [GBIF](https://www.gbif.org),
which for birds is largely eBird re-published, and the regions are
[GADM](https://gadm.org)'s.

<script src="../assets/fuse.min.js"></script>
<script src="../assets/species.js"></script>
