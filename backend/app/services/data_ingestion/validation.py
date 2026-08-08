"""Record validation.

Validation is split by what each layer is actually good at:

* **Python (here):** required fields, numeric types, coordinate ranges,
  timestamp plausibility, duplicate detection, area-of-interest containment.
  Cheap, unit-testable, and it stops bad data before it reaches the database.
* **PostGIS (at insert):** topological validity and repair. ``ST_MakeValid``
  is the authoritative implementation; reimplementing it in Python would risk
  the two disagreeing about the same polygon.

Every rejection is attributed to a named reason and counted. Nothing is dropped
silently — that is the whole point of the stage.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from datetime import UTC, datetime
from typing import Any

from app.services.data_ingestion.base import IngestionResult, SourceFeature
from app.services.data_ingestion.geometry import bbox_contains

#: Timestamps outside this window are structurally impossible for this project
#: and almost always indicate an epoch/format error rather than real data.
MIN_PLAUSIBLE_YEAR = 1900
MAX_PLAUSIBLE_YEAR = 2100


class Rejection(Exception):
    """Raised by a rule to reject a feature with a named reason."""

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def require_geometry(feature: SourceFeature) -> None:
    if not feature.geometry_wkt:
        raise Rejection("missing_geometry")


def require_fields(feature: SourceFeature, fields: Iterable[str]) -> None:
    for name in fields:
        value = feature.properties.get(name)
        if value is None or (isinstance(value, str) and not value.strip()):
            raise Rejection(f"missing_field:{name}")


def coerce_float(
    feature: SourceFeature,
    field: str,
    *,
    required: bool = False,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float | None:
    raw = feature.properties.get(field)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        if required:
            raise Rejection(f"missing_field:{field}")
        return None
    try:
        value = float(raw)
    except (TypeError, ValueError) as exc:
        raise Rejection(f"non_numeric:{field}") from exc

    # Out-of-range values are rejected rather than clipped: a clipped value
    # looks like a measurement but is not one.
    if minimum is not None and value < minimum:
        raise Rejection(f"out_of_range:{field}")
    if maximum is not None and value > maximum:
        raise Rejection(f"out_of_range:{field}")
    return value


def coerce_int(feature: SourceFeature, field: str, *, maximum: int | None = None) -> int | None:
    raw = feature.properties.get(field)
    if raw is None or (isinstance(raw, str) and not raw.strip()):
        return None
    try:
        # OSM publishes "2" and occasionally "2;3" for lanes; take the leading
        # integer rather than discarding the whole record.
        text = str(raw).split(";")[0].strip()
        value = int(float(text))
    except (TypeError, ValueError):
        return None
    if maximum is not None and value > maximum:
        return None
    return value


def validate_timestamp(value: datetime | None, *, field: str = "timestamp") -> datetime | None:
    if value is None:
        return None
    if not (MIN_PLAUSIBLE_YEAR <= value.year <= MAX_PLAUSIBLE_YEAR):
        raise Rejection(f"implausible_timestamp:{field}")
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    # A far-future observation is a parsing error, not a measurement. Forecasts
    # are handled separately and are never routed through this check.
    if value > datetime.now(UTC).replace(year=datetime.now(UTC).year + 2):
        raise Rejection(f"implausible_timestamp:{field}")
    return value


def require_within_bbox(
    feature: SourceFeature, bbox: list[float] | tuple[float, ...], *, margin: float = 0.25
) -> None:
    """Reject features that fall outside the city's area of interest.

    Some published layers cover an entire district rather than the corporation
    area. A generous margin is used because the point is to catch gross errors
    — a swapped lat/lon lands thousands of kilometres away — not to clip the
    dataset to an exact administrative edge.
    """
    wkt = feature.geometry_wkt
    if not wkt:
        raise Rejection("missing_geometry")

    body = wkt[wkt.index("(") :].strip("()")
    first = body.replace("(", " ").replace(",", " ").split()
    try:
        lon, lat = float(first[0]), float(first[1])
    except (IndexError, ValueError) as exc:
        raise Rejection("unparseable_geometry") from exc

    if not bbox_contains(bbox, lon, lat, margin=margin):
        raise Rejection("outside_area_of_interest")


class DuplicateTracker:
    """Detects repeated external ids within a single ingestion run.

    Counted separately from rejections: a duplicate is usually a publisher
    quirk (the same feature split across placemarks) rather than bad data.
    """

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def is_duplicate(self, key: str | None) -> bool:
        if key is None:
            return False
        if key in self._seen:
            return True
        self._seen.add(key)
        return False

    def __len__(self) -> int:
        return len(self._seen)


def run_rules(
    features: Iterable[SourceFeature],
    rules: Iterable[Any],
    result: IngestionResult,
    *,
    duplicate_key: Any = None,
) -> Iterator[SourceFeature]:
    """Apply rules to a feature stream, recording every outcome on ``result``.

    Yields only the features that pass, but every input is accounted for in
    ``records_received``, ``records_valid``, ``duplicates`` or
    ``rejection_reasons``.
    """
    rules = list(rules)
    tracker = DuplicateTracker()

    for feature in features:
        result.records_received += 1

        if feature.rejection_reason:
            result.reject(feature.rejection_reason)
            continue

        try:
            for rule in rules:
                rule(feature)
        except Rejection as rejection:
            feature.rejection_reason = rejection.reason
            result.reject(rejection.reason)
            continue

        if duplicate_key is not None:
            key = duplicate_key(feature)
            if tracker.is_duplicate(key):
                result.duplicates += 1
                result.reject("duplicate_external_id")
                continue

        result.records_valid += 1
        yield feature
