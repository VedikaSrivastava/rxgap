import { describe, expect, it } from "vitest";
import {
  closureRank,
  exampleClosurePharmacy,
  formatOrdinal,
  impact,
  isNewlyLost,
  searchPharmacies,
  servedHouseholds,
  sharePct,
  weightedMedian,
} from "./metrics";
import type { RxGapData } from "./types";

const pace = { id: "average" as const, label: "Average", mph: 3, mps: 1.34112, source: "test" };

const data: RxGapData = {
  meta: {
    title: "RxGap",
    subtitle: "",
    cities: ["Boston", "Cambridge", "Somerville"],
    areaLabel: "Greater Boston",
    bufferKm: 3,
    thresholdMinutes: 15,
    defaultPace: "average",
    paces: { slow: pace, average: pace, brisk: pace },
    overtureRelease: "test",
    acsYear: 2023,
    demand: "",
    network: "",
    pharmacies: "",
    reports: {},
  },
  pharmacies: [
    {
      id: "in",
      name: "Study CVS",
      address: "1 Main St, Boston MA 02118",
      city: "Boston",
      lat: 42.35,
      lon: -71.07,
      confidence: "high",
      inStudyArea: true,
      simulatable: true,
      excludeReason: null,
    },
    {
      id: "buf",
      name: "Quincy CVS",
      address: "1 Hancock St, Quincy MA 02169",
      city: "Quincy",
      lat: 42.25,
      lon: -71.0,
      confidence: "high",
      inStudyArea: false,
      simulatable: false,
      excludeReason: "Outside Greater Boston study area",
    },
    {
      id: "low",
      name: "Low Impact",
      address: "9 Quiet St, Boston MA 02118",
      city: "Boston",
      lat: 42.34,
      lon: -71.06,
      confidence: "high",
      inStudyArea: true,
      simulatable: true,
      excludeReason: null,
    },
  ],
  hexes: [
    {
      h3: "a",
      city: "Boston",
      households: 10,
      lat: 42.35,
      lon: -71.07,
      nearestId: "in",
      nearestM: 400,
      secondId: "buf",
      secondM: 1600,
    },
    {
      h3: "b",
      city: "Boston",
      households: 90,
      lat: 42.36,
      lon: -71.08,
      nearestId: "in",
      nearestM: 500,
      secondId: "buf",
      secondM: 800,
    },
    {
      h3: "c",
      city: "Boston",
      households: 5,
      lat: 42.34,
      lon: -71.06,
      nearestId: "low",
      nearestM: 200,
      secondId: "in",
      secondM: 400,
    },
  ],
};

describe("weightedMedian", () => {
  it("weights households, not hexes", () => {
    expect(weightedMedian([{ value: 10, weight: 1 }, { value: 100, weight: 99 }])).toBe(100);
  });
});

describe("impact", () => {
  it("uses household-weighted extra walk and alternative minutes", () => {
    const stats = impact(data, "in", pace, 15);
    expect(stats.medianExtra).toBe(300);
    expect(stats.alternatives[0]?.pharmacy?.id).toBe("buf");
    expect(stats.alternatives[0]?.minutes).toBeCloseTo(800 / pace.mps / 60);
  });

  it("splits closest-store households into newly lost vs still within the walk", () => {
    const stats = impact(data, "in", pace, 15);
    expect(stats.newlyHh).toBe(10);
    expect(stats.keptHh).toBe(90);
  });

  it("reports the farthest remaining walk among households who can walk here today", () => {
    const stats = impact(data, "in", pace, 15);
    expect(stats.maxAfterMin).toBeCloseTo(1600 / pace.mps / 60);
    expect(stats.maxExtraMin).toBeCloseTo(1200 / pace.mps / 60);
    expect(stats.someUnreachable).toBe(false);
  });

  it("ignores already-too-far households when reporting farthest walk", () => {
    const farther: RxGapData = {
      ...data,
      hexes: [
        ...data.hexes,
        {
          ...data.hexes[0],
          h3: "d",
          households: 1,
          nearestM: 2000,
          secondM: 5000,
        },
      ],
    };
    const stats = impact(farther, "in", pace, 15);
    expect(stats.maxAfterMin).toBeCloseTo(1600 / pace.mps / 60);
    expect(stats.maxExtraMin).toBeCloseTo(1200 / pace.mps / 60);
  });

  it("counts unroutable demand as already beyond the threshold", () => {
    const unroutable: RxGapData = {
      ...data,
      hexes: [
        {
          ...data.hexes[0],
          nearestId: null,
          nearestM: null,
          secondId: null,
          secondM: null,
        },
      ],
    };
    expect(impact(unroutable, null, pace, 15).alreadyHh).toBe(10);
  });
});

