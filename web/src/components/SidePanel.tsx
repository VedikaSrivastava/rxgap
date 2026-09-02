import { useMemo } from "react";
import { closureRank, formatHh, formatMin, formatWalk, impact } from "../lib/metrics";
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
      <p className="kicker">{simulating ? "If this closes" : "This location"}</p>
      <h2>{selected.name}</h2>
      <p className="addr">{selected.address}</p>

      {!simulating ? (
        selected.simulatable ? (
          <button className="cta" onClick={onSimulate}>
            Simulate closure
          </button>
        ) : (
          <p className="warn">{selected.excludeReason ?? "This pharmacy cannot be simulated."}</p>
        )
      ) : (
        <>
          <div className="stat is-after">
            <span>Households newly beyond {threshold} min</span>
            <b>+{formatHh(stats.newlyHh)}</b>
          </div>
          <div className="stat">
            <span>Median extra walk</span>
            <b>{formatMin(stats.medianExtraMin)}</b>
            <p>households whose nearest pharmacy was this location</p>
          </div>
          {rank && (
            <div className="stat">
              <span>Highest-impact closure</span>
              <b>#{rank.rank}</b>
              <p>of {rank.of} study-area pharmacies</p>
            </div>
          )}
          {stats.alternatives[0]?.pharmacy && (
            <div className="alts">
              <p>Nearest alternatives after closure</p>
              <ul>
                {stats.alternatives.map((alt) =>
                  alt.pharmacy ? (
                    <li key={alt.pharmacy.id}>
                      <b>{alt.pharmacy.name}</b>
                      <span>{formatWalk(alt.minutes)}</span>
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
