"""Open-Meteo adapters: rainfall history, forecast and elevation.

These differ from the file-based adapters in one important way: there is no
single file to download. Weather is fetched per zone centroid and elevation on
a sampling grid, so both adapters issue many small requests and must be
deliberate about volume.

Two mechanisms keep that honest on a laptop and polite to a free public API:

* Zone centroids are read from the database, so only zones that actually exist
  are queried.
* Elevation is requested in batches of 100 coordinates, which is the documented
  maximum for a single call.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from datetime import UTC, date, datetime
from typing import Any

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.services.data_ingestion.base import BaseDataSource, IngestionResult, SourceFeature
from app.services.data_ingestion.geometry import point_wkt
from app.services.data_ingestion.persistence import (
    DIM_POINT,
    upsert_rows,
    upsert_rows_without_geometry,
)

logger = get_logger(__name__)

#: Open-Meteo accepts up to 100 coordinates per elevation request.
ELEVATION_BATCH = 100

HOURLY_VARIABLES = (
    "precipitation",
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "surface_pressure",
    "soil_moisture_0_to_7cm",
)

#: Physical bounds used to reject impossible readings. Deliberately wide — the
#: goal is catching parse and unit errors, not second-guessing the provider.
BOUNDS: dict[str, tuple[float, float]] = {
    "precipitation": (0.0, 500.0),
    "temperature_2m": (-40.0, 60.0),
    "relative_humidity_2m": (0.0, 100.0),
    "wind_speed_10m": (0.0, 150.0),
    "surface_pressure": (800.0, 1100.0),
    "soil_moisture_0_to_7cm": (0.0, 1.0),
}

COLUMN_FOR_VARIABLE = {
    "precipitation": "precipitation_mm",
    "temperature_2m": "temperature_c",
    "relative_humidity_2m": "relative_humidity_pct",
    "wind_speed_10m": "wind_speed_ms",
    "surface_pressure": "surface_pressure_hpa",
    "soil_moisture_0_to_7cm": "soil_moisture_frac",
}


async def zone_centroids(
    session: AsyncSession, *, city_id: Any, zone_type: str = "ward"
) -> list[dict[str, Any]]:
    """Zone ids with their centroid coordinates.

    ``ST_PointOnSurface`` rather than ``ST_Centroid``: a centroid can fall
    outside a concave or multi-part ward, which would query weather for the
    wrong place.
    """
    result = await session.execute(
        text(
            """
            SELECT id,
                   ST_X(ST_PointOnSurface(geom)) AS lon,
                   ST_Y(ST_PointOnSurface(geom)) AS lat
            FROM zones
            WHERE city_id = :city_id AND zone_type = :zone_type
            ORDER BY external_id
            """
        ),
        {"city_id": city_id, "zone_type": zone_type},
    )
    return [{"zone_id": r.id, "lon": float(r.lon), "lat": float(r.lat)} for r in result]


class _OpenMeteoBase(BaseDataSource):
    """Shared HTTP behaviour. Fetching happens per zone, not as one file."""

    category = "weather"

    async def resolve_url(self) -> str:
        return str(self.config["access"]["base_url"])

    def parse(self, payload: bytes) -> Iterator[SourceFeature]:  # pragma: no cover - unused
        raise NotImplementedError(
            "Open-Meteo adapters fetch per zone; use ingest_weather() instead of parse()."
        )

    async def persist(self, *args: Any, **kwargs: Any) -> None:  # pragma: no cover - unused
        raise NotImplementedError("Open-Meteo adapters persist inside their own ingest method.")

    async def _get_json(self, client: httpx.AsyncClient, params: dict[str, Any]) -> dict[str, Any]:
        response = await client.get(await self.resolve_url(), params=params)
        response.raise_for_status()
        return response.json()


class OpenMeteoArchiveAdapter(_OpenMeteoBase):
    """ERA5 reanalysis history, one request per zone centroid."""

    is_forecast = False

    async def ingest_weather(
        self,
        session: AsyncSession,
        *,
        data_source_id: Any,
        city_id: Any,
        start_date: date,
        end_date: date,
        result: IngestionResult,
        zone_type: str = "ward",
        max_zones: int | None = None,
    ) -> None:
        zones = await zone_centroids(session, city_id=city_id, zone_type=zone_type)
        if not zones:
            result.error = (
                "No zones ingested yet — weather is keyed to zone centroids, "
                "so boundaries must be ingested first."
            )
            return

        if max_zones is not None:
            # Bounded runs keep development cheap; the cap is reported rather
            # than silently applied so coverage is never overstated.
            if len(zones) > max_zones:
                logger.info("weather_zone_cap_applied", requested=len(zones), cap=max_zones)
                result.rejection_reasons["zones_skipped_by_cap"] = len(zones) - max_zones
            zones = zones[:max_zones]

        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for zone in zones:
                params = {
                    "latitude": zone["lat"],
                    "longitude": zone["lon"],
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "hourly": ",".join(HOURLY_VARIABLES),
                    "timezone": "UTC",
                }
                try:
                    payload = await self._get_json(client, params)
                except httpx.HTTPError as exc:
                    result.reject("upstream_request_failed")
                    logger.warning("weather_fetch_failed", zone=str(zone["zone_id"]), error=str(exc))
                    continue

                rows.extend(
                    self._rows_from_payload(
                        payload,
                        zone_id=zone["zone_id"],
                        data_source_id=data_source_id,
                        result=result,
                    )
                )

        written = await upsert_rows_without_geometry(
            session,
            table="weather_observations",
            columns=[
                "data_source_id",
                "zone_id",
                "observed_at",
                "is_forecast",
                *COLUMN_FOR_VARIABLE.values(),
            ],
            conflict_columns=["zone_id", "observed_at", "data_source_id"],
            update_columns=list(COLUMN_FOR_VARIABLE.values()),
            rows=rows,
        )
        result.records_written = written

    def _rows_from_payload(
        self,
        payload: dict[str, Any],
        *,
        zone_id: Any,
        data_source_id: Any,
        result: IngestionResult,
    ) -> list[dict[str, Any]]:
        hourly = payload.get("hourly") or {}
        times = hourly.get("time") or []
        rows: list[dict[str, Any]] = []

        for index, stamp in enumerate(times):
            result.records_received += 1
            try:
                observed_at = datetime.fromisoformat(stamp).replace(tzinfo=UTC)
            except ValueError:
                result.reject("unparseable_timestamp")
                continue

            row: dict[str, Any] = {
                "data_source_id": data_source_id,
                "zone_id": zone_id,
                "observed_at": observed_at,
                "is_forecast": self.is_forecast,
            }
            rejected = False
            for variable, column in COLUMN_FOR_VARIABLE.items():
                series = hourly.get(variable) or []
                value = series[index] if index < len(series) else None
                if value is None:
                    row[column] = None
                    continue
                low, high = BOUNDS[variable]
                if not (low <= float(value) <= high):
                    result.reject(f"out_of_range:{variable}")
                    rejected = True
                    break
                row[column] = float(value)

            if rejected:
                continue
            result.records_valid += 1
            rows.append(row)

        return rows


class OpenMeteoForecastAdapter(OpenMeteoArchiveAdapter):
    """Forecast rows, stored with ``is_forecast = true``.

    Kept strictly separate from observations so a forecast can never be used as
    ground truth during training.
    """

    is_forecast = True

    async def ingest_weather(  # type: ignore[override]
        self,
        session: AsyncSession,
        *,
        data_source_id: Any,
        city_id: Any,
        result: IngestionResult,
        forecast_days: int = 3,
        zone_type: str = "ward",
        max_zones: int | None = None,
        **_: Any,
    ) -> None:
        zones = await zone_centroids(session, city_id=city_id, zone_type=zone_type)
        if not zones:
            result.error = "No zones ingested yet; forecast is keyed to zone centroids."
            return
        if max_zones is not None:
            if len(zones) > max_zones:
                result.rejection_reasons["zones_skipped_by_cap"] = len(zones) - max_zones
            zones = zones[:max_zones]

        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for zone in zones:
                params = {
                    "latitude": zone["lat"],
                    "longitude": zone["lon"],
                    "hourly": ",".join(HOURLY_VARIABLES),
                    "forecast_days": forecast_days,
                    "timezone": "UTC",
                }
                try:
                    payload = await self._get_json(client, params)
                except httpx.HTTPError as exc:
                    result.reject("upstream_request_failed")
                    logger.warning("forecast_fetch_failed", error=str(exc))
                    continue
                rows.extend(
                    self._rows_from_payload(
                        payload,
                        zone_id=zone["zone_id"],
                        data_source_id=data_source_id,
                        result=result,
                    )
                )

        result.records_written = await upsert_rows_without_geometry(
            session,
            table="weather_observations",
            columns=[
                "data_source_id",
                "zone_id",
                "observed_at",
                "is_forecast",
                *COLUMN_FOR_VARIABLE.values(),
            ],
            conflict_columns=["zone_id", "observed_at", "data_source_id"],
            update_columns=list(COLUMN_FOR_VARIABLE.values()),
            rows=rows,
        )


class OpenMeteoElevationAdapter(_OpenMeteoBase):
    """Copernicus DEM GLO-90 sampled on a regular grid.

    A point-query API is used instead of downloading DEM tiles: it keeps the
    laptop free of multi-gigabyte rasters and needs no GDAL. The cost is
    resolution — 90 m, sampled at the grid spacing configured here — which is
    recorded as a limitation in the catalogue.
    """

    category = "elevation"

    async def ingest_grid(
        self,
        session: AsyncSession,
        *,
        data_source_id: Any,
        city_id: Any,
        bbox: list[float],
        grid_size: int,
        result: IngestionResult,
    ) -> None:
        min_lon, min_lat, max_lon, max_lat = bbox
        lon_step = (max_lon - min_lon) / (grid_size - 1) if grid_size > 1 else 0.0
        lat_step = (max_lat - min_lat) / (grid_size - 1) if grid_size > 1 else 0.0

        samples: list[tuple[int, int, float, float]] = [
            (row, col, min_lon + col * lon_step, min_lat + row * lat_step)
            for row in range(grid_size)
            for col in range(grid_size)
        ]

        rows: list[dict[str, Any]] = []
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            for start in range(0, len(samples), ELEVATION_BATCH):
                batch = samples[start : start + ELEVATION_BATCH]
                params = {
                    "latitude": ",".join(f"{lat:.6f}" for _, _, _, lat in batch),
                    "longitude": ",".join(f"{lon:.6f}" for _, _, lon, _ in batch),
                }
                try:
                    payload = await self._get_json(client, params)
                except httpx.HTTPError as exc:
                    result.reject("upstream_request_failed", len(batch))
                    logger.warning("elevation_fetch_failed", error=str(exc))
                    continue

                elevations = payload.get("elevation") or []
                for (grid_row, grid_col, lon, lat), elevation in zip(batch, elevations, strict=False):
                    result.records_received += 1
                    if elevation is None:
                        result.reject("missing_elevation")
                        continue
                    # Chennai is coastal and low-lying; anything beyond this
                    # band is a provider or parsing error, not terrain.
                    if not (-100.0 <= float(elevation) <= 9000.0):
                        result.reject("out_of_range:elevation")
                        continue
                    result.records_valid += 1
                    rows.append(
                        {
                            "data_source_id": data_source_id,
                            "city_id": city_id,
                            "grid_row": grid_row,
                            "grid_col": grid_col,
                            "elevation_m": float(elevation),
                            "geom_wkt": point_wkt(lon, lat),
                        }
                    )

        result.records_written = await upsert_rows(
            session,
            table="elevation_points",
            columns=[
                "data_source_id",
                "city_id",
                "grid_row",
                "grid_col",
                "elevation_m",
                "geom",
            ],
            conflict_columns=["city_id", "grid_row", "grid_col"],
            update_columns=["elevation_m", "data_source_id"],
            rows=rows,
            geometry_dimension=DIM_POINT,
        )

    def parse(self, payload: bytes) -> Iterator[SourceFeature]:  # pragma: no cover
        data = json.loads(payload)
        for index, elevation in enumerate(data.get("elevation", [])):
            yield SourceFeature(external_id=str(index), properties={"elevation": elevation})

    async def persist(
        self,
        session: AsyncSession,
        features: Iterable[SourceFeature],
        **kwargs: Any,
    ) -> None:  # pragma: no cover - grid ingestion is the entry point
        raise NotImplementedError("Use ingest_grid().")