describe("impact before/after walks", () => {
  it("pairs the hardest-hit walk with the same household's walk today", () => {
    const stats = impact(data, "in", pace, 15);
    // Hex "a" is the longest remaining walk (1600m); its before must be a's 400m,
    // not the 500m that belongs to hex "b".
    expect(stats.maxAfterMin).toBeCloseTo(1600 / pace.mps / 60);
    expect(stats.maxBeforeMin).toBeCloseTo(400 / pace.mps / 60);
  });

  it("weights the typical before and after by households", () => {
    const stats = impact(data, "in", pace, 15);
    // Hex "b" carries 90 of the 100 households, so it is the weighted median.
    expect(stats.medianBeforeMin).toBeCloseTo(500 / pace.mps / 60);
    expect(stats.medianAfterMin).toBeCloseTo(800 / pace.mps / 60);
  });

  it("counts only households who can walk here today in the split denominator", () => {
    const stats = impact(data, "in", pace, 15);
    expect(stats.affectedHh).toBe(stats.newlyHh + stats.keptHh);
    expect(stats.affectedHh).toBe(100);
  });

  it("leaves before/after empty when nothing can be walked here today", () => {
    const farOnly: RxGapData = {
      ...data,
      hexes: [{ ...data.hexes[0], nearestM: 4000, secondM: 6000 }],
    };
    const stats = impact(farOnly, "in", pace, 15);
    expect(stats.affectedHh).toBe(0);
    expect(stats.medianBeforeMin).toBeNull();
    expect(stats.maxBeforeMin).toBeNull();
  });
});

describe("formatOrdinal", () => {
  it("uses th for the teens and the right suffix elsewhere", () => {
    expect([1, 2, 3, 4, 11, 12, 13, 21, 41, 102].map(formatOrdinal)).toEqual([
      "1st",
      "2nd",
      "3rd",
      "4th",
      "11th",
      "12th",
      "13th",
      "21st",
      "41st",
      "102nd",
    ]);
  });
});

describe("sharePct", () => {
  it("never rounds a real loss down to nothing or up to everything", () => {
    expect(sharePct(1, 1000)).toBe(1);
    expect(sharePct(999, 1000)).toBe(99);
    expect(sharePct(0, 1000)).toBe(0);
    expect(sharePct(1000, 1000)).toBe(100);
    expect(sharePct(5, 0)).toBe(0);
  });
});

describe("servedHouseholds", () => {
  it("sums households whose nearest pharmacy is this store", () => {
    expect(servedHouseholds(data, "in")).toBe(100);
    expect(servedHouseholds(data, "buf")).toBe(0);
  });
});

describe("closureRank", () => {
  it("ranks only study-area pharmacies", () => {
    const rank = closureRank(data, "in", pace, 15);
    expect(rank).toEqual({ rank: 1, of: 2 });
  });
});

describe("exampleClosurePharmacy", () => {
  it("picks the highest newly-lost impact pharmacy deterministically", () => {
    const example = exampleClosurePharmacy(data, pace, 15);
    expect(example?.id).toBe("in");
    expect(example?.simulatable).toBe(true);
  });
});

describe("isNewlyLost", () => {
  it("flags cells that cross the threshold after closure", () => {
    expect(isNewlyLost(data.hexes[0], "in", pace.mps, 15)).toBe(true);
    expect(isNewlyLost(data.hexes[1], "in", pace.mps, 15)).toBe(false);
  });
});

describe("searchPharmacies", () => {
  it("omits buffer pharmacies from the primary search", () => {
    expect(searchPharmacies(data.pharmacies, "").map((p) => p.id)).toEqual(["in", "low"]);
    expect(searchPharmacies(data.pharmacies, "Quincy")).toEqual([]);
  });
});
