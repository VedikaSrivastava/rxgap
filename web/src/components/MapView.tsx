import { useEffect, useMemo, useRef } from "react";
import * as maplibregl from "maplibre-gl";
import { cellToBoundary } from "h3-js";
import { hexAccess } from "../lib/metrics";
import { minutesColor, minutesOpacity } from "../lib/colors";
import type { Pace, Pharmacy, RxGapData } from "../lib/types";
import "maplibre-gl/dist/maplibre-gl.css";

const BASEMAP: maplibregl.StyleSpecification = {
  version: 8,
  sources: {
    esri: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
      attribution: "Tiles © Esri",
    },
    labels: {
      type: "raster",
      tiles: [
        "https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Reference/MapServer/tile/{z}/{y}/{x}",
      ],
      tileSize: 256,
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
  data: RxGapData,
  closedId: string | null,
  mps: number,
  threshold: number,
) {
  return {
    type: "FeatureCollection" as const,
    features: data.hexes.map((hex) => {
      const access = hexAccess(hex, closedId, mps);
      const base = hexAccess(hex, null, mps);
      const newlyLost =
        Boolean(closedId) &&
        hex.nearestId === closedId &&
        base.minutes != null &&
        base.minutes <= threshold &&
        (access.minutes == null || access.minutes > threshold);
      return {
        type: "Feature" as const,
        properties: {
          color: minutesColor(access.minutes, threshold, newlyLost, Boolean(closedId)),
          opacity: minutesOpacity(hex.households, newlyLost, Boolean(closedId)),
        },
        geometry: { type: "Polygon" as const, coordinates: [hexRing(hex.h3)] },
      };
    }),
  };
}

function markerClass(p: Pharmacy, selectedId: string | null, altIds: Set<string>, simulating: boolean) {
  if (p.id === selectedId) return simulating ? "pharm-dot is-closed" : "pharm-dot is-selected";
  if (altIds.has(p.id)) return "pharm-dot is-alt";
  return "pharm-dot";
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
  const markersRef = useRef<maplibregl.Marker[]>([]);
  const onSelectRef = useRef(onSelect);
  onSelectRef.current = onSelect;

  const closedId = simulating ? selectedId : null;
  const hexes = useMemo(
    () => hexCollection(data, closedId, pace.mps, threshold),
    [data, closedId, pace.mps, threshold],
  );
  const hexesRef = useRef(hexes);
  hexesRef.current = hexes;

  useEffect(() => {
    const el = rootRef.current;
    if (!el || mapRef.current) return;

    const map = new maplibregl.Map({
      container: el,
      style: BASEMAP,
      center: [-71.105, 42.36],
      zoom: 12.1,
      attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "bottom-right");

    const addHexes = () => {
      if (map.getSource("hexes")) return;
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
          paint: { "line-color": "#1b2430", "line-opacity": 0.08, "line-width": 0.4 },
        },
        "labels",
      );
      map.resize();
    };

    map.on("load", addHexes);
    const ro = new ResizeObserver(() => map.resize());
    ro.observe(el);
    requestAnimationFrame(() => map.resize());
    mapRef.current = map;
    return () => {
      ro.disconnect();
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
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
    if (!map) return;
    const alts = new Set(altIds);
    markersRef.current.forEach((m) => m.remove());
    markersRef.current = data.pharmacies.map((p) => {
      const el = document.createElement("button");
      el.type = "button";
      el.className = markerClass(p, selectedId, alts, simulating);
      el.title = p.name;
      el.addEventListener("click", () => onSelectRef.current(p.id));
      return new maplibregl.Marker({ element: el, anchor: "center" })
        .setLngLat([p.lon, p.lat])
        .addTo(map);
    });
    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
    };
  }, [data.pharmacies, selectedId, altIds, simulating]);

  useEffect(() => {
    const map = mapRef.current;
    const p = data.pharmacies.find((x) => x.id === selectedId);
    if (!map || !p) return;
    map.easeTo({ center: [p.lon, p.lat], zoom: Math.max(map.getZoom(), 13), duration: 650 });
  }, [selectedId, data.pharmacies]);

  return <div ref={rootRef} className="map" />;
}
