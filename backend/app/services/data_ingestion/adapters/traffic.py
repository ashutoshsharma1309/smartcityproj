"""Traffic data interface — declared, deliberately unimplemented.

No open traffic feed exists for Chennai, and the commercial APIs that do
(Google, TomTom, HERE) require paid keys whose licences restrict
redistribution. Rather than fabricate volumes or speeds to make a dashboard
look complete, the contract is defined and every call raises.

The shape below is what a provider must satisfy. Adding one is an adapter, not
a schema change.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotImplementedFeatureError
from app.services.data_ingestion.base import BaseDataSource, IngestionResult, SourceFeature


@dataclass(frozen=True, slots=True)
class TrafficObservation:
    """One traffic measurement on one road segment."""

    road_external_id: str
    observed_at: datetime
    #: Vehicles per hour, where the provider reports it.
    volume_vph: int | None
    #: Measured mean speed in km/h.
    speed_kph: float | None
    #: 0.0 free-flowing to 1.0 stationary, as defined by the provider.
    congestion_index: float | None


@runtime_checkable
class TrafficProvider(Protocol):
    """What a future traffic source must implement."""

    name: str

    async def observations(
        self, *, bbox: list[float], since: datetime | None = None
    ) -> Iterable[TrafficObservation]: ...


class UnavailableTrafficAdapter(BaseDataSource):
    """Placeholder that refuses rather than returning invented traffic.

    Kept in the registry so the gap is visible in the catalogue and the API,
    instead of the category simply being absent.
    """

    category = "traffic"

    def parse(self, payload: bytes) -> Iterator[SourceFeature]:
        raise NotImplementedFeatureError(
            "No traffic data source is available for the configured city.",
            module="data_ingestion.traffic",
            planned_phase="Phase 4 (requires a commercial provider key)",
        )

    async def persist(
        self,
        session: AsyncSession,
        features: Iterable[SourceFeature],
        **kwargs: Any,
    ) -> None:
        raise NotImplementedFeatureError(
            "No traffic data source is available for the configured city.",
            module="data_ingestion.traffic",
            planned_phase="Phase 4 (requires a commercial provider key)",
        )
