import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";
import { INTRO_SEEN_KEY } from "./lib/intro";
import type { RxGapData } from "./lib/types";

const pace = {
  id: "average" as const,
  label: "Standard",
  mph: 3,
  mps: 1.34112,
  source: "test",
};

const fixture: RxGapData = {
  meta: {
    title: "RxGap",
    subtitle: "",
    cities: ["Boston"],
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
      id: "impactful",
      name: "Impact Pharmacy",
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
      id: "quiet",
      name: "Quiet Pharmacy",
      address: "2 Side St, Boston MA 02118",
      city: "Boston",
      lat: 42.36,
      lon: -71.08,
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
      households: 40,
      lat: 42.35,
      lon: -71.07,
      nearestId: "impactful",
      nearestM: 400,
      secondId: "quiet",
      secondM: 2000,
    },
    {
      h3: "b",
      city: "Boston",
      households: 10,
      lat: 42.36,
      lon: -71.08,
      nearestId: "quiet",
      nearestM: 300,
      secondId: "impactful",
      secondM: 500,
    },
  ],
};

vi.mock("./components/MapView", async () => {
  const { useEffect } = await import("react");
  return {
    MapView: ({
      pulseId,
      onReady,
    }: {
      pulseId?: string | null;
      onReady?: () => void;
    }) => {
      useEffect(() => {
        onReady?.();
      }, [onReady]);
      return <div data-testid="map" data-pulse={pulseId ?? ""} />;
    },
  };
});

describe("App intro onboarding", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const url = String(input);
        if (url.includes("rxgap.json")) {
          return {
            ok: true,
            json: async () => fixture,
          } as Response;
        }
        return { ok: false } as Response;
      }),
    );
  });

  afterEach(() => {
    cleanup();
    localStorage.clear();
    vi.unstubAllGlobals();
  });

  it("shows intro when no localStorage flag exists", async () => {
    render(<App />);
    expect(
      await screen.findByRole("dialog", {
        name: /what happens when a pharmacy permanently closes/i,
      }),
    ).toBeInTheDocument();
  });

  it("stays hidden after dismissal", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("dialog", {
      name: /what happens when a pharmacy permanently closes/i,
    });
    await user.click(screen.getByRole("button", { name: /dismiss intro/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");

    cleanup();
    render(<App />);
    await screen.findByTestId("map");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("reopens from About RxGap", async () => {
    localStorage.setItem(INTRO_SEEN_KEY, "1");
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("button", { name: /about rxgap/i });
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /about rxgap/i }));
    expect(
      screen.getByRole("dialog", {
        name: /what happens when a pharmacy permanently closes/i,
      }),
    ).toBeInTheDocument();
  });

  it("Explore the map dismisses without selecting", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("dialog");
    await user.click(screen.getByRole("button", { name: /explore the map/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: /impact pharmacy/i })).not.toBeInTheDocument();
    expect(localStorage.getItem(INTRO_SEEN_KEY)).toBe("1");
  });

  it("Walk me through an example selects a simulatable pharmacy but does not auto-simulate", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("dialog");
    await user.click(screen.getByRole("button", { name: /walk me through an example/i }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(await screen.findByRole("heading", { name: /impact pharmacy/i })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /simulate permanent closure/i })).toHaveClass("is-nudge");
    expect(screen.queryByRole("button", { name: /undo permanent closure/i })).not.toBeInTheDocument();
    expect(
      screen.getByText(
        /if it closes for good, some of these households would have no pharmacy within a 15-minute walk. simulate to see how many/i,
      ),
    ).toBeInTheDocument();
  });

  it("after simulate, names who loses a walk without implying everyone does", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("dialog");
    await user.click(screen.getByRole("button", { name: /walk me through an example/i }));
    await user.click(await screen.findByRole("button", { name: /simulate permanent closure/i }));
    const panel = screen.getByRole("complementary");
    expect(
      within(panel).getByText(/would have no pharmacy within a 15-minute walk/i),
    ).toBeInTheDocument();
    expect(within(panel).queryByText(/modeled nearest/i)).not.toBeInTheDocument();
    // "lose access" is only safe to say next to the share it is out of, so the
    // panel must always show the covered side and the denominator with it.
    expect(within(panel).getByText(/lose access/i)).toBeInTheDocument();
    expect(within(panel).getByText(/still covered/i)).toBeInTheDocument();
    expect(
      within(panel).getByText(
        /car-free households who rely on this store as their closest walkable pharmacy today/i,
      ),
    ).toBeInTheDocument();
    expect(within(panel).getByText(/how much longer to the next pharmacy/i)).toBeInTheDocument();
    expect(within(panel).getByText(/^typical household$/i)).toBeInTheDocument();
    expect(within(panel).getByText(/^hardest hit$/i)).toBeInTheDocument();
    expect(within(panel).getByText(/where they would walk instead/i)).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /clear this scenario/i })).toBeInTheDocument();
  });

  it("closes on Escape and hands focus back to About RxGap", async () => {
    const user = userEvent.setup();
    render(<App />);
    const dialog = await screen.findByRole("dialog");
    await waitFor(() => expect(dialog).toHaveFocus());
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /about rxgap/i })).toHaveFocus(),
    );
  });

  it("drops the example pulse once step 1 is over", async () => {
    render(<App />);
    await waitFor(() =>
      expect(screen.getByTestId("map")).toHaveAttribute("data-pulse", "impactful"),
    );
    await waitFor(() => expect(screen.getByTestId("map")).toHaveAttribute("data-pulse", ""), {
      timeout: 5000,
    });
  });

  it("keeps the legend out from under the intro card", async () => {
    const user = userEvent.setup();
    render(<App />);
    await screen.findByRole("dialog");
    expect(screen.queryByText(/already too far/i)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /explore the map/i }));
    expect(screen.getByText(/already too far/i)).toBeInTheDocument();
  });
});
