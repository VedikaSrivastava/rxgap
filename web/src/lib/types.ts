export type PaceId = "slow" | "average" | "brisk";

export type Pace = {
  id: PaceId;
  label: string;
  mph: number;
  mps: number;
  source: string;
};

export type Pharmacy = {
  id: string;
  name: string;
  address: string;
  city: string;
  lat: number;
  lon: number;
  confidence: string;
  cmsRetail: boolean;
};

export type Hex = {
  h3: string;
  city: string;
  households: number;
  lat: number;
  lon: number;
  nearestId: string | null;
  nearestM: number | null;
  secondId: string | null;
  secondM: number | null;
};

export type RxGapData = {
  meta: {
    title: string;
    subtitle: string;
    cities: string[];
    bufferKm: number;
    thresholdMinutes: number;
    defaultPace: PaceId;
    paces: Record<PaceId, Pace>;
    overtureRelease: string;
    acsYear: number;
    demand: string;
    network: string;
    pharmacies: string;
    reports: Record<string, unknown>;
  };
  pharmacies: Pharmacy[];
  hexes: Hex[];
};

export type HexAccess = {
  meters: number | null;
  minutes: number | null;
  pharmacyId: string | null;
};
