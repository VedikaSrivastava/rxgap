import { useEffect, useMemo, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { cellToBoundary } from "h3-js";
import { hexFill } from "../lib/colors";
import { formatHh, formatWalk, hexAccess, isNewlyLost } from "../lib/metrics";
import type { Pace, Pharmacy, RxGapData } from "../lib/types";
import "maplibre-gl/dist/maplibre-gl.css";

maplibregl.setWorkerUrl(workerUrl);

const MAX_ZOOM = 16;
const CLUSTER_MAX_ZOOM = 12;

const BASEMAP: maplibregl.StyleSpecification = {
  version: 8,
  glyphs: "https://protomaps.github.io/basemaps-assets/fonts/{fontstack}/{range}.pbf",
  sources: {
    esri: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      maxzoom: MAX_ZOOM,
      attribution: "Tiles © Esri",
    },
    labels: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      maxzoom: MAX_ZOOM,
    },
  },
  layers: [
    { id: "esri", type: "raster", source: "esri" },
    { id: "labels", type: "raster", source: "labels" },
  ],
};

type Props = {
  data: RxGapData;
  selectedId: string | null;
  simulating: boolean;
  pace: Pace;
  threshold: number;
  altIds: string[];
  pulseId?: string | null;
  onSelect: (id: string) => void;
  onReady?: () => void;
};

function hexRing(h3: string): number[][] {
  const ring = cellToBoundary(h3, true) as number[][];
  if (!ring.length) return ring;
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) ring.push([first[0], first[1]]);
  return ring;
}

function hexCollection(
  hexes: RxGapData["hexes"],
  rings: number[][][],
  closedId: string | null,
  mps: number,
  threshold: number,
  names: Map<string, string>,
) {
  const simulating = Boolean(closedId);
  return {
    type: "FeatureCollection" as const,
    features: hexes.map((hex, i) => {
      const before = hexAccess(hex, null, mps);
      const access = hexAccess(hex, closedId, mps);
      const newlyLost = isNewlyLost(hex, closedId, mps, threshold);
      const paint = hexFill(
        access.minutes,
        hex.households,
        threshold,
        newlyLost,
        simulating,
      );
      let status = "";
      if (simulating) {
        if (newlyLost) status = "Newly lost";
        else if (access.minutes != null && access.minutes <= threshold) status = "Still walkable";
        else status = "Too far";
      }
      return {
        type: "Feature" as const,
        id: i,
        properties: {
          ...paint,
          inspect: simulating && hex.households > 0 ? 1 : 0,
          status,
          households: hex.households,
          minutes: access.minutes,
          beforeMinutes: before.minutes,
          pharmacy: access.pharmacyId ? names.get(access.pharmacyId) ?? "" : "",
        },
        geometry: { type: "Polygon" as const, coordinates: [rings[i]] },
      };
    }),
  };
}

function pharmacyRole(
  p: Pharmacy,
  selectedId: string | null,
  altIds: Set<string>,
  simulating: boolean,
) {
  if (p.id === selectedId) return simulating ? "closed" : "selected";
  if (altIds.has(p.id)) return "alt";
  if (!p.inStudyArea) return "buffer";
  if (!p.simulatable) return "excluded";
  return "ok";
}

function pharmacyCollection(
  pharmacies: Pharmacy[],
  selectedId: string | null,
  altIds: string[],
  simulating: boolean,
) {
  const alts = new Set(altIds);
  return {
    type: "FeatureCollection" as const,
    features: pharmacies.map((p) => {
      const role = pharmacyRole(p, selectedId, alts, simulating);
      return {
        type: "Feature" as const,
        id: p.id,
        properties: {
          id: p.id,
          name: p.name,
          address: p.address,
          reason: p.excludeReason ?? "",
          role,
          roleLabel:
            role === "closed"
              ? "Permanently closing"
              : role === "alt"
                ? "Next closest"
                : role === "excluded"
                  ? "Can't simulate"
                  : role === "buffer"
                    ? "Nearby context"
                    : "",
        },
        geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
      };
    }),
  };
}

