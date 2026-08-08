"""The feature contract.

One declaration of every model input, used by both the training pipeline and
the inference path. Sharing this module is what prevents training/serving skew:
if a feature is renamed or its unit changes, both sides break together instead
of silently disagreeing.

Nothing here computes a value. It states what the model will consume, where it
comes from, and — critically — whether the platform currently has a source for
it. Features whose source is an unresolved gap in
``data/metadata/data_sources.json`` are marked ``available=False`` so the
roadmap and the code agree about what is actually buildable today.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class FeatureGroup(str, Enum):
    RAINFALL = "rainfall"
    TERRAIN = "terrain"
    HYDROLOGY = "hydrology"
    URBAN_FORM = "urban_form"
    TEMPORAL = "temporal"


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    name: str
    display_name: str
    group: FeatureGroup
    unit: str | None
    #: Slug from the provenance manifest that supplies the raw input.
    source_slug: str
    description: str
    #: False when no registered data source can supply it yet.
    available: bool = True
    #: When a feature may legitimately be missing, the model is trained with
    #: LightGBM's native NaN handling rather than an imputed value — imputing
    #: would invent data.
    nullable: bool = False


FEATURES: tuple[FeatureSpec, ...] = (
    # ------------------------------------------------------------- rainfall
    FeatureSpec(
        name="rain_1h_mm",
        display_name="Rainfall in the last hour",
        group=FeatureGroup.RAINFALL,
        unit="mm",
        source_slug="open-meteo-archive",
        description="Immediate intensity; drives flash surface accumulation.",
    ),
    FeatureSpec(
        name="rain_3h_mm",
        display_name="Rainfall in the last 3 hours",
        group=FeatureGroup.RAINFALL,
        unit="mm",
        source_slug="open-meteo-archive",
        description="Short-burst total, the window over which most urban waterlogging forms.",
    ),
    FeatureSpec(
        name="rain_24h_mm",
        display_name="Rainfall in the last 24 hours",
        group=FeatureGroup.RAINFALL,
        unit="mm",
        source_slug="open-meteo-archive",
        description="Daily total.",
    ),
    FeatureSpec(
        name="antecedent_rain_72h_mm",
        display_name="Rainfall in the preceding 72 hours",
        group=FeatureGroup.RAINFALL,
        unit="mm",
        source_slug="open-meteo-archive",
        description=(
            "Saturation proxy: the same hourly intensity floods a catchment that is "
            "already wet and drains away from one that is not."
        ),
    ),
    FeatureSpec(
        name="max_hourly_rain_24h_mm",
        display_name="Peak hourly rainfall in 24 hours",
        group=FeatureGroup.RAINFALL,
        unit="mm/h",
        source_slug="open-meteo-archive",
        description="Separates one intense burst from the same total spread thinly.",
    ),
    FeatureSpec(
        name="soil_moisture_frac",
        display_name="Soil moisture",
        group=FeatureGroup.HYDROLOGY,
        unit="fraction",
        source_slug="open-meteo-archive",
        description="Reanalysis surface soil moisture; a direct saturation measure.",
        nullable=True,
    ),
    # -------------------------------------------------------------- terrain
    FeatureSpec(
        name="mean_elevation_m",
        display_name="Mean elevation",
        group=FeatureGroup.TERRAIN,
        unit="m",
        source_slug="copernicus-dem-glo30",
        description="Low-lying zones accumulate runoff from their surroundings.",
    ),
    FeatureSpec(
        name="elevation_percentile_in_city",
        display_name="Relative elevation within the city",
        group=FeatureGroup.TERRAIN,
        unit="percentile",
        source_slug="copernicus-dem-glo30",
        description=(
            "Absolute elevation is not comparable across cities; the percentile makes "
            "the model transferable to a second city without retraining from scratch."
        ),
    ),
    FeatureSpec(
        name="mean_slope_deg",
        display_name="Mean terrain slope",
        group=FeatureGroup.TERRAIN,
        unit="degrees",
        source_slug="copernicus-dem-glo30",
        description="Flat ground sheds water slowly.",
    ),
    FeatureSpec(
        name="depression_area_fraction",
        display_name="Fraction of the zone in a topographic depression",
        group=FeatureGroup.TERRAIN,
        unit="fraction",
        source_slug="copernicus-dem-glo30",
        description="Sink-filling on the DEM identifies bowls with no downhill outlet.",
    ),
    # ----------------------------------------------------------- urban form
    FeatureSpec(
        name="impervious_fraction",
        display_name="Impervious surface fraction",
        group=FeatureGroup.URBAN_FORM,
        unit="fraction",
        source_slug="osm-road-network",
        description=(
            "Approximated from built-up and road area. Impervious ground converts "
            "rainfall to runoff instead of absorbing it."
        ),
    ),
    FeatureSpec(
        name="road_density_km_per_sqkm",
        display_name="Road density",
        group=FeatureGroup.URBAN_FORM,
        unit="km/km²",
        source_slug="osm-road-network",
        description="Correlates with imperviousness and with exposure when flooding occurs.",
    ),
    # ------------------------------------------------------------- temporal
    FeatureSpec(
        name="month_of_year",
        display_name="Month",
        group=FeatureGroup.TEMPORAL,
        unit=None,
        source_slug="open-meteo-archive",
        description="Encodes monsoon seasonality without hardcoding a monsoon window.",
    ),
    # ------------------------------------------- blocked on unresolved gaps
    FeatureSpec(
        name="tide_height_m",
        display_name="Tide height",
        group=FeatureGroup.HYDROLOGY,
        unit="m",
        source_slug="tide-gauge",
        description=(
            "High tide blocks gravity drainage to the sea. Rainfall coinciding with "
            "high tide is the classic severe-waterlogging pattern in coastal cities."
        ),
        available=False,
        nullable=True,
    ),
    FeatureSpec(
        name="drain_capacity_index",
        display_name="Storm-drain capacity index",
        group=FeatureGroup.HYDROLOGY,
        unit="index",
        source_slug="drainage-network",
        description=(
            "Designed drainage capacity per unit area. Without it the model must "
            "infer capacity indirectly from terrain and imperviousness."
        ),
        available=False,
        nullable=True,
    ),
)

#: The label the classifier is trained against.
TARGET = "waterlogging_occurred"

#: Sourced from `flood_incidents`, which is itself an unresolved gap. Recorded
#: here so the blocker is visible from the modelling code, not only the docs.
TARGET_SOURCE_SLUG = "historical-incidents"
TARGET_AVAILABLE = False


def available_features() -> tuple[FeatureSpec, ...]:
    """Features a registered source can supply today."""
    return tuple(spec for spec in FEATURES if spec.available)


def blocked_features() -> tuple[FeatureSpec, ...]:
    """Features waiting on a data gap; see `data/metadata/data_sources.json`."""
    return tuple(spec for spec in FEATURES if not spec.available)


def feature_names() -> tuple[str, ...]:
    return tuple(spec.name for spec in available_features())
