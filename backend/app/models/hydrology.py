"""Hydrological features: waterbodies and sampled elevation.

Watersheds are *not* here — they are stored in ``zones`` with
``zone_type='watershed'``. A watershed and a ward are both polygonal analysis
units with the same downstream use, so giving them separate tables would mean
duplicating every spatial query that runs over "an analysis unit".
"""

from __future__ import annotations

import uuid

from geoalchemy2 import Geometry
from sqlalchemy import Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from app.models.city import City
from app.models.geography import SRID
from app.models.provenance import DataSource


class Waterbody(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Lakes, tanks and rivers.

    Waterbodies matter twice over: they absorb runoff, and their margins flood
    first. Distance-to-water is one of the strongest terrain-independent
    predictors of urban waterlogging.
    """

    __tablename__ = "waterbodies"
    __table_args__ = (
        UniqueConstraint("data_source_id", "external_id", name="waterbody_external_id"),
        Index("ix_waterbodies_geom", "geom", postgresql_using="gist"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    external_id: Mapped[str] = mapped_column(String(160), nullable=False)
    name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    #: e.g. "waterbody", "river", "tank". Taken from the source layer, not inferred.
    water_type: Mapped[str] = mapped_column(String(60), nullable=False, default="waterbody")
    area_sq_m: Mapped[float | None] = mapped_column(Float, nullable=True)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="GEOMETRY", srid=SRID, spatial_index=False), nullable=False
    )

    data_source: Mapped[DataSource] = relationship()
    city: Mapped[City] = relationship()


class ElevationPoint(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    """Elevation sampled on a regular grid.

    Stored as points rather than a raster because the source is a point-query
    API (Copernicus DEM GLO-90 via Open-Meteo), which avoids downloading and
    storing DEM tiles on a laptop. Slope is derived from neighbouring samples
    in the transform stage.
    """

    __tablename__ = "elevation_points"
    __table_args__ = (
        UniqueConstraint("city_id", "grid_row", "grid_col", name="elevation_grid_cell"),
        Index("ix_elevation_points_geom", "geom", postgresql_using="gist"),
    )

    data_source_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    city_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cities.id", ondelete="CASCADE"), nullable=False, index=True
    )
    #: Position within the sampling grid, so neighbours can be found without a
    #: spatial join when deriving slope.
    grid_row: Mapped[int] = mapped_column(nullable=False)
    grid_col: Mapped[int] = mapped_column(nullable=False)
    elevation_m: Mapped[float] = mapped_column(Float, nullable=False)
    geom: Mapped[object] = mapped_column(
        Geometry(geometry_type="POINT", srid=SRID, spatial_index=False), nullable=False
    )

    data_source: Mapped[DataSource] = relationship()
    city: Mapped[City] = relationship()