function esc(text: string) {
  return text.replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]!,
  );
}

function numProp(value: unknown): number | null {
  if (value == null || value === "") return null;
  const n = Number(value);
  return Number.isFinite(n) ? n : null;
}

function hexTipHtml(props: Record<string, unknown>): string {
  const status = String(props.status ?? "");
  const hh = numProp(props.households) ?? 0;
  const minutes = numProp(props.minutes);
  const before = numProp(props.beforeMinutes);
  const pharmacy = String(props.pharmacy ?? "");
  const walk =
    before != null && minutes != null && Math.round(before) !== Math.round(minutes)
      ? `${formatWalk(before)} → ${formatWalk(minutes)}`
      : formatWalk(minutes);
  return [
    status ? `<b>${esc(status)}</b>` : "",
    `<span>${esc(formatHh(hh))} no-vehicle households</span>`,
    `<span>Walk ${esc(walk)}</span>`,
    pharmacy ? `<span>${esc(pharmacy)}</span>` : "",
  ]
    .filter(Boolean)
    .join("");
}

function pharmacyTipHtml(props: Record<string, unknown>): string {
  const name = String(props.name ?? "");
  const roleLabel = String(props.roleLabel ?? "");
  const extra = props.reason
    ? String(props.reason)
    : String(props.address ?? "");
  if (roleLabel) {
    return `<b>${esc(roleLabel)}</b><span>${esc(name)}</span>${
      extra ? `<span>${esc(extra)}</span>` : ""
    }`;
  }
  return `<b>${esc(name)}</b>${extra ? `<span>${esc(extra)}</span>` : ""}`;
}

/** Lon/lat bounds from a GeoJSON FeatureCollection (study municipalities). */
function collectionBounds(fc: {
  features?: Array<{ geometry?: { coordinates?: unknown } | null }>;
}): maplibregl.LngLatBounds | null {
  const bounds = new maplibregl.LngLatBounds();
  let empty = true;
  const visit = (coords: unknown) => {
    if (!Array.isArray(coords) || coords.length === 0) return;
    if (typeof coords[0] === "number" && typeof coords[1] === "number") {
      bounds.extend([coords[0] as number, coords[1] as number]);
      empty = false;
      return;
    }
    for (const part of coords) visit(part);
  };
  for (const feature of fc.features ?? []) {
    visit(feature.geometry?.coordinates);
  }
  return empty ? null : bounds;
}

