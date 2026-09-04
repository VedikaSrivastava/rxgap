import { useEffect, useId, useRef, useState } from "react";
import { type IntroPhase, prefersReducedMotion } from "../lib/intro";

type Props = {
  onDismiss: () => void;
  onTryExample: () => void;
  onPhase: (phase: IntroPhase) => void;
  /** Hold the step animation until the map tiles and pharmacy dots have painted. */
  mapReady?: boolean;
};

const STEPS: { phase: IntroPhase; text: string }[] = [
  { phase: "pharmacy", text: "Pick a pharmacy" },
  { phase: "maxWalk", text: "Set how far is too far to walk" },
  { phase: "simulate", text: "See who loses access" },
];

const STEP_PHARMACY_MS = 3200;
const STEP_WALK_MS = 2000;
const STEP_SIMULATE_MS = 1500;

export function IntroCard({ onDismiss, onTryExample, onPhase, mapReady = false }: Props) {
  const titleId = useId();
  const whyId = useId();
  const cardRef = useRef<HTMLDivElement>(null);
  const [whyOpen, setWhyOpen] = useState(true);
  const [phase, setPhase] = useState<IntroPhase>("idle");
  const onPhaseRef = useRef(onPhase);
  const onDismissRef = useRef(onDismiss);

  useEffect(() => {
    onPhaseRef.current = onPhase;
    onDismissRef.current = onDismiss;
  });

  // Non-modal dialog: focus it so screen readers announce it, and let Escape close it.
  useEffect(() => {
    cardRef.current?.focus({ preventScroll: true, focusVisible: false });
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onDismissRef.current();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (!mapReady) return;
    const advance = (next: IntroPhase) => {
      setPhase(next);
      onPhaseRef.current(next);
    };
    if (prefersReducedMotion()) {
      advance("idle");
      return;
    }
    advance("pharmacy");
    const timers = [
      window.setTimeout(() => advance("maxWalk"), STEP_PHARMACY_MS),
      window.setTimeout(() => advance("simulate"), STEP_PHARMACY_MS + STEP_WALK_MS),
      window.setTimeout(
        () => advance("idle"),
        STEP_PHARMACY_MS + STEP_WALK_MS + STEP_SIMULATE_MS,
      ),
    ];
    return () => {
      for (const t of timers) window.clearTimeout(t);
      onPhaseRef.current("idle");
    };
  }, [mapReady]);

  return (
    <div
      className="intro"
      role="dialog"
      aria-modal="false"
      aria-labelledby={titleId}
      tabIndex={-1}
      ref={cardRef}
    >
      <div className="intro-main">
        <div className="intro-top">
          <h2 id={titleId}>What happens when a pharmacy permanently closes?</h2>
          <button
            className="close"
            type="button"
            onClick={() => onDismiss()}
            aria-label="Dismiss intro"
          >
            ×
          </button>
        </div>

        <p className="intro-body">
          RxGap simulates a closure and shows which car-free households in Greater Boston lose a
          pharmacy they can walk to.
        </p>

        <ol className="intro-steps">
          {STEPS.map((step, i) => (
            <li key={step.phase} className={phase === step.phase ? "is-active" : undefined}>
              <span className="intro-step-num" aria-hidden="true">
                {i + 1}
              </span>
              <span className="intro-step-text">{step.text}</span>
            </li>
          ))}
        </ol>

        <div className="intro-actions">
          <button className="cta" type="button" onClick={() => onTryExample()}>
            Walk me through an example
          </button>
          <button className="ghost" type="button" onClick={() => onDismiss()}>
            I&apos;ll explore the map myself
          </button>
        </div>
      </div>

      <div className="intro-why">
        <button
          type="button"
          className="intro-why-toggle"
          aria-expanded={whyOpen}
          aria-controls={whyId}
          onClick={() => setWhyOpen((v) => !v)}
        >
          <span>Why this matters</span>
          <span aria-hidden="true">{whyOpen ? "↓" : "→"}</span>
        </button>
        {whyOpen && (
          <p className="intro-context" id={whyId}>
            Boston officials counted 41 pharmacy closures since 2018. In December 2025 the City
            Council backed a petition to extend permanent-closure notice from 14 to 120 days, so
            communities have time to respond. RxGap asks what that window could tell them.
          </p>
        )}
      </div>
    </div>
  );
}
