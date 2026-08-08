"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl, { type Map as MapLibreMap } from "maplibre-gl";

import type { AreaOfInterest } from "@/lib/types";

const TILE_URL =
  process.env.NEXT_PUBLIC_BASEMAP_TILE_URL ??
  "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const ATTRIBUTION =
  process.env.NEXT_PUBLIC_BASEMAP_ATTRIBUTION ?? "© OpenStreetMap contributors";

interface CityMapProps {
  area: AreaOfInterest;
  /** Extent of ingested geometry, or null when nothing has been ingested. */
  dataExtent: [number, number, number, number] | null;
}

/**
 * The command centre basemap.
 *
 * It draws the configured area of interest and nothing else. Risk and road
 * layers are added in Phase 3/4 from real predictions — the map deliberately
 * shows no coloured overlay today, because any overlay now would be decoration
 * standing in for analysis that has not happened.
 */
export function CityMap({ area, dataExtent }: CityMapProps) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<MapLibreMap | null>(null);
  const [tilesFailed, setTilesFailed] = useState(false);

  useEffect(() => {
    if (map.current || !container.current) return;

    const instance = new maplibregl.Map({
      container: container.current,
      style: {
        version: 8,
        sources: {
          basemap: {
            type: "raster",
            tiles: [TILE_URL],
            tileSize: 256,
            attribution: ATTRIBUTION,
            maxzoom: 19,
          },
        },
        layers: [
          { id: "background", type: "background", paint: { "background-color": "#0d1119" } },
          {
            id: "basemap",
            type: "raster",
            source: "basemap",
            // Dimmed and desaturated so the risk overlays added in Phase 3
            // remain the most salient thing on the map rather than competing
            // with basemap colour.
            paint: {
              "raster-opacity": 0.65,
              "raster-saturation": -0.6,
              "raster-brightness-max": 0.82,
              "raster-contrast": -0.05,
            },
          },
        ],
      },
      center: area.center,
      zoom: area.default_zoom,
      attributionControl: { compact: true },
    });

    instance.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    instance.addControl(new maplibregl.ScaleControl({ unit: "metric" }), "bottom-left");

    instance.on("error", (event) => {
      // Tile requests fail on an offline machine; the map still renders, and
      // the banner below says so rather than leaving a blank grey square.
      if (event.error && String(event.error.message ?? "").includes("Failed to fetch")) {
        setTilesFailed(true);
      }
    });

    instance.on("load", () => {
      // Outline the configured area of interest.
      const [minLon, minLat, maxLon, maxLat] = area.bbox;
      instance.addSource("aoi", {
        type: "geojson",
        data: {
          type: "Feature",
          properties: {},
          geometry: {
            type: "Polygon",
            coordinates: [
              [
                [minLon, minLat],
                [maxLon, minLat],
                [maxLon, maxLat],
                [minLon, maxLat],
                [minLon, minLat],
              ],
            ],
          },
        },
      });
      instance.addLayer({
        id: "aoi-fill",
        type: "fill",
        source: "aoi",
        paint: { "fill-color": "#38bdf8", "fill-opacity": 0.05 },
      });
      instance.addLayer({
        id: "aoi-outline",
        type: "line",
        source: "aoi",
        paint: { "line-color": "#38bdf8", "line-width": 1.5, "line-dasharray": [3, 2] },
      });

      // Prefer real ingested geometry over the configured bounds when it exists.
      const bounds = dataExtent ?? area.bbox;
      instance.fitBounds(
        [
          [bounds[0], bounds[1]],
          [bounds[2], bounds[3]],
        ],
        { padding: 48, duration: 0 },
      );
    });

    map.current = instance;
    return () => {
      instance.remove();
      map.current = null;
    };
  }, [area, dataExtent]);

  return (
    <div className="relative size-full">
      <div ref={container} className="size-full" />

      <div className="pointer-events-none absolute left-4 top-4 space-y-2">
        <div className="pointer-events-auto rounded border border-ground-700 bg-ground-900/90 px-3 py-2 backdrop-blur">
          <p className="font-mono text-[11px] uppercase tracking-widest text-ink-500">
            Area of interest
          </p>
          <p className="text-sm font-medium text-ink-100">
            {area.city_name}, {area.country_code}
          </p>
          <p className="font-mono text-[11px] text-ink-500">
            {area.bbox.map((v) => v.toFixed(3)).join(", ")}
          </p>
        </div>

        {!dataExtent && (
          <div className="pointer-events-auto max-w-xs rounded border border-signal-warn/40 bg-signal-warn/10 px-3 py-2">
            <p className="text-xs leading-relaxed text-signal-warn">
              No geometry ingested yet. The outline is the configured bounding box, not
              mapped city data.
            </p>
          </div>
        )}

        {tilesFailed && (
          <div className="pointer-events-auto max-w-xs rounded border border-signal-down/40 bg-signal-down/10 px-3 py-2">
            <p className="text-xs leading-relaxed text-signal-down">
              Basemap tiles could not be loaded. Check network access to the tile server.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
