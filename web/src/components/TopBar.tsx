import { useMemo, useState } from "react";
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
  const q = query.trim().toLowerCase();
  const matches = useMemo(() => {
    const list = data.pharmacies.filter(
      (p) => !q || `${p.name} ${p.address} ${p.city}`.toLowerCase().includes(q),
    );
    return list.slice(0, 10);
  }, [data.pharmacies, q]);

  return (
    <header className="topbar">
      <div className="brand">
        <strong>RxGap</strong>
        <span>Boston · Cambridge</span>
        <p>Pick a store and see who loses a short walk if it closes.</p>
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
        <label className="pace">
          Walk
          <select value={paceId} onChange={(e) => onPace(e.target.value as PaceId)}>
            {(Object.keys(data.meta.paces) as PaceId[]).map((id) => (
              <option key={id} value={id}>
                {data.meta.paces[id].label}
              </option>
            ))}
          </select>
        </label>
        <label className="mins">
          Too far after {threshold} min
          <input
            type="range"
            min={10}
            max={30}
            value={threshold}
            onChange={(e) => onThreshold(Number(e.target.value))}
          />
        </label>
      </div>
    </header>
  );
}
