import type { Hex, HexAccess, Pace, RxGapData } from "./types";

export function hexAccess(
  hex: Hex,
  closedId: string | null,
  mps: number,
): HexAccess {
  const closed = Boolean(closedId && hex.nearestId === closedId);
  const meters = closed ? hex.secondM : hex.nearestM;
  const pharmacyId = closed ? hex.secondId : hex.nearestId;
  return {
    meters,
    minutes: meters == null ? null : meters / mps / 60,
    pharmacyId,
  };
}

export function isNewlyLost(
  hex: Hex,
  closedId: string | null,
  mps: number,
  threshold: number,
): boolean {
  if (!closedId || hex.nearestId !== closedId) return false;
  const base = hexAccess(hex, null, mps);
  const after = hexAccess(hex, closedId, mps);
  return (
    base.minutes != null &&
    base.minutes <= threshold &&
    (after.minutes == null || after.minutes > threshold)
  );
}

export function searchPharmacies(
  pharmacies: RxGapData["pharmacies"],
  query: string,
  limit = 10,
) {
  const q = query.trim().toLowerCase();
  return pharmacies
    .filter((p) => p.inStudyArea)
    .filter((p) => !q || `${p.name} ${p.address} ${p.city}`.toLowerCase().includes(q))
    .slice(0, limit);
}

export function weightedMedian(pairs: { value: number; weight: number }[]): number | null {
  const rows = pairs
    .filter((p) => p.weight > 0 && Number.isFinite(p.value))
    .sort((a, b) => a.value - b.value);
  const total = rows.reduce((s, r) => s + r.weight, 0);
  if (!total) return null;
  let acc = 0;
  for (const row of rows) {
    acc += row.weight;
    if (acc >= total / 2) return row.value;
  }
  return rows[rows.length - 1]?.value ?? null;
}

export function impact(
  data: RxGapData,
  closedId: string | null,
  pace: Pace,
  threshold: number,
) {
  let newlyHh = 0;
  let keptHh = 0;
  let alreadyHh = 0;
  let maxAfterM: number | null = null;
  let maxBeforeM: number | null = null;
  let maxExtraM: number | null = null;
  let someUnreachable = false;
  const extra: { value: number; weight: number }[] = [];
  const before: { value: number; weight: number }[] = [];
  const after: { value: number; weight: number }[] = [];
  const next = new Map<string, { households: number; extras: { value: number; weight: number }[] }>();

  for (const hex of data.hexes) {
    const base = hexAccess(hex, null, pace.mps);
    const hh = hex.households;
    if (base.minutes == null || base.minutes > threshold) alreadyHh += hh;
    if (isNewlyLost(hex, closedId, pace.mps, threshold)) newlyHh += hh;
    else if (closedId && hex.nearestId === closedId) {
      const walk = hexAccess(hex, closedId, pace.mps);
      if (
        base.minutes != null &&
        base.minutes <= threshold &&
        walk.minutes != null &&
        walk.minutes <= threshold
      ) {
        keptHh += hh;
      }
    }
    // Everything below describes only the households who can walk here today —
    // the ones a closure actually changes something for.
    if (!closedId || hex.nearestId !== closedId) continue;
    if (base.minutes == null || base.minutes > threshold) continue;
    if (hex.secondM == null) {
      someUnreachable = true;
      continue;
    }
    // The hardest-hit household is the longest walk left, so its "before" has to
    // come from the same hex — a separate max would pair two different places.
    if (maxAfterM == null || hex.secondM > maxAfterM) {
      maxAfterM = hex.secondM;
      maxBeforeM = hex.nearestM;
    }
    if (hex.nearestM != null) {
      const extraM = hex.secondM - hex.nearestM;
      if (maxExtraM == null || extraM > maxExtraM) maxExtraM = extraM;
      extra.push({ value: extraM, weight: hh });
      before.push({ value: hex.nearestM, weight: hh });
      after.push({ value: hex.secondM, weight: hh });
    }
    if (hex.secondId) {
      const row = next.get(hex.secondId) ?? { households: 0, extras: [] };
      row.households += hh;
      row.extras.push({ value: hex.secondM, weight: hh });
      next.set(hex.secondId, row);
    }
  }

  const toMin = (m: number | null) => (m == null ? null : m / pace.mps / 60);
  const medianExtra = weightedMedian(extra);
  return {
    newlyHh,
    keptHh,
    /** Households who can walk to this store today — the denominator the panel splits. */
    affectedHh: newlyHh + keptHh,
    alreadyHh,
    someUnreachable,
    medianExtra,
    medianExtraMin: toMin(medianExtra),
    medianBeforeMin: toMin(weightedMedian(before)),
    medianAfterMin: toMin(weightedMedian(after)),
    maxExtraMin: toMin(maxExtraM),
    maxBeforeMin: toMin(maxBeforeM),
    maxAfterMin: toMin(maxAfterM),
    alternatives: [...next.entries()]
      .sort((a, b) => b[1].households - a[1].households)
      .slice(0, 3)
      .map(([id, row]) => {
        const meters = weightedMedian(row.extras);
        return {
          pharmacy: data.pharmacies.find((p) => p.id === id) ?? null,
          households: row.households,
          minutes: toMin(meters),
        };
      }),
  };
}

