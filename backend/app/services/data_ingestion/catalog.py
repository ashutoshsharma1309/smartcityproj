"""Loader for ``data/metadata/catalog.json``.

The catalogue is the platform's declaration of what data may exist. Loading it
through typed models means a malformed or under-documented entry fails at load
time, not halfway through an ingestion run.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

DatasetCategory = Literal[
    "weather",
    "elevation",
    "road_network",
    "administrative_boundary",
    "drainage",
    "hydrology",
    "flood_history",
    "civic",
    "traffic",
    "land_cover",
]


class DatasetAccess(BaseModel):
    model_config = ConfigDict(extra="allow")

    method: Literal["ckan", "http_api", "file"]
    base_url: str | None = None
    ckan_base_url: str | None = None
    package_id: str | None = None
    resource_id: str | None = None
    requires_key: bool = False
    batch_size: int | None = None


class DatasetField(BaseModel):
    model_config = ConfigDict(extra="allow")

    name: str
    type: str | None = None
    unit: str | None = None
    description: str | None = None


class DatasetEntry(BaseModel):
    """One catalogued dataset."""

    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    category: DatasetCategory
    provider: str
    source_url: str
    access: DatasetAccess
    license: str
    attribution: str | None = None
    format: str
    geographic_coverage: str | None = None
    temporal_coverage: str | None = None
    update_frequency: str | None = None
    fields: list[DatasetField] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    role: str | None = None
    adapter: str
    origin: Literal["observed", "derived", "simulated"] = "observed"
    verified_on: str | None = None
    observed_feature_count: int | None = None


class UnavailableDataset(BaseModel):
    """A dataset the project needs and does not have.

    Modelled explicitly so gaps are first-class data rather than prose buried
    in a document — the API and the dashboard both surface them.
    """

    model_config = ConfigDict(extra="allow")

    need: str
    category: str
    why_it_matters: str
    finding: str
    consequence: str
    status_checked_on: str | None = None
    adapter_ready: str | None = None


class Catalog(BaseModel):
    model_config = ConfigDict(extra="allow")

    schema_version: str
    generated_on: str
    city_selection: dict[str, Any]
    datasets: list[DatasetEntry]
    unavailable: list[UnavailableDataset] = Field(default_factory=list)

    def by_id(self, dataset_id: str) -> DatasetEntry:
        for dataset in self.datasets:
            if dataset.id == dataset_id:
                return dataset
        raise KeyError(f"No dataset '{dataset_id}' in the catalogue.")

    def by_category(self, category: str) -> list[DatasetEntry]:
        return [d for d in self.datasets if d.category == category]

    @property
    def dataset_ids(self) -> list[str]:
        return [d.id for d in self.datasets]


def repo_root() -> Path:
    """Repository root, resolved from this file's location."""
    return Path(__file__).resolve().parents[4]


def default_catalog_path() -> Path:
    return repo_root() / "data" / "metadata" / "catalog.json"


def load_catalog(path: Path | None = None) -> Catalog:
    target = path or default_catalog_path()
    if not target.exists():
        raise FileNotFoundError(f"Dataset catalogue not found at {target}")
    raw = json.loads(target.read_text(encoding="utf-8"))
    return Catalog.model_validate(raw)


@lru_cache
def get_catalog() -> Catalog:
    """Process-wide cached catalogue."""
    return load_catalog()
