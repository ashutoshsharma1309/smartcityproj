import { CityMap } from "@/components/CityMap";
import { DataPanel } from "@/components/DataPanel";
import { ModulePanel } from "@/components/ModulePanel";
import { SystemHeader } from "@/components/SystemHeader";
import {
  getCatalogSummary,
  getDataExtent,
  getDataSources,
  getMeta,
  getReadiness,
} from "@/lib/api";
import type { AreaOfInterest } from "@/lib/types";

// The dashboard reports live backend state, so it must never be prerendered
// or cached at build time.
export const dynamic = "force-dynamic";

/**
 * Used only to keep the map mounted when `/meta` is unreachable, so the shell
 * still renders and the header can explain what is wrong. It is labelled as
 * a fallback in the UI and is never presented as ingested data.
 */
const FALLBACK_AREA: AreaOfInterest = {
  city_name: "Unknown",
  country_code: "--",
  bbox: [-0.5, 51.3, 0.3, 51.7],
  center: [-0.1, 51.5],
  default_zoom: 9,
};

export default async function DashboardPage() {
  const [meta, readiness, summary, sources, extent] = await Promise.all([
    getMeta(),
    getReadiness(),
    getCatalogSummary(),
    getDataSources(),
    getDataExtent(),
  ]);

  const area = meta.ok ? meta.data.area_of_interest : FALLBACK_AREA;

  return (
    <div className="flex h-screen flex-col overflow-hidden">
      <SystemHeader
        meta={meta.ok ? meta.data : null}
        readiness={readiness.ok ? readiness.data : null}
        apiError={meta.ok ? null : meta.error}
      />

      <main className="flex min-h-0 flex-1 flex-col lg:flex-row">
        <div className="relative min-h-[45vh] flex-1 lg:min-h-0">
          <CityMap area={area} dataExtent={extent.ok ? extent.data.bbox : null} />
        </div>

        <aside className="w-full shrink-0 overflow-y-auto border-l border-ground-800 bg-ground-900 lg:w-[26rem]">
          <div className="px-5 py-4">
            <h2 className="text-sm font-medium text-ink-100">
              Predictive flood &amp; road-impact analysis
            </h2>
            <p className="mt-2 text-xs leading-relaxed text-ink-500">
              UrbanPulse forecasts waterlogging risk per zone from rainfall, terrain, tide
              and drainage data, then derives which roads it cuts. Risk is computed by a
              gradient-boosted model; the language model only rewrites those results as
              prose.
            </p>
            <p className="mt-2 text-xs leading-relaxed text-ink-500">
              This is the Phase 1 foundation. Panels below report exactly what the backend
              can do today — no forecast is shown because none has been computed.
            </p>
          </div>

          <DataPanel
            summary={summary.ok ? summary.data : null}
            sources={sources.ok ? sources.data : []}
          />

          {meta.ok ? (
            <ModulePanel modules={meta.data.modules} />
          ) : (
            <section className="border-t border-ground-800 px-5 py-4">
              <p className="text-xs text-signal-down">
                Module status unavailable — the API could not be reached.
              </p>
            </section>
          )}
        </aside>
      </main>
    </div>
  );
}
