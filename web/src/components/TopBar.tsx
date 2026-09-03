import { useMemo, useState } from "react";
import { searchPharmacies } from "../lib/metrics";
import type { PaceId, Pharmacy, RxGapData } from "../lib/types";

type Props = {
  data: RxGapData;
  selected: Pharmacy | null;
  paceId: PaceId;
  threshold: number;
  onSelect: (id: string) => void;
  onPace: (id: PaceId) => void;
  onThreshold: (n: number) => void;
};

function walkMiles(threshold: number, mph: number) {
  return threshold * (mph / 60);
}

export function TopBar({
  data,
  selected,
  paceId,
  threshold,
  onSelect,
  onPace,
  onThreshold,
}: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const matches = useMemo(
    () => searchPharmacies(data.pharmacies, query),
    [data.pharmacies, query],
  );
  const pace = data.meta.paces[paceId];
  const miles = walkMiles(threshold, pace.mph);
  const paceWord = pace.label.toLowerCase();

  return (
    <header className="topbar">
      <div className="brand">
        <strong>RxGap</strong>
        <span>{data.meta.areaLabel ?? "Greater Boston"}</span>
        <p>See who loses walkable pharmacy access when a store closes.</p>
      </div>

      <div className="ask">
        <label htmlFor="pharmacy-search">Which pharmacy is closing?</label>
        <input
          id="pharmacy-search"
          value={open || !selected ? query : selected.name}
          placeholder="Search, or click one on the map"
          onChange={(e) => {
            setQuery(e.target.value);
            setOpen(true);
          }}
          onFocus={() => {
            setQuery("");
            setOpen(true);
          }}
          onBlur={() => window.setTimeout(() => setOpen(false), 180)}
        />
        {open && (
          <ul className="suggest">
            {matches.map((p) => (
              <li key={p.id}>
                <button
                  onMouseDown={(e) => e.preventDefault()}
                  onClick={() => {
                    onSelect(p.id);
                    setQuery("");
                    setOpen(false);
                  }}
                >
                  <b>{p.name}</b>
                  <span>
                    {p.simulatable ? p.address : (p.excludeReason ?? "Cannot simulate closure")}
                  </span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="toggles">
        <label className="max-walk">
          <span className="max-walk-title">Max walk</span>
          <span className="max-walk-value">
            {threshold} min
            <span className="max-walk-miles">
              ≈{miles.toFixed(2)} mi of walking at {paceWord} pace
            </span>
          </span>
          <input
            type="range"
            min={10}
            max={30}
            value={threshold}
            onChange={(e) => onThreshold(Number(e.target.value))}
            aria-label="Maximum walk in minutes"
          />
        </label>
        <details className="assumptions">
          <summary>Assumptions</summary>
          <label>
            Walking speed
            <select value={paceId} onChange={(e) => onPace(e.target.value as PaceId)}>
              {(Object.keys(data.meta.paces) as PaceId[]).map((id) => {
                const p = data.meta.paces[id];
                return (
                  <option key={id} value={id}>
                    {p.label} ({p.mph} mph)
                  </option>
                );
              })}
            </select>
          </label>
        </details>
      </div>
    </header>
  );
}
