import { useEffect, useState } from "react";
import { MapView } from "./components/MapView";
import { SidePanel } from "./components/SidePanel";
import { TopBar } from "./components/TopBar";
import { formatHh, impact } from "./lib/metrics";
import type { PaceId, RxGapData } from "./lib/types";

export default function App() {
  const [data, setData] = useState<RxGapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [paceId, setPaceId] = useState<PaceId>("average");
  const [threshold, setThreshold] = useState(15);

  useEffect(() => {
    fetch("/data/rxgap.json")
      .then((r) => {
        if (!r.ok) throw new Error("Data artifact missing. Run python -m pipeline.build");
        return r.json();
      })
      .then((json: RxGapData) => {
        setData(json);
        setPaceId(json.meta.defaultPace);
        setThreshold(json.meta.thresholdMinutes);
      })
      .catch((err: Error) => setError(err.message));
  }, []);

  if (error) return <main className="boot">{error}</main>;
  if (!data) return <main className="boot">Opening the map…</main>;

  const selected = data.pharmacies.find((p) => p.id === selectedId) ?? null;
  const pace = data.meta.paces[paceId];
  const stats = impact(data, simulating ? selected?.id ?? null : null, pace, threshold);
  const altIds =
    selected && simulating
      ? stats.alternatives.map((a) => a.pharmacy?.id).filter((id): id is string => Boolean(id))
      : [];

  return (
    <div className="app">
      <TopBar
        data={data}
        selected={selected}
        paceId={paceId}
        threshold={threshold}
        onSelect={(id) => {
          setSelectedId(id);
          setSimulating(false);
        }}
        onPace={setPaceId}
        onThreshold={setThreshold}
      />
      <div className="stage">
        <MapView
          data={data}
          selectedId={selectedId}
          simulating={simulating}
          altIds={altIds}
          onSelect={(id) => {
            setSelectedId(id);
            setSimulating(false);
          }}
        />
        {selected && (
          <SidePanel
            data={data}
            selected={selected}
            simulating={simulating}
            pace={pace}
            threshold={threshold}
            onSimulate={() => setSimulating(true)}
            onClear={() => setSimulating(false)}
            onDeselect={() => {
              setSelectedId(null);
              setSimulating(false);
            }}
          />
        )}
        {!selected && (
          <p className="hint">Pick a pharmacy on the map, then simulate what happens if it closes.</p>
        )}
        <div className="legend">
          <span>
            <i className="swatch ink" /> pharmacy
          </span>
          {simulating && (
            <>
              <span>
                <i className="swatch coral" /> closing
              </span>
              <span>
                <i className="swatch teal" /> next closest
              </span>
            </>
          )}
          <span>
            <i className="swatch gray" /> can&apos;t simulate
          </span>
          <p>
            Numbered circles are groups of stores — zoom in to see each one. A walk
            over {threshold} min (at {pace.label.toLowerCase()} pace) counts as too far.
            Today, about {formatHh(stats.alreadyHh)} no-vehicle households in Boston and
            Cambridge are already past that.
          </p>
        </div>
      </div>
    </div>
  );
}
