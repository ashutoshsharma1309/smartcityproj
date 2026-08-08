"""City registry.

Cities are rows, not configuration constants. That is what makes the platform
portable: adding Bengaluru means inserting a row and pointing catalogue entries
at it, with no code change and no second deployment.

Every spatial table carries a ``city_id`` so a single database can hold several
cities without their geometries mixing in a spatial query.
"""

from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import Float, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin

SRID = 4326


class City(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "cities"
    __table_args__ = (Index("ix_cities_boundary", "boundary", postgresql_using="gist"),)

    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    country_code: Mapped[str] = mapped_column(String(2), nullable=False)
    #: IANA timezone; rainfall aggregation windows are local-day based.
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="UTC")

    # Bounding box in EPSG:4326. Stored as plain columns rather than a geometry
    # because it is configuration for API and map defaults, not something the
    # spatial queries join against.
    min_lon: Mapped[float] = mapped_column(Float, nullable=False)
    min_lat: Mapped[float] = mapped_column(Float, nullable=False)
    max_lon: Mapped[float] = mapped_column(Float, nullable=False)
    max_lat: Mapped[float] = mapped_column(Float, nullable=False)
    center_lon: Mapped[float] = mapped_column(Float, nullable=False)
    center_lat: Mapped[float] = mapped_column(Float, nullable=False)
    default_zoom: Mapped[float] = mapped_column(Float, nullable=False, default=10.5)

    #: Dissolved administrative boundary, populated once ward geometry lands.
    boundary: Mapped[object | None] = mapped_column(
        Geometry(geometry_type="MULTIPOLYGON", srid=SRID, spatial_index=False), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<City {self.slug}>"
