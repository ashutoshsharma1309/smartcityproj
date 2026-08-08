"""Environment-driven application configuration.

All configuration enters the process through environment variables (or a local
``.env`` file). Nothing is hardcoded; there are no secret defaults.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, PostgresDsn, RedisDsn, computed_field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

#: List-valued settings are written as plain comma-separated strings in `.env`
#: (`CORS_ORIGINS=http://a,http://b`). Without `NoDecode`, pydantic-settings
#: tries to JSON-decode them at the source level and fails before any validator
#: runs, so the application would refuse to start.
CSVList = Annotated[list[str], NoDecode]
CSVFloatList = Annotated[list[float], NoDecode]

Environment = Literal["local", "test", "staging", "production"]
LogFormat = Literal["json", "console"]


class Settings(BaseSettings):
    """Typed application settings.

    Loaded once per process via :func:`get_settings` and injected into request
    handlers through ``app.api.deps.SettingsDep``.
    """

    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
        extra="ignore",
        case_sensitive=False,
    )

    # ------------------------------------------------------------------ app
    project_name: str = "UrbanPulse"
    environment: Environment = "local"
    debug: bool = False
    api_v1_prefix: str = "/api/v1"

    # -------------------------------------------------------------- logging
    log_level: str = "INFO"
    log_format: LogFormat = "console"

    # ------------------------------------------------------------- database
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "urbanpulse"
    postgres_password: str = "urbanpulse"
    postgres_db: str = "urbanpulse"
    db_echo: bool = False
    db_pool_size: int = 5
    db_max_overflow: int = 10
    db_pool_pre_ping: bool = True
    # Seconds a health probe may spend waiting on the database before failing.
    # This budget also covers establishing the first pooled connection, which
    # on a cold container can take several seconds; too tight a value makes the
    # first probe after startup report a false outage.
    db_health_timeout_seconds: float = 10.0

    # ---------------------------------------------------------------- redis
    # Redis backs two things that are part of the design, not decoration:
    #   1. a cache for expensive PostGIS zone/road aggregations served per map
    #      viewport, and
    #   2. the broker for scheduled ingestion jobs (weather polling) added in
    #      Phase 2.
    redis_enabled: bool = True
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: str | None = None
    redis_health_timeout_seconds: float = 2.0
    # Default TTL for cached geospatial aggregations.
    cache_default_ttl_seconds: int = 300

    # ----------------------------------------------------------------- cors
    cors_origins: CSVList = Field(
        default_factory=lambda: ["http://localhost:3000", "http://127.0.0.1:3000"]
    )
    cors_allow_credentials: bool = True

    # ------------------------------------------------------------------ llm
    # The LLM is used only for turning structured, already-computed facts into
    # natural language. It never produces numbers. Provider is swappable.
    llm_provider: str = "none"
    llm_api_key: str | None = None
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_timeout_seconds: float = 30.0
    llm_max_output_tokens: int = 700

    # ------------------------------------------------ external data sources
    # Public, key-optional endpoints used by the ingestion service (Phase 2).
    open_meteo_base_url: str = "https://api.open-meteo.com/v1"
    open_meteo_archive_base_url: str = "https://archive-api.open-meteo.com/v1"
    overpass_api_url: str = "https://overpass-api.de/api/interpreter"

    # ------------------------------------------------------ area of interest
    # The first target city. Kept in configuration so the platform is not
    # hardcoded to one municipality.
    city_name: str = "Mumbai"
    city_country_code: str = "IN"
    # Bounding box as min_lon, min_lat, max_lon, max_lat (EPSG:4326).
    city_bbox: CSVFloatList = Field(default_factory=lambda: [72.775, 18.890, 72.990, 19.280])
    city_center: CSVFloatList = Field(default_factory=lambda: [72.8777, 19.0760])
    default_map_zoom: float = 10.5

    @field_validator("cors_origins", "city_bbox", "city_center", mode="before")
    @classmethod
    def _split_csv(cls, value: object) -> object:
        """Allow list settings to be supplied as comma-separated strings."""
        if isinstance(value, str) and not value.strip().startswith("["):
            return [part.strip() for part in value.split(",") if part.strip()]
        return value

    @field_validator("city_bbox")
    @classmethod
    def _validate_bbox(cls, value: list[float]) -> list[float]:
        if len(value) != 4:
            raise ValueError(
                "city_bbox must contain exactly 4 numbers: min_lon,min_lat,max_lon,max_lat"
            )
        min_lon, min_lat, max_lon, max_lat = value
        if min_lon >= max_lon or min_lat >= max_lat:
            raise ValueError("city_bbox min values must be strictly less than max values")
        return value

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        upper = value.upper()
        if upper not in allowed:
            raise ValueError(f"log_level must be one of {sorted(allowed)}")
        return upper

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        """Async SQLAlchemy DSN (asyncpg driver)."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+asyncpg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def sync_database_url(self) -> str:
        """Synchronous DSN, used by Alembic migrations."""
        return str(
            PostgresDsn.build(
                scheme="postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password,
                host=self.postgres_host,
                port=self.postgres_port,
                path=self.postgres_db,
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def redis_url(self) -> str:
        return str(
            RedisDsn.build(
                scheme="redis",
                password=self.redis_password,
                host=self.redis_host,
                port=self.redis_port,
                path=str(self.redis_db),
            )
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def llm_configured(self) -> bool:
        """True only when a real provider *and* credentials are present."""
        return self.llm_provider.lower() != "none" and bool(self.llm_api_key)


@lru_cache
def get_settings() -> Settings:
    """Process-wide settings singleton."""
    return Settings()