/** Households newly lost per pharmacy if that store alone closed (one pass over hexes). */
export function newlyLostByPharmacy(
  data: RxGapData,
  pace: Pace,
  threshold: number,
): Map<string, number> {
  const byId = new Map<string, number>();
  for (const hex of data.hexes) {
    if (!hex.nearestId) continue;
    if (isNewlyLost(hex, hex.nearestId, pace.mps, threshold)) {
      byId.set(hex.nearestId, (byId.get(hex.nearestId) ?? 0) + hex.households);
    }
  }
  return byId;
}

export function closureRank(
  data: RxGapData,
  closedId: string,
  pace: Pace,
  threshold: number,
) {
  const impactById = newlyLostByPharmacy(data, pace, threshold);
  const scored = data.pharmacies
    .filter((p) => p.inStudyArea && p.simulatable)
    .map((p) => ({ id: p.id, newlyHh: impactById.get(p.id) ?? 0 }))
    .sort((a, b) => b.newlyHh - a.newlyHh || a.id.localeCompare(b.id));
  const index = scored.findIndex((row) => row.id === closedId);
  if (index < 0) return null;
  return { rank: index + 1, of: scored.length };
}

/** Deterministic example for onboarding: highest newly-lost impact at this pace/threshold. */
export function exampleClosurePharmacy(
  data: RxGapData,
  pace: Pace,
  threshold: number,
) {
  const impactById = newlyLostByPharmacy(data, pace, threshold);
  const candidates = data.pharmacies.filter((p) => p.inStudyArea && p.simulatable);
  if (!candidates.length) return null;
  const withImpact = candidates
    .map((p) => ({ pharmacy: p, newlyHh: impactById.get(p.id) ?? 0 }))
    .filter((row) => row.newlyHh > 0)
    .sort(
      (a, b) =>
        b.newlyHh - a.newlyHh || a.pharmacy.id.localeCompare(b.pharmacy.id),
    );
  if (withImpact.length) return withImpact[0].pharmacy;
  return [...candidates].sort((a, b) => a.id.localeCompare(b.id))[0] ?? null;
}

export function servedHouseholds(data: RxGapData, pharmacyId: string): number {
  return data.hexes.reduce((sum, hex) => (hex.nearestId === pharmacyId ? sum + hex.households : sum), 0);
}

export function formatHh(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

export function formatMin(minutes: number | null): string {
  if (minutes == null) return "—";
  return `+${minutes.toFixed(1)} min`;
}

export function formatWalk(minutes: number | null): string {
  if (minutes == null) return "—";
  return `${Math.round(minutes)} min`;
}

/** "41st", "2nd" — the panel names a rank in prose, not as a bare number. */
export function formatOrdinal(n: number): string {
  const abs = Math.abs(Math.round(n));
  const tens = abs % 100;
  const suffix =
    tens >= 11 && tens <= 13
      ? "th"
      : { 1: "st", 2: "nd", 3: "rd" }[abs % 10] ?? "th";
  return `${abs}${suffix}`;
}

/** Whole-percent share, clamped so a rounded 0% never reads as "nobody". */
export function sharePct(part: number, whole: number): number {
  if (!whole) return 0;
  const raw = (part / whole) * 100;
  if (raw > 0 && raw < 1) return 1;
  if (raw < 100 && raw > 99) return 99;
  return Math.round(raw);
}
