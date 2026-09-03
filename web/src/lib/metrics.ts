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
  let alreadyHh = 0;
  const extra: { value: number; weight: number }[] = [];
  const next = new Map<string, { households: number; extras: { value: number; weight: number }[] }>();

  for (const hex of data.hexes) {
    const base = hexAccess(hex, null, pace.mps);
    const hh = hex.households;
    if (base.minutes == null || base.minutes > threshold) alreadyHh += hh;
    if (isNewlyLost(hex, closedId, pace.mps, threshold)) newlyHh += hh;
    if (closedId && hex.nearestId === closedId && hex.nearestM != null && hex.secondM != null) {
      extra.push({ value: hex.secondM - hex.nearestM, weight: hh });
      if (hex.secondId) {
        const row = next.get(hex.secondId) ?? { households: 0, extras: [] };
        row.households += hh;
        row.extras.push({ value: hex.secondM, weight: hh });
        next.set(hex.secondId, row);
      }
    }
  }

  const medianExtra = weightedMedian(extra);
  return {
    newlyHh,
    alreadyHh,
    medianExtra,
    medianExtraMin: medianExtra == null ? null : medianExtra / pace.mps / 60,
    alternatives: [...next.entries()]
      .sort((a, b) => b[1].households - a[1].households)
      .slice(0, 3)
      .map(([id, row]) => {
        const meters = weightedMedian(row.extras);
        return {
          pharmacy: data.pharmacies.find((p) => p.id === id) ?? null,
          households: row.households,
          minutes: meters == null ? null : meters / pace.mps / 60,
        };
      }),
  };
}

export function closureRank(
  data: RxGapData,
  closedId: string,
  pace: Pace,
  threshold: number,
) {
  const scored = data.pharmacies
    .filter((p) => p.inStudyArea && p.simulatable)
    .map((p) => ({ id: p.id, newlyHh: impact(data, p.id, pace, threshold).newlyHh }))
    .sort((a, b) => b.newlyHh - a.newlyHh);
  const index = scored.findIndex((row) => row.id === closedId);
  if (index < 0) return null;
  return { rank: index + 1, of: scored.length };
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
