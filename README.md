# RxGap

Pharmacy closure impact simulator for Boston and Cambridge.

**See how a pharmacy closure changes walkable access.**

Select a pharmacy, click **Simulate closure**, and the map shifts from today’s walkable coverage to the households that lose a 15-minute walk.

## Why this exists

Boston and Cambridge have watched chain pharmacies close. A nearest-pharmacy map cannot answer the operational question: if this storefront shuts, which no-vehicle households lose a reasonable walk, and how much farther is the next licensed store?

Demand is clipped to Boston and Cambridge. The walk graph and candidate pharmacies extend 3 km beyond city limits so border neighborhoods are not artificially stranded. Only study-area pharmacies are selectable; buffer pharmacies can appear as nearest alternatives.

## Sources

| Layer | Authority |
| --- | --- |
| Currently licensed location | MA Board of Registration in Pharmacy, currently licensed *Retail Pharmacy* roster |
| Pharmacy type | NPPES taxonomy `3336C0003X` (Community/Retail Pharmacy) |
| Location / context | Overture places |
| Walk network | Overture transportation `segment` topology via `connector_id` |
| Demand | ACS 2023 5-year B25044 no-vehicle households, with MOEs, allocated to Overture buildings, then H3-9 |

Build-specific source counts and validation checks are written to `data/reports/`. CMS Q1 2026 Retail Pharmacy Access is plan-level network adequacy, not a storefront directory.

Known closed storefronts (90 River St, 1329 Hyde Park Ave, 2275 Washington St, 416 Warren St) fail the pipeline if they re-enter as active.

## Walking contract

| Pace | Speed | Source |
| --- | --- | --- |
| Slow | 2.0 mph | MUTCD slower-walker design speed |
| Average | 3.0 mph *(default)* | Common FHWA pedestrian planning speed |
| Brisk | 4.0 mph | Brisk adult walk |

The access threshold is **15 minutes**. Route distance is origin snap + graph path + destination snap, using Overture connector IDs as junctions. Shape coordinates are used for length, not to decide whether two segments connect.

Headline extra-walk is a **household-weighted median** for hexes whose modeled nearest pharmacy was the closed location. That is not a claim about where people actually shop.

## Stack

- Python pipeline: DuckDB against Overture GeoParquet, MA Board bulk license export, NPPES, ACS, H3
- Vite + React + TypeScript + MapLibre frontend
- Static artifact on Vercel (free)

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pipeline.build --skip-cms
python -m unittest discover -s tests

cd web
npm install
npm test
npm run dev
```

The pipeline writes `web/public/data/rxgap.json`. Re-run it when sources update.

## Deploy

[Vercel](https://vercel.com) can host the frontend for free. Root `vercel.json` builds `web/` and publishes `web/dist`. Commit `web/public/data/rxgap.json` so the deployed app does not need the Python pipeline.

## Trade-offs

- Board retail licenses are the operating-status filter; NPPES active NPI status is not.
- Demand uses residential-classified buildings within each block group, falls back to other buildings or a representative point where needed, and must conserve the ACS total.
- Buffer pharmacies are used in shortest-path calculation but are not closable in the product.
- Duplicate licenses for one storefront remain visible but only one identity participates in routing.
- We model nearest / second-nearest licensed walk-in pharmacies, not observed shopping behavior.
- ACS MOEs are pulled and reported at the block-group / citywide level; they are not allocated onto H3 cells.

## Kill conditions

If we cannot assemble a defensible currently licensed walk-in set, or the pedestrian graph does not connect Boston and Cambridge across the Charles, the project is not honest enough to ship. Spike reports live in `data/reports/`.
