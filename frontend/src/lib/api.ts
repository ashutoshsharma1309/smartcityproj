/**
 * Typed client for the UrbanPulse API.
 *
 * Every call returns a discriminated result rather than throwing, because the
 * dashboard's job is to *report* backend state — including the backend being
 * down. A failed fetch is information to display, not an exception to swallow.
 */

import type {
  ApiErrorBody,
  CatalogSummary,
  DataSource,
  ReadinessResponse,
  SystemMeta,
  ZoneFeatureCollection,
} from "@/lib/types";

/**
 * The URL a browser uses to reach the API. Also what error messages quote,
 * because that is the address a developer can actually open.
 */
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

/**
 * The URL this process uses to reach the API.
 *
 * These differ under Docker Compose. The dashboard renders in a server
 * component, so its fetches leave the *frontend container*, where
 * `localhost:8000` is the frontend itself — not the backend. Server-side calls
 * must use the compose service name (`http://backend:8000`) instead.
 *
 * Unset when running natively, where both sides are genuinely `localhost`.
 */
const SERVER_BASE_URL =
  typeof window === "undefined"
    ? (process.env.API_BASE_URL_INTERNAL ?? API_BASE_URL)
    : API_BASE_URL;

export type ApiResult<T> =
  | { ok: true; data: T }
  | { ok: false; error: string; code?: string; status?: number };

// The dashboard issues several calls in parallel on load. A cold connection
// pool, or a loaded machine, can push the first of them past a few seconds, so
// this is deliberately generous — it bounds a hang, it is not a latency budget.
const DEFAULT_TIMEOUT_MS = 12000;

async function request<T>(path: string, timeoutMs = DEFAULT_TIMEOUT_MS): Promise<ApiResult<T>> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  try {
    const response = await fetch(`${SERVER_BASE_URL}${path}`, {
      signal: controller.signal,
      headers: { Accept: "application/json" },
      // The dashboard must reflect live state, never a cached snapshot.
      cache: "no-store",
    });

    if (!response.ok) {
      // The backend uses one error envelope everywhere, so this parses for
      // every failing route.
      const body = (await response.json().catch(() => null)) as ApiErrorBody | null;
      return {
        ok: false,
        status: response.status,
        code: body?.error?.code,
        error: body?.error?.message ?? `Request failed with status ${response.status}.`,
      };
    }

    return { ok: true, data: (await response.json()) as T };
  } catch (error) {
    const isAbort = error instanceof DOMException && error.name === "AbortError";
    return {
      ok: false,
      error: isAbort
        ? `The API did not respond within ${timeoutMs / 1000}s.`
        : `Could not reach the API at ${API_BASE_URL}.`,
    };
  } finally {
    clearTimeout(timer);
  }
}

export const getMeta = () => request<SystemMeta>("/api/v1/meta");
export const getReadiness = () => request<ReadinessResponse>("/health/ready");
export const getCatalogSummary = () => request<CatalogSummary>("/api/v1/catalog/summary");
export const getDataSources = () => request<DataSource[]>("/api/v1/catalog/sources");
export const getZones = () => request<ZoneFeatureCollection>("/api/v1/geo/zones");
export const getDataExtent = () =>
  request<{ bbox: [number, number, number, number] | null }>("/api/v1/geo/extent");
