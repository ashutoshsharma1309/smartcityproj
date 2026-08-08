"""Module registry — the single source of truth for what is actually built.

``GET /api/v1/meta`` serves this list and the frontend renders it verbatim.
When a module gains a real implementation, its state changes here and the
dashboard updates with it. Nothing else in the codebase describes capability
status, so the UI cannot drift out of sync with reality.
"""

from __future__ import annotations

from app.schemas.meta import ModuleStatus

MODULES: tuple[ModuleStatus, ...] = (
    ModuleStatus(
        key="data_ingestion",
        name="Data Ingestion Service",
        state="interface_only",
        description=(
            "Pulls weather, elevation, road-network and incident data from registered public "
            "providers and records an audited ingestion run for every attempt."
        ),
        planned_phase="Phase 2",
    ),
    ModuleStatus(
        key="data_validation",
        name="Data Validation Service",
        state="interface_only",
        description=(
            "Applies schema, range and geometry-topology checks; rejected records are counted "
            "per run rather than silently dropped."
        ),
        planned_phase="Phase 2",
    ),
    ModuleStatus(
        key="geospatial",
        name="Geospatial Processing Service",
        state="implemented",
        description=(
            "Serves zones and road segments from PostGIS as GeoJSON, simplified server-side. "
            "Terrain-attribute derivation from a DEM is not implemented yet."
        ),
        planned_phase="Phase 2",
    ),
    ModuleStatus(
        key="feature_engineering",
        name="Feature Engineering Pipeline",
        state="interface_only",
        description=(
            "Builds antecedent-rainfall, terrain and tide features shared by training and "
            "inference so the two cannot drift apart."
        ),
        planned_phase="Phase 3",
    ),
    ModuleStatus(
        key="risk_prediction",
        name="Risk Prediction Engine",
        state="interface_only",
        description=(
            "Gradient-boosted classifier producing a calibrated waterlogging probability per "
            "zone, with SHAP attributions. Never an LLM."
        ),
        planned_phase="Phase 3",
    ),
    ModuleStatus(
        key="impact_analysis",
        name="Impact Analysis Engine",
        state="interface_only",
        description=(
            "Intersects at-risk zones with the road graph and uses NetworkX connectivity to "
            "find severed links and isolated zones."
        ),
        planned_phase="Phase 4",
    ),
    ModuleStatus(
        key="recommendations",
        name="Recommendation Engine",
        state="interface_only",
        description=(
            "Deterministic rules mapping risk and impact to municipal actions, each traceable "
            "to the rule that fired."
        ),
        planned_phase="Phase 4",
    ),
    ModuleStatus(
        key="llm_explanation",
        name="LLM Explanation Service",
        state="not_configured",
        description=(
            "Turns computed predictions, impacts and actions into a short natural-language "
            "briefing. Receives structured facts only and produces no numbers of its own."
        ),
        planned_phase="Phase 5",
    ),
    ModuleStatus(
        key="alerts",
        name="Alert / Event Service",
        state="interface_only",
        description="Raises events when zone risk crosses configured thresholds.",
        planned_phase="Phase 5",
    ),
    ModuleStatus(
        key="rest_api",
        name="REST API",
        state="implemented",
        description=(
            "Versioned FastAPI surface with a consistent error envelope, request correlation "
            "ids and OpenAPI documentation."
        ),
        planned_phase=None,
    ),
    ModuleStatus(
        key="gis_frontend",
        name="GIS Command Centre",
        state="implemented",
        description=(
            "Next.js and MapLibre shell rendering the city basemap, live backend status and "
            "the dataset catalogue."
        ),
        planned_phase=None,
    ),
    ModuleStatus(
        key="evaluation",
        name="Evaluation / Monitoring",
        state="interface_only",
        description=(
            "Backtesting against historical incidents plus drift monitoring on live feature "
            "distributions."
        ),
        planned_phase="Phase 6",
    ),
)


def module_by_key(key: str) -> ModuleStatus | None:
    return next((module for module in MODULES if module.key == key), None)
