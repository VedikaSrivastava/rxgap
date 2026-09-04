/// <reference types="node" />
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

/**
 * MapLibre places a custom marker by writing `transform` on the element it is given
 * (Marker._updateDOM). A CSS animation on that same element overrides the inline
 * style, which strands the marker at the map container's origin instead of the
 * pharmacy. The scaling therefore has to stay on a child element.
 */
describe("intro pulse marker", () => {
  const css = readFileSync("src/index.css", "utf8");
  const mapView = readFileSync("src/components/MapView.tsx", "utf8");

  it("animates a child ring, not the marker element MapLibre positions", () => {
    expect(mapView).toContain("pharm-pulse-ring");
    const ring = css.match(/\.pharm-pulse-ring \{([^}]*)\}/);
    expect(ring?.[1]).toMatch(/animation\s*:/);
  });

  it("never sets transform or animation on the marker element itself", () => {
    const block = css.match(/\.pharm-pulse \{([^}]*)\}/);
    expect(block).not.toBeNull();
    expect(block?.[1]).not.toMatch(/\b(transform|animation)\s*:/);
  });
});

describe("legend swatches", () => {
  const css = readFileSync("src/index.css", "utf8");
  const app = readFileSync("src/App.tsx", "utf8");

  /** A swatch whose class has no rule behind it renders as an invisible blank. */
  it("has a style rule for every class the legend paints with", () => {
    const classes = [...app.matchAll(/<i className="([^"]+)" \/>/g)].flatMap((m) =>
      m[1].split(" "),
    );
    expect(classes.length).toBeGreaterThan(6);
    for (const name of new Set(classes)) {
      expect(css, `.${name} is used in the legend but never styled`).toMatch(
        new RegExp(String.raw`\.${name}\b`),
      );
    }
  });
});
