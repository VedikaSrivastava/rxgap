# RxGap

A pharmacy closure impact explorer for Greater Boston.

**Live demo:** [https://rxgap.vercel.app/](https://rxgap.vercel.app/)

Pick a licensed walk-in pharmacy, set a **max walk**, simulate it closing, and see which no-vehicle households lose that walk — and how much farther the next licensed store is.

## What it shows

The map shades H3 demand cells by whether a licensed storefront is within the max walk (default 15 minutes at a documented walking-speed assumption). Select a pharmacy and click **Simulate closure**. Newly lost cells turn coral. Changing max walk or the speed assumption recolors the map; demand-cell geometry does not change.

Headline impact is household-weighted: how many no-vehicle households lose a walk under the threshold, and the typical extra walk for households whose modeled nearest pharmacy is that location.

## Who it's for

Neighbors, journalists, advocates, and planning staff who need “what happens if this store closes” for walkable access — not a live “pharmacy near me” app.

## Study area

For this analysis, RxGap defines its Greater Boston study area as **22 complete municipalities**: Boston, Cambridge, Somerville, Brookline, Newton, Watertown, Belmont, Arlington, Medford, Malden, Everett, Chelsea, Revere, Winthrop, Lynn, Quincy, Milton, Braintree, Dedham, Needham, Waltham, and Weymouth.

Demand and closable pharmacies exist only inside that municipal union. A **3 km routing envelope** beyond those boundaries (buffered in EPSG:26986) supplies network continuity and context pharmacies so routes are not cut at the study edge. Pins in the envelope but outside the study union are not ranked as closures.

## How it works

**Pharmacies.** MA Board currently licensed *Retail Pharmacy* roster; NPPES taxonomy `3336C0003X` is type evidence, not operating status. Only walk-in storefronts that snap to the network and lie in the study union can be closed in the tool.

**Demand.** ACS 2023 5-year B25044 (no-vehicle households) allocated onto Overture buildings inside each block group, then aggregated to [H3](https://h3geo.org/) resolution 9. No demand is allocated in the 3 km buffer.

**Walking.** Overture transportation segments joined on `connector_id`. Distance = origin snap + graph path + destination snap. The UI’s primary control is **max walk** in minutes; network meters convert with a documented walking-speed assumption (default 3.0 mph / Standard). Slower (2 mph) and Faster (4 mph) are available under Assumptions for sensitivity. Sample walks are checked against geodesic length and an external foot-routing reference in `data/reports/validation.json` — those checks are diagnostics, not the production distance model.

| Assumption | Speed | Source |
| --- | --- | --- |
| Slower | 2.0 mph | MUTCD slower-walker design speed |
| Standard | 3.0 mph *(default)* | Common FHWA pedestrian planning speed |
| Faster | 4.0 mph | Brisk adult walk |

## Data sources

| Layer | Source |
| --- | --- |
| Currently licensed location | MA Board of Registration in Pharmacy, retail roster |
| Pharmacy type | NPPES taxonomy `3336C0003X` |
| Storefront pin fallback | Census batch geocoder, then NPPES, Overture places, OSM Nominatim |
| Buildings, places, walk network | [Overture Maps](https://overturemaps.org/) (release pinned in `pipeline/config.py`) |
| Households without a vehicle | ACS 2023 5-year B25044 |
| Municipal boundaries | Census TIGER/Line county subdivisions |

Build counts and checks are written to `data/reports/` (including `geography.json`).

## Run locally

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

The UI reads `web/public/data/rxgap.json`.

### Rebuild the data

```bash
python -m pipeline.build --skip-cms
python -m unittest discover -s tests
```

That resolves study geography, extracts Overture for the analysis envelope bbox, geocodes licensed pharmacies (retained inside the envelope polygon), builds the walk graph, allocates demand inside the study union, computes nearest/second stores, and writes `web/public/data/rxgap.json`.

## Deploy

[Vercel](https://vercel.com) hosts the frontend at [https://rxgap.vercel.app/](https://rxgap.vercel.app/). Root `vercel.json` builds `web/` and publishes `web/dist`.

## Cuts

No transit, driving, delivery/mail-order, insurance networks, medication availability, hours, or opening-location optimization.

## Limitations

- Nearest and second-nearest licensed walk-in stores are modeled; observed shopping trips are not.
- Board retail licenses are the operating-status filter. An active NPI is not treated as proof the storefront is open.
- Duplicate licenses for one storefront remain visible; only one identity is used for routing.
- ACS margins of error are kept at block-group and citywide level. They are not spread onto H3 cells.
- Households near the study edge may have a nearer pharmacy in the routing envelope that is not closable in the tool.

The pipeline refuses to finish if a known-closed storefront is marked active, if demand allocation drops households, or if the pedestrian graph fails continuity checks (including Boston–Cambridge crossings of the Charles).
