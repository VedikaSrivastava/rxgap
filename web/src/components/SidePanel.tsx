import { useMemo } from "react";
import { closureRank, formatHh, formatMin, formatWalk, impact, servedHouseholds } from "../lib/metrics";
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
  const served = useMemo(() => servedHouseholds(data, selected.id), [data, selected]);
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
          <>
            <div className="stat">
              <span>Closest store for</span>
              <b>{formatHh(served)}</b>
              <p>no-vehicle households in {data.meta.areaLabel ?? "this area"}</p>
            </div>
            <p className="lead">
              If it closes, those households walk to the next licensed pharmacy. A walk
              over {threshold} minutes counts as losing access.
            </p>
            <button className="cta" onClick={onSimulate}>
              Simulate closure
            </button>
          </>
        ) : (
          <p className="warn">{selected.excludeReason ?? "This pharmacy cannot be simulated."}</p>
        )
      ) : (
        <>
          <div className="stat is-after">
            <span>Would lose a {threshold}-min walk</span>
            <b>+{formatHh(stats.newlyHh)}</b>
            <p>no-vehicle households whose closest store is this one, and whose next option is too far</p>
          </div>
          <div className="stat">
            <span>Typical extra walk</span>
            <b>{formatMin(stats.medianExtraMin)}</b>
            <p>for households that used this as their closest pharmacy</p>
          </div>
          {rank && (
            <div className="stat">
              <span>Impact rank</span>
              <b>#{rank.rank}</b>
              <p>of {rank.of} {data.meta.areaLabel ?? "study-area"} pharmacies we can close in the tool</p>
            </div>
          )}
          {stats.alternatives[0]?.pharmacy && (
            <div className="alts">
              <p>Where they go next</p>
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
