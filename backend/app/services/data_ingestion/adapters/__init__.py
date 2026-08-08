"""Adapter registry.

The catalogue names an adapter class per dataset; this maps that name to the
implementation. Registering a new source is a catalogue entry plus one line
here — nothing else in the pipeline changes.
"""

from __future__ import annotations

from app.services.data_ingestion.adapters.flood import (
    FloodEventPointAdapter,
    InundationPointAdapter,
)
from app.services.data_ingestion.adapters.osm import OverpassRoadAdapter
from app.services.data_ingestion.adapters.traffic import UnavailableTrafficAdapter
from app.services.data_ingestion.adapters.vector import (
    DrainageAdapter,
    RoadCenterlineAdapter,
    WardBoundaryAdapter,
    WaterbodyAdapter,
    WatershedAdapter,
)
from app.services.data_ingestion.adapters.weather import (
    OpenMeteoArchiveAdapter,
    OpenMeteoElevationAdapter,
    OpenMeteoForecastAdapter,
)
from app.services.data_ingestion.base import BaseDataSource

ADAPTERS: dict[str, type[BaseDataSource]] = {
    "WardBoundaryAdapter": WardBoundaryAdapter,
    "WatershedAdapter": WatershedAdapter,
    "RoadCenterlineAdapter": RoadCenterlineAdapter,
    "OverpassRoadAdapter": OverpassRoadAdapter,
    "InundationPointAdapter": InundationPointAdapter,
    "FloodEventPointAdapter": FloodEventPointAdapter,
    "DrainageAdapter": DrainageAdapter,
    "WaterbodyAdapter": WaterbodyAdapter,
    "OpenMeteoArchiveAdapter": OpenMeteoArchiveAdapter,
    "OpenMeteoForecastAdapter": OpenMeteoForecastAdapter,
    "OpenMeteoElevationAdapter": OpenMeteoElevationAdapter,
    "TrafficAdapter": UnavailableTrafficAdapter,
}


def get_adapter_class(name: str) -> type[BaseDataSource]:
    try:
        return ADAPTERS[name]
    except KeyError as exc:
        raise KeyError(
            f"Unknown adapter '{name}'. Registered adapters: {sorted(ADAPTERS)}"
        ) from exc


__all__ = ["ADAPTERS", "get_adapter_class"]
