# RxGap

A pharmacy closure impact explorer for Greater Boston.

Pick a licensed walk-in pharmacy, simulate it closing, and see which no-vehicle households lose a reasonable walk — and how much farther the next licensed store is.

## What it shows

The map shades H3 demand cells by whether a licensed storefront is within a 15-minute walk. Select a pharmacy and click **Simulate closure**. Coverage then shifts from today’s walkable cells to the households that lose that walk — newly lost cells turn coral. Changing walk pace or the minute threshold recolors the map.

Headline impact is household-weighted: how many no-vehicle households lose a walk under the threshold, and the typical extra walk for households whose modeled nearest pharmacy is that location. That is a nearest-store result, not a claim about where people actually shop.

## Who it's for

The main job is still “what happens if this store closes.” The same map is also a public picture of currently licensed walk-in pharmacies in Greater Boston, so other people can get something out of it without running a study.

**Neighbors.** You do not need a GIS background. Click around your area to see which licensed walk-in pharmacies are on the map, which ones the model treats as closest for nearby households, and what the extra walk looks like if a familiar CVS or Walgreens shuts. That is useful when a closure is already in the news, or when you are trying to understand how thin coverage is on your side of a municipal line. It is not a live “pharmacy near me” app: there is no GPS pin, no hours, and no “open now.” For a trip today, still check the store. For “what is licensed to operate around here, and what if it left,” this is the map.

**Journalists and researchers.** A nearest-pharmacy dot map cannot answer the operational question. RxGap can: which no-vehicle households lose a 15-minute walk if this storefront closes, how much farther the next licensed store is, and how that closure ranks against others. Sources and methods are documented so the numbers can be checked.

**Advocates and organizers.** Closures land unevenly. The tool is built around households without a car, which is the group most stuck with walking or transit. That is a way to talk about a specific store, a neighborhood, or a chain pullout without flattening the city into one average.

**City, public health, and planning staff.** Use it to sanity-check a rumor, a license change, or a proposed closure against walkable access — including Brookline, Somerville, Chelsea, and other places people actually walk to, not only the Census Boston/Cambridge line.

Anyone can also use it more lightly: search or click a store to read the address, see whether it is a public walk-in (some licensed sites are not), and notice clusters versus thin stretches. Treat that as a licensed-storefront atlas, not as medical advice or a substitute for calling the pharmacy.

## Study area

Demand and closable pharmacies cover every Massachusetts city and town that intersects the analysis window — Boston, Cambridge, Brookline, Somerville, Chelsea, Quincy, Newton, and their neighbors. Census city limits are not how people walk here, so abutting municipalities are first-class, not a buffer.

The walk graph uses that same window so routes are not cut at a municipal line.

## How it works

**Pharmacies.** Operating status comes from the Massachusetts Board of Registration in Pharmacy currently licensed *Retail Pharmacy* roster. NPPES taxonomy `3336C0003X` is type evidence (community/retail), not proof the store is open. Mail-order, long-term care, and other non-walk-in licenses can still appear on the map with a reason; only walk-in storefronts that snap to the network can be closed in the tool. Pins are geocoded Census batch → NPPES coordinates → Overture storefront match → OSM Nominatim. Nominatim refined 53 locations in the current build.

**Demand.** ACS 2023 5-year table B25044 (no-vehicle households, with margins of error) is allocated onto Overture buildings inside each block group, preferring residential buildings, then aggregated to [H3](https://h3geo.org/) resolution 9. The ACS block-group total is conserved. Block groups that only partly overlap the study window keep the inside share when that clipped-away mass is material (about 1.5% here); see `data/reports/buildings_demand.json`.

**Walking.** Routes use Overture transportation segments joined on `connector_id`. Shape coordinates measure length; they do not decide whether two segments connect. Distance is origin snap + graph path + destination snap. Limited-access trunks are omitted unless the name is a bridge or overpass (Longfellow and the BU Bridge are tagged trunk). Modeled walks are checked against geodesic length and OSRM’s public foot profile in `data/reports/validation.json`.

| Pace | Speed | Source |
| --- | --- | --- |
| Slow | 2.0 mph | MUTCD slower-walker design speed |
| Average | 3.0 mph *(default)* | Common FHWA pedestrian planning speed |
| Brisk | 4.0 mph | Brisk adult walk |

## Data sources

| Layer | Source |
| --- | --- |
| Currently licensed location | MA Board of Registration in Pharmacy, retail roster |
| Pharmacy type | NPPES taxonomy `3336C0003X` |
| Storefront pin fallback | Census batch geocoder, then NPPES, Overture places, OSM Nominatim |
| Buildings, places, walk network | [Overture Maps](https://overturemaps.org/) (release pinned in `pipeline/config.py`) |
| Households without a vehicle | ACS 2023 5-year B25044 |
| Municipal boundaries | Census TIGER/Line county subdivisions |

CMS Retail Pharmacy Access files are plan-level network adequacy. They are not a storefront directory and are not used to plot stores.

Build counts and checks are written to `data/reports/`.

## Run locally

Python 3.11+ and Node.js 20+ are enough to run the app against the committed data artifact.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt

cd web
npm install
npm test
npm run lint
npm run build
npm run dev
```

The UI is a Vite + React + MapLibre app. It reads `web/public/data/rxgap.json`.

GitHub Actions (`.github/workflows/ci.yml`) runs the Python tests, Vitest, oxlint, and the production build on every push.

### Rebuild the data

Re-run the pipeline when Board licenses, ACS, or the Overture release change.

```bash
python -m pipeline.build --skip-cms
python -m unittest discover -s tests
```

That extracts Overture layers for the analysis window, geocodes licensed pharmacies, builds the walk graph, checks a handful of walks against OSRM, allocates demand, computes nearest and second-nearest stores, and writes `web/public/data/rxgap.json`.

`--skip-cms` skips an optional CMS cross-check that is not required for the map.

## Deploy

[Vercel](https://vercel.com) can host the frontend. Root `vercel.json` builds `web/` and publishes `web/dist`. Commit `web/public/data/rxgap.json` so production does not need the Python pipeline. Once it is live, add `Live demo: <url>` at the top of this README and set the same URL as the GitHub repository homepage.

## Cuts

No transit, driving, delivery/mail-order, insurance networks, medication availability, hours, or opening-location optimization. The question is walkable access to a licensed storefront if one location closes.

## Limitations

- Nearest and second-nearest licensed walk-in stores are modeled; observed shopping trips are not.
- Board retail licenses are the operating-status filter. An active NPI is not treated as proof the storefront is open.
- Duplicate licenses for one storefront remain visible; only one identity is used for routing.
- ACS margins of error are kept at block-group and citywide level. They are not spread onto H3 cells.
- Households at the outer edge of the extract window may have a nearer pharmacy just outside it.

The pipeline refuses to finish if a known-closed storefront is marked active, if demand allocation drops households, or if the pedestrian graph fails continuity checks (including Boston–Cambridge crossings of the Charles). Walking-distance checks live in `data/reports/validation.json`.
