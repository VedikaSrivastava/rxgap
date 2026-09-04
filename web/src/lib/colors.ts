/** The three states the map key names, in the key's own colours. One hue means
 *  one thing in both the before and after views, so the key never needs a caveat. */
export const CELL_NEWLY_LOST = "#b4543e";
export const CELL_WALKABLE = "#5f9e92";
export const CELL_BEYOND = "#d8bcb2";

export function minutesColor(
  minutes: number | null,
  threshold: number,
  newlyLost: boolean,
): string {
  if (newlyLost) return CELL_NEWLY_LOST;
  if (minutes == null) return CELL_BEYOND;
  return minutes <= threshold ? CELL_WALKABLE : CELL_BEYOND;
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

export function hexFill(
  minutes: number | null,
  households: number,
  threshold: number,
  newlyLost: boolean,
  simulating: boolean,
) {
  const beyond = minutes == null || minutes > threshold;
  return {
    color: minutesColor(minutes, threshold, newlyLost),
    opacity: minutesOpacity(households, newlyLost, simulating, beyond),
  };
}
