import { describe, expect, it } from "vitest";
import { closureRank, impact, servedHouseholds, weightedMedian } from "./metrics";
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

describe("servedHouseholds", () => {
  it("sums households whose nearest pharmacy is this store", () => {
    expect(servedHouseholds(data, "in")).toBe(100);
    expect(servedHouseholds(data, "buf")).toBe(0);
  });
});

describe("closureRank", () => {
  it("ranks only study-area pharmacies", () => {
    const rank = closureRank(data, "in", pace, 15);
    expect(rank).toEqual({ rank: 1, of: 1 });
  });
});
