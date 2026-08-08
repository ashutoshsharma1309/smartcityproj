"""Coordinate handling and WKT construction.

Geometry work is deliberately split in two:

* **Here (Python):** cheap, purely numeric checks — coordinates finite and in
  range, rings closed, enough vertices to form the claimed shape. These catch
  malformed input before it reaches the database and can be unit-tested with no
  infrastructure.
* **PostGIS:** topological validity (self-intersection, ring orientation) and
  repair via ``ST_MakeValid``. That is where the authoritative geometry engine
  lives, so duplicating it in Python would risk the two disagreeing.

Everything is EPSG:4326 with coordinates ordered longitude, latitude — KML's
native order, and GeoJSON's. Latitude-first input is a common and silent
corruption, so :func:`validate_lonlat` rejects out-of-range values rather than
clamping them.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence

Coordinate = tuple[float, float]

MIN_LON, MAX_LON = -180.0, 180.0
MIN_LAT, MAX_LAT = -90.0, 90.0

#: A ring needs 4 positions because the first and last must coincide.
MIN_RING_POSITIONS = 4
MIN_LINE_POSITIONS = 2


class GeometryError(ValueError):
    """Raised when input cannot form a valid geometry of the expected type."""


def validate_lonlat(lon: float, lat: float) -> Coordinate:
    """Return a validated (lon, lat) pair or raise :class:`GeometryError`."""
    if not (math.isfinite(lon) and math.isfinite(lat)):
        raise GeometryError("coordinate_not_finite")
    if not (MIN_LON <= lon <= MAX_LON):
        raise GeometryError("longitude_out_of_range")
    if not (MIN_LAT <= lat <= MAX_LAT):
        raise GeometryError("latitude_out_of_range")
    # (0, 0) is in the Gulf of Guinea. In a Chennai dataset it always means a
    # missing coordinate that was written as zero rather than left null.
    if lon == 0.0 and lat == 0.0:
        raise GeometryError("null_island_coordinate")
    return (lon, lat)


def parse_kml_coordinates(text: str) -> list[Coordinate]:
    """Parse a KML ``<coordinates>`` block.

    KML tuples are ``lon,lat[,altitude]`` separated by whitespace. Altitude is
    discarded: the platform is 2D, and carrying a third ordinate would silently
    produce POINT Z geometries that do not match the column definitions.
    """
    coordinates: list[Coordinate] = []
    for token in text.replace("\n", " ").replace("\t", " ").split():
        parts = token.split(",")
        if len(parts) < 2:
            continue
        try:
            lon, lat = float(parts[0]), float(parts[1])
        except ValueError as exc:
            raise GeometryError("coordinate_not_numeric") from exc
        coordinates.append(validate_lonlat(lon, lat))
    if not coordinates:
        raise GeometryError("empty_coordinates")
    return coordinates


def _fmt(value: float) -> str:
    # 7 decimal places is ~1 cm at the equator — well beyond any source here,
    # and it keeps WKT payloads small for the 20k-segment road layer.
    return f"{value:.7f}".rstrip("0").rstrip(".")


def _ring(coordinates: Sequence[Coordinate]) -> str:
    return ", ".join(f"{_fmt(lon)} {_fmt(lat)}" for lon, lat in coordinates)


def point_wkt(lon: float, lat: float) -> str:
    lon, lat = validate_lonlat(lon, lat)
    return f"POINT({_fmt(lon)} {_fmt(lat)})"


def linestring_wkt(coordinates: Sequence[Coordinate]) -> str:
    if len(coordinates) < MIN_LINE_POSITIONS:
        raise GeometryError("linestring_too_few_points")
    # A "line" whose vertices are all identical has zero length and would break
    # length and connectivity computations downstream.
    if len(set(coordinates)) < MIN_LINE_POSITIONS:
        raise GeometryError("linestring_degenerate")
    return f"LINESTRING({_ring(coordinates)})"


def close_ring(coordinates: Sequence[Coordinate]) -> list[Coordinate]:
    """Ensure the first and last positions coincide, as WKT requires."""
    ring = list(coordinates)
    if ring and ring[0] != ring[-1]:
        ring.append(ring[0])
    return ring


def polygon_wkt(
    outer: Sequence[Coordinate], inners: Iterable[Sequence[Coordinate]] = ()
) -> str:
    outer_ring = close_ring(outer)
    if len(outer_ring) < MIN_RING_POSITIONS:
        raise GeometryError("polygon_ring_too_few_points")

    rings = [f"({_ring(outer_ring)})"]
    for inner in inners:
        inner_ring = close_ring(inner)
        if len(inner_ring) < MIN_RING_POSITIONS:
            # Skip a malformed hole rather than discarding the whole polygon —
            # the outer boundary is still usable and is the part that matters.
            continue
        rings.append(f"({_ring(inner_ring)})")
    return f"POLYGON({', '.join(rings)})"


def multipolygon_wkt(polygons: Sequence[str]) -> str:
    """Combine POLYGON WKT strings into one MULTIPOLYGON."""
    if not polygons:
        raise GeometryError("empty_multipolygon")
    bodies = [p[len("POLYGON(") : -1] for p in polygons if p.startswith("POLYGON(")]
    if not bodies:
        raise GeometryError("empty_multipolygon")
    return f"MULTIPOLYGON({', '.join(f'({b})' for b in bodies)})"


def multilinestring_parts(wkts: Sequence[str]) -> list[str]:
    """Return the individual LINESTRING WKTs from a list, ignoring blanks."""
    return [w for w in wkts if w.startswith("LINESTRING(")]


def bbox_contains(bbox: Sequence[float], lon: float, lat: float, *, margin: float = 0.0) -> bool:
    """Whether a coordinate falls inside ``[min_lon, min_lat, max_lon, max_lat]``."""
    min_lon, min_lat, max_lon, max_lat = bbox
    return (
        (min_lon - margin) <= lon <= (max_lon + margin)
        and (min_lat - margin) <= lat <= (max_lat + margin)
    )
