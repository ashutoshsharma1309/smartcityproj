"""KML reader.

Every geospatial dataset published by Greater Chennai Corporation is KML, so
this parser carries most of the ingestion weight.

It uses the standard library's ``ElementTree`` rather than GDAL/fiona. KML is
plain XML and the subset used by these files is small, so a dependency on a
compiled geospatial stack would buy nothing and would bloat the API image that
shares this package.

Two details of real GCC files are handled explicitly:

* Attributes live in ``ExtendedData/SchemaData/SimpleData``, not in ``<name>``.
* Features are frequently ``MultiGeometry`` — the road layer has 20,407
  placemarks containing 36,922 LineStrings — so a placemark can legitimately
  yield several geometries.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
from xml.etree import ElementTree

from app.services.data_ingestion.geometry import (
    Coordinate,
    GeometryError,
    linestring_wkt,
    multipolygon_wkt,
    parse_kml_coordinates,
    point_wkt,
    polygon_wkt,
)

KML_NS = "{http://www.opengis.net/kml/2.2}"


@dataclass(slots=True)
class KMLPlacemark:
    name: str | None
    #: Merged ``SimpleData`` and ``Data`` attributes.
    properties: dict[str, Any] = field(default_factory=dict)
    #: One entry per geometry found; a MultiGeometry yields several.
    geometries: list[tuple[str, str]] = field(default_factory=list)
    #: Reason this placemark produced no usable geometry, if any.
    error: str | None = None


def _localname(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ElementTree.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    value = element.text.strip()
    return value or None


def _extract_properties(placemark: ElementTree.Element) -> dict[str, Any]:
    """Read ExtendedData attributes in both KML dialects."""
    properties: dict[str, Any] = {}
    for extended in placemark.iter():
        tag = _localname(extended.tag)
        if tag == "SimpleData":
            key = extended.get("name")
            if key:
                properties[key] = _text(extended)
        elif tag == "Data":
            key = extended.get("name")
            if key:
                value_el = next(
                    (c for c in extended if _localname(c.tag) == "value"), None
                )
                properties[key] = _text(value_el)
    return properties


def _polygon_from_element(polygon: ElementTree.Element) -> str:
    outer: list[Coordinate] = []
    inners: list[list[Coordinate]] = []

    for child in polygon.iter():
        tag = _localname(child.tag)
        if tag not in ("outerBoundaryIs", "innerBoundaryIs"):
            continue
        coords_el = next(
            (c for c in child.iter() if _localname(c.tag) == "coordinates"), None
        )
        text = _text(coords_el)
        if not text:
            continue
        ring = parse_kml_coordinates(text)
        if tag == "outerBoundaryIs":
            if not outer:
                outer = ring
        else:
            inners.append(ring)

    if not outer:
        raise GeometryError("polygon_missing_outer_ring")
    return polygon_wkt(outer, inners)


def _geometries_from(element: ElementTree.Element) -> list[tuple[str, str]]:
    """Collect (geometry_type, wkt) pairs beneath a placemark."""
    found: list[tuple[str, str]] = []

    for node in element.iter():
        tag = _localname(node.tag)

        if tag == "Point":
            coords_el = next(
                (c for c in node.iter() if _localname(c.tag) == "coordinates"), None
            )
            text = _text(coords_el)
            if text:
                lon, lat = parse_kml_coordinates(text)[0]
                found.append(("Point", point_wkt(lon, lat)))

        elif tag == "LineString":
            coords_el = next(
                (c for c in node.iter() if _localname(c.tag) == "coordinates"), None
            )
            text = _text(coords_el)
            if text:
                found.append(("LineString", linestring_wkt(parse_kml_coordinates(text))))

        elif tag == "Polygon":
            found.append(("Polygon", _polygon_from_element(node)))

    return found


def iter_placemarks(payload: bytes) -> Iterator[KMLPlacemark]:
    """Stream placemarks from a KML document.

    ``iterparse`` with element clearing keeps memory flat: the road centreline
    file is 21 MB and would otherwise be held as a full DOM.
    """
    source = ElementTree.iterparse(_BytesReader(payload), events=("end",))

    for _event, element in source:
        if _localname(element.tag) != "Placemark":
            continue

        name_el = next((c for c in element if _localname(c.tag) == "name"), None)
        placemark = KMLPlacemark(
            name=_text(name_el),
            properties=_extract_properties(element),
        )
        try:
            placemark.geometries = _geometries_from(element)
            if not placemark.geometries:
                placemark.error = "no_geometry"
        except GeometryError as exc:
            placemark.error = str(exc)
        except Exception as exc:  # noqa: BLE001 - one bad placemark must not stop the file
            placemark.error = f"parse_error:{type(exc).__name__}"

        yield placemark
        element.clear()


def merge_polygons(geometries: list[tuple[str, str]]) -> str | None:
    """Combine a placemark's polygons into a single MULTIPOLYGON.

    GCC publishes several wards as multi-part placemarks (200 placemarks
    contain 209 polygons), and a ward is one zone regardless of how many
    disjoint pieces it has.
    """
    polygons = [wkt for kind, wkt in geometries if kind == "Polygon"]
    if not polygons:
        return None
    return multipolygon_wkt(polygons)


class _BytesReader:
    """Minimal file-like wrapper so ``iterparse`` can read an in-memory payload."""

    __slots__ = ("_data", "_pos")

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            chunk = self._data[self._pos :]
            self._pos = len(self._data)
            return chunk
        chunk = self._data[self._pos : self._pos + size]
        self._pos += len(chunk)
        return chunk
