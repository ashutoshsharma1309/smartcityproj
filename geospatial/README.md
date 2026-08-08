# Geospatial processing

Batch jobs that build the city's geometric representation and write it to
PostGIS. The API only reads the results.

## Why this is offline

Terrain derivation samples a DEM raster over every zone polygon and fills
topographic sinks. That is seconds-to-minutes of CPU per city and needs
rasterio and GeoPandas — neither belongs in a request handler. It runs once per
city, or again when boundaries change, and the API reads the stored columns.

Runtime geometry work that *is* cheap stays in SQL: bounding-box filtering,
`ST_SimplifyPreserveTopology` and `ST_AsGeoJSON` all run inside PostgreSQL, so
the API process never needs GEOS bindings and never ships raw vertices to the
browser.

## Coordinate systems

Everything is stored in **EPSG:4326 (WGS84)** because that is what OSM,
administrative boundary files and MapLibre all expect.

Area, length and distance must never be computed on raw degrees — a degree of
longitude is not a fixed distance. Project first, via `ST_Transform` to a
suitable metric CRS or a `geography` cast. For the first target city that means
**EPSG:32643** (UTM zone 43N).

## Planned jobs (Phase 2)

| Job                    | Input                          | Output                                    |
| ---------------------- | ------------------------------ | ----------------------------------------- |
| `build_zones`          | OSM admin boundaries           | `zones` polygons                          |
| `build_road_network`   | OSM via Overpass               | `road_segments`, zone assignment          |
| `derive_terrain`       | Copernicus DEM GLO-30          | elevation, slope, depression fraction     |
| `derive_urban_form`    | `road_segments`, OSM landuse   | `impervious_fraction`, road density       |
| `build_road_graph`     | `road_segments`                | NetworkX graph cached for impact analysis |