export function MapView({
  data,
  selectedId,
  simulating,
  pace,
  threshold,
  altIds,
  pulseId = null,
  onSelect,
  onReady,
}: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const pulseRef = useRef<maplibregl.Marker | null>(null);
  const onSelectRef = useRef(onSelect);
  const onReadyRef = useRef(onReady);
  const simulatingRef = useRef(simulating);

  const closedId = simulating ? selectedId : null;
  const names = useMemo(
    () => new Map(data.pharmacies.map((p) => [p.id, p.name])),
    [data.pharmacies],
  );
  const rings = useMemo(() => data.hexes.map((hex) => hexRing(hex.h3)), [data.hexes]);
  const hexes = useMemo(
    () => hexCollection(data.hexes, rings, closedId, pace.mps, threshold, names),
    [data.hexes, rings, closedId, pace.mps, threshold, names],
  );
  const pharmacies = useMemo(
    () => pharmacyCollection(data.pharmacies, selectedId, altIds, simulating),
    [data.pharmacies, selectedId, altIds, simulating],
  );
  const hexesRef = useRef(hexes);
  const pharmaciesRef = useRef(pharmacies);

  useEffect(() => {
    onSelectRef.current = onSelect;
    onReadyRef.current = onReady;
    simulatingRef.current = simulating;
    hexesRef.current = hexes;
    pharmaciesRef.current = pharmacies;
  }, [onSelect, onReady, simulating, hexes, pharmacies]);

  useEffect(() => {
    const el = rootRef.current;
    if (!el) return;
    if (mapRef.current) {
      mapRef.current.remove();
      mapRef.current = null;
    }

    const map = new maplibregl.Map({
      container: el,
      style: BASEMAP,
      // Placeholder until cities.geojson loads; fitBounds then frames the 22 municipalities.
      center: [-71.105, 42.324],
      zoom: 9.6,
      maxZoom: MAX_ZOOM,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");
    const popup = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 10,
      className: "pharm-pop",
    });
    popupRef.current = popup;

    let alive = true;
    let readySent = false;
    let readyFallback = 0;
    const signalReady = () => {
      if (!alive || readySent) return;
      readySent = true;
      window.clearTimeout(readyFallback);
      onReadyRef.current?.();
    };
    readyFallback = window.setTimeout(signalReady, 8000);
    const waitUntilPainted = () => {
      if (!alive) return;
      map.once("idle", signalReady);
      map.triggerRepaint();
    };

    const addLayers = () => {
      if (!map.getSource("municipalities")) {
        map.addSource("municipalities", {
          type: "geojson",
          data: { type: "FeatureCollection", features: [] },
        });
        map.addLayer(
          {
            id: "municipality-boundaries",
            type: "line",
            source: "municipalities",
            paint: {
              "line-color": "#1b2431",
              "line-opacity": 0.18,
              "line-width": 1,
            },
          },
          "labels",
        );
        fetch("/data/cities.geojson")
          .then((r) => (r.ok ? r.json() : null))
          .then((fc) => {
            if (!fc || !map.getSource("municipalities")) return;
            (map.getSource("municipalities") as maplibregl.GeoJSONSource).setData(fc);
            const bounds = collectionBounds(fc);
            if (bounds) {
              map.fitBounds(bounds, {
                padding: { top: 56, bottom: 72, left: 28, right: 28 },
                maxZoom: 12,
                duration: 0,
              });
            }
          })
          .catch(() => {
            // Outlines are contextual; map still works without them.
          })
          .finally(waitUntilPainted);
      }
      if (!map.getSource("hexes")) {
        map.addSource("hexes", { type: "geojson", data: hexesRef.current });
        map.addLayer(
          {
            id: "hex-fill",
            type: "fill",
            source: "hexes",
            paint: {
              "fill-color": ["get", "color"],
              "fill-opacity": [
                "case",
                ["boolean", ["feature-state", "hover"], false],
                ["min", 1, ["*", ["get", "opacity"], 1.55]],
                ["get", "opacity"],
              ],
            },
          },
          "labels",
        );
        map.addLayer(
          {
            id: "hex-line",
            type: "line",
            source: "hexes",
            paint: {
              "line-color": "#1b2431",
              "line-opacity": [
                "case",
                ["boolean", ["feature-state", "hover"], false],
                0.72,
                0.07,
              ],
              "line-width": [
                "case",
                ["boolean", ["feature-state", "hover"], false],
                1.8,
                0.4,
              ],
            },
          },
          "labels",
        );
      }
      if (!map.getSource("pharmacies")) {
        map.addSource("pharmacies", {
          type: "geojson",
          data: pharmaciesRef.current,
          promoteId: "id",
          cluster: true,
          clusterMaxZoom: CLUSTER_MAX_ZOOM,
          clusterRadius: 40,
        });
        map.addLayer({
          id: "pharm-clusters",
          type: "circle",
          source: "pharmacies",
          filter: ["has", "point_count"],
          paint: {
            "circle-color": "#1b2431",
            "circle-opacity": 0.85,
            "circle-stroke-width": 1.5,
            "circle-stroke-color": "#fff",
            "circle-radius": ["step", ["get", "point_count"], 12, 4, 15, 10, 19, 25, 24],
          },
        });
        map.addLayer({
          id: "pharm-points",
          type: "circle",
          source: "pharmacies",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-color": [
              "match",
              ["get", "role"],
              "selected",
              "#b4543e",
              "closed",
              "#f7f8fa",
              "alt",
              "#c99a2e",
              "buffer",
              "#b8bec8",
              "excluded",
              "#d5d8de",
              "#1b2431",
            ],
            "circle-radius": [
              "case",
              ["boolean", ["feature-state", "hover"], false],
              ["match", ["get", "role"], "selected", 10, "closed", 10, "alt", 10, 8],
              ["match", ["get", "role"], "selected", 8, "closed", 8, "alt", 8, 6],
            ],
            "circle-stroke-width": [
              "case",
              ["boolean", ["feature-state", "hover"], false],
              ["match", ["get", "role"], "closed", 3.5, "alt", 3, 2.5],
              ["match", ["get", "role"], "closed", 3, "alt", 2.5, 2],
            ],
            "circle-stroke-color": [
              "match",
              ["get", "role"],
              "closed",
              "#b4543e",
              "alt",
              "#fff",
              "excluded",
              "#b8bec8",
              "#fff",
            ],
            "circle-opacity": ["match", ["get", "role"], "buffer", 0.55, "excluded", 0.9, 1],
          },
        });
        // Invisible larger target so pins win over hex fill under the cursor.
        map.addLayer({
          id: "pharm-hit",
          type: "circle",
          source: "pharmacies",
          filter: ["!", ["has", "point_count"]],
          paint: {
            "circle-radius": 16,
            "circle-opacity": 0,
            "circle-stroke-width": 0,
          },
        });
        try {
          map.addLayer({
            id: "pharm-cluster-count",
            type: "symbol",
            source: "pharmacies",
            filter: ["has", "point_count"],
            layout: {
              "text-field": ["to-string", ["get", "point_count"]],
              "text-font": ["Noto Sans Regular"],
              "text-size": 11,
              "text-allow-overlap": true,
            },
            paint: { "text-color": "#fff" },
          });
        } catch {
          // Glyphs are optional; cluster circles still render without counts.
        }
      }
      map.resize();
    };

    if (map.loaded()) addLayers();
    else map.on("load", addLayers);

    let hoveredHexId: number | null = null;
    let hoveredPharmId: string | number | null = null;

    const clearHexHover = () => {
      if (hoveredHexId == null || !map.getSource("hexes")) return;
      map.setFeatureState({ source: "hexes", id: hoveredHexId }, { hover: false });
      hoveredHexId = null;
    };

    const clearPharmHover = () => {
      if (hoveredPharmId == null || !map.getSource("pharmacies")) return;
      map.setFeatureState({ source: "pharmacies", id: hoveredPharmId }, { hover: false });
      hoveredPharmId = null;
    };

    const clearHover = () => {
      clearHexHover();
      clearPharmHover();
      map.getCanvas().style.cursor = "";
      popup.remove();
    };

    map.on("click", "pharm-clusters", (e) => {
      const feature = e.features?.[0];
      if (!feature || feature.geometry.type !== "Point") return;
      const clusterId = feature.properties?.cluster_id;
      const source = map.getSource("pharmacies") as maplibregl.GeoJSONSource;
      const coords = feature.geometry.coordinates as [number, number];
      source.getClusterExpansionZoom(clusterId).then((zoom) => {
        map.easeTo({ center: coords, zoom: Math.min(zoom, MAX_ZOOM), duration: 450 });
      });
    });

    map.on("click", "pharm-hit", (e) => {
      const id = e.features?.[0]?.properties?.id;
      if (id) onSelectRef.current(String(id));
    });
    map.on("click", "pharm-points", (e) => {
      const id = e.features?.[0]?.properties?.id;
      if (id) onSelectRef.current(String(id));
    });

    // Stores first, then hexes — otherwise hex mousemove steals the pin tip.
    map.on("mousemove", (e) => {
      const storeLayers = ["pharm-hit", "pharm-points", "pharm-clusters"].filter((id) =>
        map.getLayer(id),
      );
      const store = storeLayers.length
        ? map.queryRenderedFeatures(e.point, { layers: storeLayers })[0]
        : undefined;

      if (store?.properties && store.geometry.type === "Point") {
        clearHexHover();
        if (store.properties.point_count != null) {
          clearPharmHover();
          map.getCanvas().style.cursor = "pointer";
          popup.remove();
          return;
        }
        const id = (store.id ?? store.properties.id) as string | number;
        if (id != null && id !== hoveredPharmId) {
          clearPharmHover();
          hoveredPharmId = id;
          map.setFeatureState({ source: "pharmacies", id }, { hover: true });
        }
        map.getCanvas().style.cursor = "pointer";
        popup
          .setLngLat(store.geometry.coordinates as [number, number])
          .setHTML(pharmacyTipHtml(store.properties as Record<string, unknown>))
          .addTo(map);
        return;
      }

      clearPharmHover();

      if (!simulatingRef.current || !map.getLayer("hex-fill")) {
        clearHexHover();
        map.getCanvas().style.cursor = "";
        popup.remove();
        return;
      }

      const hex = map.queryRenderedFeatures(e.point, { layers: ["hex-fill"] })[0];
      const props = (hex?.properties ?? {}) as Record<string, unknown>;
      if (!hex || !Number(props.inspect) || hex.id == null) {
        clearHexHover();
        map.getCanvas().style.cursor = "";
        popup.remove();
        return;
      }

      const id = Number(hex.id);
      if (id !== hoveredHexId) {
        clearHexHover();
        hoveredHexId = id;
        map.setFeatureState({ source: "hexes", id }, { hover: true });
      }
      map.getCanvas().style.cursor = "help";
      popup.setLngLat(e.lngLat).setHTML(hexTipHtml(props)).addTo(map);
    });

    map.on("mouseout", clearHover);

    const ro = new ResizeObserver(() => map.resize());
    ro.observe(el);
    requestAnimationFrame(() => map.resize());
    mapRef.current = map;
    return () => {
      alive = false;
      window.clearTimeout(readyFallback);
      ro.disconnect();
      popup.remove();
      popupRef.current = null;
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getSource("hexes")) return;
    (map.getSource("hexes") as maplibregl.GeoJSONSource).setData(hexes);
  }, [hexes]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map?.getSource("pharmacies")) return;
    (map.getSource("pharmacies") as maplibregl.GeoJSONSource).setData(pharmacies);
  }, [pharmacies]);

  useEffect(() => {
    if (!simulating) popupRef.current?.remove();
  }, [simulating]);

  useEffect(() => {
    const map = mapRef.current;
    const p = data.pharmacies.find((x) => x.id === selectedId);
    if (!map || !p) return;
    map.easeTo({
      center: [p.lon, p.lat],
      zoom: Math.min(Math.max(map.getZoom(), CLUSTER_MAX_ZOOM + 1), MAX_ZOOM),
      duration: 650,
    });
  }, [selectedId, data.pharmacies]);

  useEffect(() => {
    const map = mapRef.current;
    pulseRef.current?.remove();
    pulseRef.current = null;
    if (!map || !pulseId) return;
    const p = data.pharmacies.find((x) => x.id === pulseId);
    if (!p) return;
    // MapLibre positions a marker by writing `transform` on this element, so the
    // animation has to live on a child — animating it here would clobber the translate.
    const el = document.createElement("div");
    el.className = "pharm-pulse";
    el.setAttribute("aria-hidden", "true");
    const ring = document.createElement("div");
    ring.className = "pharm-pulse-ring";
    el.appendChild(ring);
    pulseRef.current = new maplibregl.Marker({ element: el, anchor: "center" })
      .setLngLat([p.lon, p.lat])
      .addTo(map);
    return () => {
      pulseRef.current?.remove();
      pulseRef.current = null;
    };
  }, [pulseId, data.pharmacies]);

  return <div ref={rootRef} className="map" />;
}
