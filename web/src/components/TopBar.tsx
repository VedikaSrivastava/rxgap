import { type CSSProperties, useMemo, useRef, useState } from "react";
import { searchPharmacies } from "../lib/metrics";
import type { PaceId, Pharmacy, RxGapData } from "../lib/types";

type Props = {
  data: RxGapData;
  selected: Pharmacy | null;
  paceId: PaceId;
  threshold: number;
  highlightMaxWalk?: boolean;
  onSelect: (id: string) => void;
  onPace: (id: PaceId) => void;
  onThreshold: (n: number) => void;
};

const MIN_WALK = 5;
const MAX_WALK = 30;
const TICKS = [5, 10, 15, 20, 30];

function walkMiles(threshold: number, mph: number) {
  return threshold * (mph / 60);
}

function formatMph(mph: number) {
  const n = Number.isInteger(mph) ? String(mph) : mph.toFixed(1);
  return `${n} mph`;
}

function formatWalkMiles(miles: number) {
  const n = Math.round(miles * 100) / 100;
  return n === 1 ? "1 mile" : `${n} miles`;
}

function walkPct(minutes: number) {
  return ((minutes - MIN_WALK) / (MAX_WALK - MIN_WALK)) * 100;
}

export function TopBar({
  data,
  selected,
  paceId,
  threshold,
  highlightMaxWalk = false,
  onSelect,
  onPace,
  onThreshold,
}: Props) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [assumptionsOpen, setAssumptionsOpen] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);
  const matches = useMemo(
    () => searchPharmacies(data.pharmacies, query),
    [data.pharmacies, query],
  );
  const pace = data.meta.paces[paceId];
  const miles = walkMiles(threshold, pace.mph);
  const paceWord = pace.label.toLowerCase();
  const simulatable = data.pharmacies.filter((p) => p.simulatable).length;
  const area = data.meta.areaLabel ?? "Greater Boston";
  // WebKit has no ::-moz-range-progress, so the filled track is drawn from here.
  const fill = walkPct(threshold);

  // The picked store collapses the search into a summary row; the field only
  // comes back when there is nothing chosen or the user asks to change it.
  const searching = open || !selected;

  return (
    <header className="topbar">
      <div className="brand">
        <strong>RxGap</strong>
        <span>{area}</span>
        <p>See who loses a walkable pharmacy  access when a store permanently closes.</p>
        <div className="brand-foot">
          <button
            type="button"
            className="link-quiet"
            aria-expanded={assumptionsOpen}
            onClick={() => setAssumptionsOpen((v) => !v)}
          >
            All assumptions
          </button>
          {assumptionsOpen && (
            <dl className="assumptions">
              <div>
                <dt>Walking speed</dt>
                <dd>{pace.source}</dd>
              </div>
              <div>
                <dt>Who is counted</dt>
                <dd>
                  Households with no vehicle available, {data.meta.acsYear} ACS 5-year estimates.
                </dd>
              </div>
              <div>
                <dt>Pharmacies</dt>
                <dd>
                  {data.meta.pharmacies || "Overture Places"}
                  {data.meta.overtureRelease ? ` · ${data.meta.overtureRelease}` : ""}
                </dd>
              </div>
              <div>
                <dt>Street network</dt>
                <dd>{data.meta.network || "OpenStreetMap walking network"}</dd>
              </div>
            </dl>
          )}
        </div>
      </div>

      <div className="step step-pick">
        <p className="step-head">
          <span className="step-num" aria-hidden="true">
            1
          </span>
          <label htmlFor="pharmacy-search">Pick a pharmacy to close</label>
        </p>

        <div className="ask">
          {searching ? (
            <input
              id="pharmacy-search"
              ref={inputRef}
              value={query}
              autoComplete="off"
              placeholder="Search by name or address"
              onChange={(e) => {
                setQuery(e.target.value);
                setOpen(true);
              }}
              onFocus={() => setOpen(true)}
              onBlur={() => window.setTimeout(() => setOpen(false), 180)}
            />
          ) : (
            <p className="picked">
              <span className="picked-dot" aria-hidden="true" />
              <span className="picked-name">
                {selected.name} <span className="picked-addr">· {selected.address}</span>
              </span>
              <button
                type="button"
                className="picked-change"
                onClick={() => {
                  setQuery("");
                  setOpen(true);
                  window.setTimeout(() => inputRef.current?.focus(), 0);
                }}
              >
                Change
              </button>
            </p>
          )}
          {searching && open && (
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
                      {p.simulatable
                        ? p.address
                        : (p.excludeReason ?? "Cannot simulate permanent closure")}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <p className="step-note">
          Or click any dot on the map. {simulatable.toLocaleString("en-US")} pharmacies in the
          study area.
        </p>
      </div>

      <div className={`step step-walk${highlightMaxWalk ? " is-spotlight" : ""}`}>
        <p className="step-head">
          <span className="step-num" aria-hidden="true">
            2
          </span>
          <label htmlFor="max-walk">How far is too far to walk?</label>
        </p>

        <div className="walk-value">
          <p className="walk-readout">
            <b>{threshold} min</b>
            <span>
              covers about {formatWalkMiles(miles)} at a {paceWord} pace
            </span>
          </p>
          <div className="walk-speed">
            <p className="walk-speed-label" id="walk-speed-label">
              Walking speed
            </p>
            <div className="segmented" role="group" aria-labelledby="walk-speed-label">
              {(Object.keys(data.meta.paces) as PaceId[]).map((id) => {
                const p = data.meta.paces[id];
                return (
                  <button
                    key={id}
                    type="button"
                    className={id === paceId ? "is-on" : undefined}
                    aria-pressed={id === paceId}
                    aria-label={`${p.label}, ${formatMph(p.mph)}`}
                    data-speed={formatMph(p.mph)}
                    onClick={() => onPace(id)}
                  >
                    {p.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>

        <input
          id="max-walk"
          className="walk-range"
          style={{ "--fill": `${fill}%` } as CSSProperties}
          type="range"
          min={MIN_WALK}
          max={MAX_WALK}
          value={threshold}
          onChange={(e) => onThreshold(Number(e.target.value))}
          aria-label="Maximum walk in minutes"
        />
        <p className="walk-ticks" aria-hidden="true">
          {TICKS.map((t) => (
            <span
              key={t}
              className={t === threshold ? "is-on" : undefined}
              style={{ left: `${walkPct(t)}%` }}
            >
              {t}
            </span>
          ))}
        </p>
      </div>
    </header>
  );
}
