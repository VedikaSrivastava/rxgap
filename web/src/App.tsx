import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { IntroCard } from "./components/IntroCard";
import { MapView } from "./components/MapView";
import { SidePanel } from "./components/SidePanel";
import { TopBar } from "./components/TopBar";
import { hasSeenIntro, markIntroSeen, type IntroPhase } from "./lib/intro";
import { exampleClosurePharmacy, formatHh, impact } from "./lib/metrics";
import type { PaceId, RxGapData } from "./lib/types";

export default function App() {
  const [data, setData] = useState<RxGapData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [simulating, setSimulating] = useState(false);
  const [paceId, setPaceId] = useState<PaceId>("average");
  const [threshold, setThreshold] = useState(15);
  const [introOpen, setIntroOpen] = useState(() => !hasSeenIntro());
  const [introPhase, setIntroPhase] = useState<IntroPhase>("idle");
  const [mapReady, setMapReady] = useState(false);
  const [keyOpen, setKeyOpen] = useState(true);

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

  const pace = data ? data.meta.paces[paceId] : null;
  const example = useMemo(() => {
    if (!data || !pace) return null;
    return exampleClosurePharmacy(data, pace, threshold);
  }, [data, pace, threshold]);

  const aboutRef = useRef<HTMLButtonElement>(null);
  const restoreFocusRef = useRef(false);
  const onMapReady = useCallback(() => setMapReady(true), []);

  // Dismissing unmounts the focused card, so hand focus back to the About control.
  useEffect(() => {
    if (introOpen || !restoreFocusRef.current) return;
    restoreFocusRef.current = false;
    aboutRef.current?.focus();
  }, [introOpen]);

  if (error) return <main className="boot">{error}</main>;
  if (!data || !pace) return <main className="boot">Opening the map…</main>;

  const selected = data.pharmacies.find((p) => p.id === selectedId) ?? null;
  const stats = impact(data, simulating ? selected?.id ?? null : null, pace, threshold);
  const altIds =
    selected && simulating
      ? stats.alternatives.map((a) => a.pharmacy?.id).filter((id): id is string => Boolean(id))
      : [];

  const dismissIntro = (restoreFocus = true) => {
    restoreFocusRef.current = restoreFocus;
    markIntroSeen();
    setIntroOpen(false);
    setIntroPhase("idle");
  };

  const tryExample = () => {
    if (!example) {
      dismissIntro();
      return;
    }
    setSelectedId(example.id);
    setSimulating(false);
    dismissIntro(false);
  };

  const area = data.meta.areaLabel ?? "this area";

  return (
    <div className="app">
      <TopBar
        data={data}
        selected={selected}
        paceId={paceId}
        threshold={threshold}
        highlightMaxWalk={introOpen && introPhase === "maxWalk"}
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
          pace={pace}
          threshold={threshold}
          altIds={altIds}
          pulseId={introOpen && introPhase === "pharmacy" ? example?.id ?? null : null}
          onReady={onMapReady}
          onSelect={(id) => {
            setSelectedId(id);
            setSimulating(false);
          }}
        />
        {introOpen && (
          <IntroCard
            onDismiss={() => dismissIntro()}
            onTryExample={tryExample}
            onPhase={setIntroPhase}
            mapReady={mapReady}
          />
        )}
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
        {!introOpen && (
          <div className="map-footer">
            <button
              type="button"
              className="about-rxgap"
              ref={aboutRef}
              onClick={() => setIntroOpen(true)}
            >
              ⓘ About RxGap
            </button>
          </div>
        )}
        {!introOpen &&
          (keyOpen ? (
            <div className="legend">
              <div className="legend-top">
                <h2>Map key</h2>
                <button type="button" onClick={() => setKeyOpen(false)}>
                  Hide <span aria-hidden="true">▲</span>
                </button>
              </div>

              <div className="legend-group">
                <h3>Neighborhoods, by what this permanent closure does to them</h3>
                <ul>
                  <li>
                    <i className="swatch cell coral" /> Newly cut off — had a walkable pharmacy,
                    now don&apos;t
                  </li>
                  <li>
                    <i className="swatch cell walk" /> Still walkable — another pharmacy within{" "}
                    {threshold} min
                  </li>
                  <li>
                    <i className="swatch cell beyond" /> Already too far before this closure
                  </li>
                </ul>
              </div>

              <div className="legend-group is-ruled">
                <h3>Pharmacy dots</h3>
                <ul className="is-grid">
                  <li>
                    <i className="dot" /> Open
                  </li>
                  <li>
                    <i className="dot is-picked" /> The one you picked
                  </li>
                  <li>
                    <i className="dot is-closing" /> Permanently closing in this scenario
                  </li>
                  <li>
                    <i className="dot is-next" /> Next closest option
                  </li>
                  <li className="is-quiet">
                    <i className="dot is-outside" /> Outside the study area
                  </li>
                  <li className="is-quiet">
                    <i className="dot is-excluded" /> Can&apos;t simulate
                  </li>
                </ul>
              </div>

              <div className="legend-read">
                <p>
                  <strong>Reading the map:</strong> a walk over {threshold} minutes counts as too
                  far. Numbered circles are clusters of stores — zoom in to split them.
                </p>
                <p className="legend-read-note">
                  {formatHh(stats.alreadyHh)} car-free households in {area} are already past that
                  today.
                </p>
              </div>
            </div>
          ) : (
            <button type="button" className="legend-show" onClick={() => setKeyOpen(true)}>
              Map key <span aria-hidden="true">▼</span>
            </button>
          ))}
      </div>
    </div>
  );
}
