"""SQLAlchemy models.

Importing this package registers every table on ``Base.metadata``, which is
what Alembic autogenerate reads.
"""

from app.models.base import Base
from app.models.city import City
from app.models.civic import CivicIncident, ComplaintStatus
from app.models.geography import SRID, DrainageAsset, RoadSegment, Zone
from app.models.hydrology import ElevationPoint, Waterbody
from app.models.observations import (
    FloodIncident,
    FloodRecordType,
    IncidentSeverity,
    TideObservation,
    WeatherObservation,
)
from app.models.provenance import (
    DataOrigin,
    DataSource,
    DataSourceKind,
    IngestionRun,
    IngestionStatus,
)

__all__ = [
    "SRID",
    "Base",
    "City",
    "CivicIncident",
    "ComplaintStatus",
    "DataOrigin",
    "DataSource",
    "DataSourceKind",
    "DrainageAsset",
    "ElevationPoint",
    "FloodIncident",
    "FloodRecordType",
    "IncidentSeverity",
    "IngestionRun",
    "IngestionStatus",
    "RoadSegment",
    "TideObservation",
    "Waterbody",
    "WeatherObservation",
    "Zone",
]
