/**
 * Types mirroring the backend's Pydantic schemas.
 *
 * Kept hand-written and narrow rather than generated from OpenAPI: the surface
 * is small, and an explicit contract makes drift show up as a type error during
 * review instead of at runtime.
 */

export type ModuleState = "implemented" | "interface_only" | "not_configured";

export interface ModuleStatus {
  key: string;
  name: string;
  state: ModuleState;
  description: string;
  planned_phase: string | null;
}

export interface AreaOfInterest {
  city_name: string;
  country_code: string;
  /** [min_lon, min_lat, max_lon, max_lat] in EPSG:4326. */
  bbox: [number, number, number, number];
  /** [lon, lat] */
  center: [number, number];
  default_zoom: number;
}

export interface SystemMeta {
  service: string;
  version: string;
  environment: string;
  api_version: string;
  area_of_interest: AreaOfInterest;
  modules: ModuleStatus[];
  llm_configured: boolean;
  llm_provider: string;
}

export type HealthState = "ok" | "degraded" | "unavailable" | "disabled";

export interface DependencyHealth {
  name: string;
  state: HealthState;
  latency_ms: number | null;
  detail: string | null;
  metadata: Record<string, string>;
}

export interface ReadinessResponse {
  status: HealthState;
  service: string;
  version: string;
  environment: string;
  checked_at: string;
  dependencies: DependencyHealth[];
}

export interface CatalogSummary {
  data_sources: number;
  zones: number;
  road_segments: number;
  drainage_assets: number;
  weather_observations: number;
  tide_observations: number;
  flood_incidents: number;
}

export type DataOrigin = "observed" | "derived" | "simulated";

export interface DataSource {
  id: string;
  slug: string;
  name: string;
  provider: string;
  kind: string;
  origin: DataOrigin;
  source_url: string;
  license: string;
  attribution: string | null;
  description: string | null;
  update_interval_seconds: number | null;
  is_active: boolean;
}

/** RFC 7946 collection, plus the backend's non-standard `metadata` block. */
export interface ZoneFeatureCollection {
  type: "FeatureCollection";
  features: Array<{
    type: "Feature";
    id?: string | null;
    geometry: unknown;
    properties: Record<string, unknown>;
  }>;
  metadata: Record<string, unknown>;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    details: Record<string, unknown>;
    request_id: string | null;
  };
}
