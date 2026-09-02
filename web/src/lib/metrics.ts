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

export function impact(
  data: RxGapData,
  closedId: string | null,
  pace: Pace,
  threshold: number,
) {
  let newlyHh = 0;
  let alreadyHh = 0;
  const extraMeters: number[] = [];
  const nextCount = new Map<string, number>();

  for (const hex of data.hexes) {
    const base = hexAccess(hex, null, pace.mps);
    const next = hexAccess(hex, closedId, pace.mps);
    const hh = hex.households;
    if (base.minutes != null && base.minutes > threshold) alreadyHh += hh;
    const newly =
      Boolean(closedId) &&
      hex.nearestId === closedId &&
      base.minutes != null &&
      base.minutes <= threshold &&
      (next.minutes == null || next.minutes > threshold);
    if (newly) newlyHh += hh;
    if (closedId && hex.nearestId === closedId && hex.nearestM != null && hex.secondM != null) {
      extraMeters.push(hex.secondM - hex.nearestM);
      if (hex.secondId) nextCount.set(hex.secondId, (nextCount.get(hex.secondId) ?? 0) + hh);
    }
  }

  extraMeters.sort((a, b) => a - b);
  const medianExtra =
    extraMeters.length === 0 ? null : extraMeters[Math.floor(extraMeters.length / 2)];

  return {
    newlyHh,
    alreadyHh,
    medianExtra,
    medianExtraMin: medianExtra == null ? null : medianExtra / pace.mps / 60,
    alternatives: [...nextCount.entries()]
      .sort((a, b) => b[1] - a[1])
      .slice(0, 3)
      .map(([id, households]) => ({
        pharmacy: data.pharmacies.find((p) => p.id === id) ?? null,
        households,
      })),
  };
}

export function closureRank(
  data: RxGapData,
  closedId: string,
  pace: Pace,
  threshold: number,
) {
  const scored = data.pharmacies
    .map((p) => ({ id: p.id, newlyHh: impact(data, p.id, pace, threshold).newlyHh }))
    .sort((a, b) => b.newlyHh - a.newlyHh);
  const index = scored.findIndex((row) => row.id === closedId);
  if (index < 0) return null;
  return { rank: index + 1, of: scored.length };
}

export function formatHh(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

export function formatMin(minutes: number | null): string {
  if (minutes == null) return "—";
  return `+${minutes.toFixed(1)} min`;
}
