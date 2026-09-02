import { useMemo } from "react";
import { closureRank, formatHh, formatMin, impact } from "../lib/metrics";
import type { Pace, Pharmacy, RxGapData } from "../lib/types";

type Props = {
  data: RxGapData;
  selected: Pharmacy;
  simulating: boolean;
  pace: Pace;
  threshold: number;
  onSimulate: () => void;
  onClear: () => void;
  onDeselect: () => void;
};

export function SidePanel({
  data,
  selected,
  simulating,
  pace,
  threshold,
  onSimulate,
  onClear,
  onDeselect,
}: Props) {
  const stats = useMemo(
    () => impact(data, selected.id, pace, threshold),
    [data, selected, pace, threshold],
  );
  const rank = useMemo(
    () => (simulating ? closureRank(data, selected.id, pace, threshold) : null),
    [simulating, data, selected, pace, threshold],
  );

  return (
    <aside className="side">
      <button className="close" onClick={onDeselect} aria-label="Clear selection">
        ×
      </button>
      <p className="kicker">{simulating ? "After this closes" : "This location"}</p>
      <h2>{selected.name}</h2>
      <p className="addr">{selected.address}</p>

      <div className="stat">
        <span>Already beyond {threshold} min</span>
        <b>~{formatHh(stats.alreadyHh)}</b>
        <p>no-vehicle households, before any closure</p>
      </div>

      {!simulating ? (
        <button className="cta" onClick={onSimulate}>
          Simulate closure
        </button>
      ) : (
        <>
          <div className="stat is-after">
            <span>Newly beyond {threshold} min</span>
            <b>+{formatHh(stats.newlyHh)}</b>
            <p>additional no-vehicle households lose access</p>
          </div>
          <div className="stat">
            <span>Extra walk for people who used this store</span>
            <b>{formatMin(stats.medianExtraMin)}</b>
            <p>median additional walking time</p>
          </div>
          {rank && (
            <p className="rank">
              This would be the <strong>#{rank.rank}</strong> most disruptive
              closure of {rank.of} pharmacies here.
            </p>
          )}
          {stats.alternatives[0]?.pharmacy && (
            <div className="alts">
              <p>Where people go next</p>
              <ul>
                {stats.alternatives.map((alt) =>
                  alt.pharmacy ? (
                    <li key={alt.pharmacy.id}>
                      <b>{alt.pharmacy.name}</b>
                      <span>{alt.pharmacy.city}</span>
                    </li>
                  ) : null,
                )}
              </ul>
            </div>
          )}
          <button className="ghost" onClick={onClear}>
            Back to today
          </button>
        </>
      )}
    </aside>
  );
}
