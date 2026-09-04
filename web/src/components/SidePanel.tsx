import { useMemo } from "react";
import {
  closureRank,
  formatHh,
  formatOrdinal,
  formatWalk,
  impact,
  servedHouseholds,
  sharePct,
} from "../lib/metrics";
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

/** Prefer the full address; only append city when it isn't already in the line. */
function formatPlace(address: string, city: string | null | undefined) {
  const trimmed = address.trim();
  if (city && !trimmed.toLowerCase().includes(city.toLowerCase())) {
    return `${trimmed} · ${city}`;
  }
  return trimmed;
}

/** A before/after walk drawn as one bar: the walk they have, then what is added. */
function WalkShift({
  label,
  before,
  after,
}: {
  label: string;
  before: number | null;
  after: number | null;
}) {
  if (before == null || after == null) return null;
  const kept = after <= 0 ? 0 : Math.min(100, (before / after) * 100);
  return (
    <div className="shift">
      <p className="shift-label">{label}</p>
      <p className="shift-pair">
        <span className="shift-before">{formatWalk(before)}</span>
        <span className="shift-arrow" aria-hidden="true">
          →
        </span>
        <span className="shift-after">{formatWalk(after)}</span>
      </p>
      <span className="shift-bar" aria-hidden="true">
        <i className="shift-bar-kept" style={{ width: `${kept}%` }} />
        <i className="shift-bar-added" style={{ width: `${100 - kept}%` }} />
      </span>
    </div>
  );
}

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

  const area = data.meta.areaLabel ?? "this area";
  const affected = stats.affectedHh;
  const lossPct = sharePct(stats.newlyHh, affected);
  const keptPct = sharePct(stats.keptHh, affected);
  const lossShare = affected ? (stats.newlyHh / affected) * 100 : 0;
  const altCeiling = Math.max(
    threshold,
    ...stats.alternatives.map((alt) => alt.minutes ?? 0),
  );

  return (
    <aside className="side">
      <button className="close" onClick={onDeselect} aria-label="Clear selection">
        ×
      </button>

      <header className="side-head">
        <p className={`kicker${simulating ? " is-live" : ""}`}>
          {simulating ? "Simulated permanent closure" : "Selected pharmacy"}
        </p>
        <h2>{selected.name}</h2>
        <p className="addr">{formatPlace(selected.address, selected.city)}</p>
      </header>

      {!simulating ? (
        selected.simulatable ? (
          <>
            <div className="answer">
              <p className="answer-line">
                <strong>{formatHh(served)} car-free households</strong> count this store as
                their closest pharmacy today.
              </p>
              <p className="answer-note">
                If it closes for good, some of these households would have no pharmacy within a{" "}
                {threshold}-minute walk. Simulate to see how many.
              </p>
            </div>
            <button className="cta is-nudge" onClick={onSimulate}>
              Simulate permanent closure
            </button>
          </>
        ) : (
          <p className="warn">
            {selected.excludeReason ??
              "This pharmacy cannot be simulated as a permanent closure."}
          </p>
        )
      ) : (
        <>
          <div className="answer">
            <p className="answer-line">
              If this store closes for good,{" "}
              <strong>{formatHh(stats.newlyHh)} car-free households</strong> would have no
              pharmacy within a {threshold}-minute walk.
            </p>
            {affected > 0 && (
              <>
                <span className="split" aria-hidden="true">
                  <i className="split-lost" style={{ width: `${lossShare}%` }} />
                  <i className="split-kept" style={{ width: `${100 - lossShare}%` }} />
                </span>
                <p className="split-key">
                  <span>
                    <strong className="is-lost">{formatHh(stats.newlyHh)} lose access</strong> ·{" "}
                    {lossPct}%
                  </span>
                  <span>
                    <strong className="is-kept">{formatHh(stats.keptHh)} still covered</strong> ·{" "}
                    {keptPct}%
                  </span>
                </p>
                <p className="answer-note">
                  of the {formatHh(affected)} car-free households who rely on this store as their
                  closest walkable pharmacy today
                </p>
              </>
            )}
          </div>

          {stats.someUnreachable && (
            <p className="warn">
              Some of these households have no other pharmacy they can reach on foot at all.
            </p>
          )}

          {(stats.medianAfterMin != null || stats.maxAfterMin != null) && (
            <section className="block">
              <h3>How much longer to the next pharmacy</h3>
              <div className="shifts">
                <WalkShift
                  label="Typical household"
                  before={stats.medianBeforeMin}
                  after={stats.medianAfterMin}
                />
                <WalkShift
                  label="Hardest hit"
                  before={stats.maxBeforeMin}
                  after={stats.maxAfterMin}
                />
              </div>
            </section>
          )}

          {rank && (
            <section className="block is-ruled">
              <h3>Compared with other permanent closures</h3>
              <p className="rank-line">
                This is the <strong>{formatOrdinal(rank.rank)} most damaging</strong> of the{" "}
                {rank.of} pharmacies that could permanently close in {area} — worse than{" "}
                {sharePct(rank.of - rank.rank, rank.of)}% of them.
              </p>
              <span className="rank-scale" aria-hidden="true">
                <i className="rank-mark" style={{ left: `${(rank.rank / rank.of) * 100}%` }} />
              </span>
              <p className="rank-ends" aria-hidden="true">
                <span>Most damaging permanent closure</span>
                <span>Least</span>
              </p>
            </section>
          )}

          {stats.alternatives[0]?.pharmacy && (
            <section className="block is-ruled">
              <h3>Where they would walk instead</h3>
              <p className="gold-key">
                <i className="dot is-next" aria-hidden="true" /> shown in gold on the map
              </p>
              <ul className="alts">
                {stats.alternatives.map((alt) =>
                  alt.pharmacy ? (
                    <li key={alt.pharmacy.id}>
                      <span className="alt-body">
                        <span className="alt-name">{alt.pharmacy.name}</span>
                        <span className="alt-bar" aria-hidden="true">
                          <i
                            className={
                              alt.minutes != null && alt.minutes >= threshold
                                ? "is-limit"
                                : undefined
                            }
                            style={{
                              width: `${
                                alt.minutes == null || altCeiling <= 0
                                  ? 100
                                  : Math.min(100, (alt.minutes / altCeiling) * 100)
                              }%`,
                            }}
                          />
                        </span>
                      </span>
                      <span className="alt-time">{formatWalk(alt.minutes)} walk</span>
                    </li>
                  ) : null,
                )}
              </ul>
            </section>
          )}

          <div className="side-foot">
            <button className="cta is-dark" onClick={onClear}>
              Clear this scenario
            </button>
          </div>
        </>
      )}
    </aside>
  );
}
