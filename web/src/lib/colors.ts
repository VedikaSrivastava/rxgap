export function minutesColor(
  minutes: number | null,
  threshold: number,
  newlyLost: boolean,
  simulating: boolean,
): string {
  if (newlyLost) return "#c4452d";
  if (minutes == null) return simulating ? "#e4d5c8" : "#d4a090";
  if (simulating) {
    if (minutes <= threshold) return "#8fb8b2";
    return "#e4d5c8";
  }
  if (minutes <= threshold) return "#3d8f86";
  return "#d4a090";
}

export function minutesOpacity(
  households: number,
  newlyLost: boolean,
  simulating: boolean,
  beyond: boolean,
): number {
  if (households <= 0) return 0.04;
  if (newlyLost) return 0.9;
  const cover = Math.min(0.62, 0.28 + Math.log10(1 + households) * 0.16);
  if (simulating) return cover * 0.28;
  return beyond ? Math.max(0.4, cover * 0.85) : cover;
}
