export function minutesColor(
  minutes: number | null,
  threshold: number,
  newlyLost: boolean,
  simulating: boolean,
): string {
  if (newlyLost) return "#c4452d";
  if (minutes == null) return "#d4d0c8";
  if (simulating) {
    if (minutes <= threshold) return "#9bb8b3";
    return "#d9c4bc";
  }
  if (minutes <= threshold * 0.55) return "#7fa39d";
  if (minutes <= threshold) return "#cbb58a";
  return "#d4b4ab";
}

export function minutesOpacity(
  households: number,
  newlyLost: boolean,
  simulating: boolean,
): number {
  if (households <= 0) return 0.05;
  if (newlyLost) return 0.78;
  const base = Math.min(0.42, 0.1 + Math.log10(1 + households) * 0.12);
  return simulating ? base * 0.7 : base;
}
