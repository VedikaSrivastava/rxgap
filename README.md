# RxGap

Pharmacy closure impact simulator for Boston and Cambridge.

**See how pharmacy closures change walkable access across Boston and Cambridge.**

RxGap answers a specific operational question: if this pharmacy closes, which households without a vehicle lose a reasonable walk, and how much farther is the next store?

Select a pharmacy, click **Simulate closure**, and the map shifts from today’s access to the households that lose a 15-minute walk.

## Why this exists

A nearest-pharmacy map cannot answer the counterfactual. Public-health and planning staff get a closure notice and need to know what changes *before* the doors shut.

The Q1 2026 CMS “Retail Pharmacy Access” ZIP is plan-level network adequacy, not a walk-in storefront directory. Walk-in identity is NPPES taxonomy `3336C0003X` (Community/Retail Pharmacy), geocoded and matched to Overture places.

## Walking contract

Pace is Slow / Average / Brisk. It is a documented walking-speed assumption, not a claim about who lives in no-vehicle households.

| Pace | Speed | Source |
| --- | --- | --- |
| Slow | 2.0 mph | MUTCD slower-walker design speed |
| Average | 3.0 mph *(default)* | Common FHWA pedestrian planning speed |
| Brisk | 4.0 mph | Brisk adult walk |

The access threshold is **15 minutes**. Demand is clipped to Boston and Cambridge; the walk graph and candidate pharmacies extend **3 km** beyond city limits so border neighborhoods are not artificially stranded.

## Stack

- Python pipeline: DuckDB against Overture GeoParquet, NPPES, ACS, H3
- Vite + React + TypeScript + MapLibre frontend
- Static artifact on Vercel (free)

## Run locally

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pipeline.build

cd web
npm install
npm run dev
```

The pipeline writes `web/public/data/rxgap.json`. That file is what the app serves. Re-run the pipeline when sources update.

## Deploy

[Vercel](https://vercel.com) can host the frontend for free. Root `vercel.json` builds `web/` and publishes `web/dist`. Commit `web/public/data/rxgap.json` so the deployed app does not need the Python pipeline.

## Kill conditions

If we cannot assemble a defensible walk-in pharmacy set, or the pedestrian graph does not connect Boston and Cambridge across the Charles, the project is not honest enough to ship. Spike reports live in `data/reports/`.
