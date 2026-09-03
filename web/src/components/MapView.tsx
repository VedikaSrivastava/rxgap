import { useEffect, useMemo, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import workerUrl from "maplibre-gl/dist/maplibre-gl-worker.mjs?worker&url";
import { cellToBoundary } from "h3-js";
import { hexFill } from "../lib/colors";
import { hexAccess, isNewlyLost } from "../lib/metrics";
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
  onSelect: (id: string) => void;
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
) {
  const simulating = Boolean(closedId);
  return {
    type: "FeatureCollection" as const,
    features: hexes.map((hex, i) => {
      const access = hexAccess(hex, closedId, mps);
      const paint = hexFill(
        access.minutes,
        hex.households,
        threshold,
        isNewlyLost(hex, closedId, mps, threshold),
        simulating,
      );
      return {
        type: "Feature" as const,
        properties: paint,
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
    features: pharmacies.map((p) => ({
      type: "Feature" as const,
      id: p.id,
      properties: {
        id: p.id,
        name: p.name,
        address: p.address,
        reason: p.excludeReason ?? "",
        role: pharmacyRole(p, selectedId, alts, simulating),
      },
      geometry: { type: "Point" as const, coordinates: [p.lon, p.lat] },
    })),
  };
}

function esc(text: string) {
  return text.replace(/[&<>"']/g, (ch) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[ch]!,
  );
}

export function MapView({
  data,
  selectedId,
  simulating,
  pace,
  threshold,
  altIds,
  onSelect,
}: Props) {
  const rootRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const popupRef = useRef<maplibregl.Popup | null>(null);
  const onSelectRef = useRef(onSelect);

  const closedId = simulating ? selectedId : null;
  const rings = useMemo(() => data.hexes.map((hex) => hexRing(hex.h3)), [data.hexes]);
  const hexes = useMemo(
    () => hexCollection(data.hexes, rings, closedId, pace.mps, threshold),
    [data.hexes, rings, closedId, pace.mps, threshold],
  );
  const pharmacies = useMemo(
    () => pharmacyCollection(data.pharmacies, selectedId, altIds, simulating),
    [data.pharmacies, selectedId, altIds, simulating],
  );
  const hexesRef = useRef(hexes);
  const pharmaciesRef = useRef(pharmacies);

  useEffect(() => {
    onSelectRef.current = onSelect;
    hexesRef.current = hexes;
    pharmaciesRef.current = pharmacies;
  }, [onSelect, hexes, pharmacies]);

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
      center: [-71.10, 42.345],
      zoom: 11.4,
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
              "line-color": "#1b2430",
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
          })
          .catch(() => {
            // Outlines are contextual; map still works without them.
          });
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
              "fill-opacity": ["get", "opacity"],
            },
          },
          "labels",
        );
        map.addLayer(
          {
            id: "hex-line",
            type: "line",
            source: "hexes",
            paint: { "line-color": "#1b2430", "line-opacity": 0.07, "line-width": 0.4 },
          },
          "labels",
        );
      }
      if (!map.getSource("pharmacies")) {
        map.addSource("pharmacies", {
          type: "geojson",
          data: pharmaciesRef.current,
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
            "circle-color": "#1b2430",
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
              "#c4452d",
              "closed",
              "#fff",
              "alt",
              "#2a7a72",
              "buffer",
              "#8a9199",
              "excluded",
              "#9aa3ad",
              "#1b2430",
            ],
            "circle-radius": ["match", ["get", "role"], "selected", 8, "closed", 8, "alt", 7, 6],
            "circle-stroke-width": ["match", ["get", "role"], "closed", 3, 2],
            "circle-stroke-color": ["match", ["get", "role"], "closed", "#c4452d", "#fff"],
            "circle-opacity": ["match", ["get", "role"], "buffer", 0.55, "excluded", 0.8, 1],
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

    map.on("click", "pharm-points", (e) => {
      const id = e.features?.[0]?.properties?.id;
      if (id) onSelectRef.current(String(id));
    });

    map.on("mouseenter", "pharm-clusters", () => {
      map.getCanvas().style.cursor = "pointer";
    });
    map.on("mouseleave", "pharm-clusters", () => {
      map.getCanvas().style.cursor = "";
    });
    map.on("mouseenter", "pharm-points", (e) => {
      map.getCanvas().style.cursor = "pointer";
      const feature = e.features?.[0];
      if (!feature || feature.geometry.type !== "Point") return;
      const props = feature.properties ?? {};
      const extra = props.reason
        ? `<span>${esc(String(props.reason))}</span>`
        : `<span>${esc(String(props.address ?? ""))}</span>`;
      popup
        .setLngLat(feature.geometry.coordinates as [number, number])
        .setHTML(`<b>${esc(String(props.name ?? ""))}</b>${extra}`)
        .addTo(map);
    });
    map.on("mouseleave", "pharm-points", () => {
      map.getCanvas().style.cursor = "";
      popup.remove();
    });

    const ro = new ResizeObserver(() => map.resize());
    ro.observe(el);
    requestAnimationFrame(() => map.resize());
    mapRef.current = map;
    return () => {
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
    const map = mapRef.current;
    const p = data.pharmacies.find((x) => x.id === selectedId);
    if (!map || !p) return;
    map.easeTo({
      center: [p.lon, p.lat],
      zoom: Math.min(Math.max(map.getZoom(), CLUSTER_MAX_ZOOM + 1), MAX_ZOOM),
      duration: 650,
    });
  }, [selectedId, data.pharmacies]);

  return <div ref={rootRef} className="map" />;
}
