import type { CatalogSummary, DataSource } from "@/lib/types";

const TABLE_LABELS: Array<[keyof CatalogSummary, string]> = [
  ["zones", "Zones"],
  ["road_segments", "Road segments"],
  ["weather_observations", "Weather obs."],
  ["tide_observations", "Tide obs."],
  ["flood_incidents", "Flood incidents"],
  ["drainage_assets", "Drainage assets"],
];

const ORIGIN_STYLE: Record<string, string> = {
  observed: "border-signal-ok/40 bg-signal-ok/10 text-signal-ok",
  derived: "border-accent/40 bg-accent/10 text-accent",
  simulated: "border-signal-warn/40 bg-signal-warn/10 text-signal-warn",
};

/**
 * The data catalogue.
 *
 * Row counts are shown even when zero — an empty warehouse is a fact an
 * operator needs, and hiding it would let the UI imply data exists. Sources
 * marked `simulated` are visually distinct from observed data by design.
 */
export function DataPanel({
  summary,
  sources,
}: {
  summary: CatalogSummary | null;
  sources: DataSource[];
}) {
  return (
    <section className="border-t border-ground-800">
      <header className="px-5 py-3">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-ink-500">
          Data warehouse
        </h2>
      </header>

      {summary === null ? (
        <p className="px-5 pb-4 text-xs text-signal-down">
          Row counts unavailable — the API could not be reached.
        </p>
      ) : (
        <dl className="grid grid-cols-2 gap-px bg-ground-850">
          {TABLE_LABELS.map(([key, label]) => (
            <div key={key} className="bg-ground-900 px-5 py-3">
              <dt className="text-[11px] text-ink-500">{label}</dt>
              <dd
                className={`font-mono text-lg tabular-nums ${
                  summary[key] === 0 ? "text-ink-500" : "text-ink-100"
                }`}
              >
                {summary[key].toLocaleString()}
              </dd>
            </div>
          ))}
        </dl>
      )}

      <div className="px-5 py-3">
        <h3 className="font-mono text-[11px] uppercase tracking-widest text-ink-500">
          Registered sources
        </h3>

        {sources.length === 0 ? (
          <p className="mt-2 text-xs leading-relaxed text-ink-500">
            No data sources registered. Run{" "}
            <code className="rounded bg-ground-800 px-1 py-0.5 font-mono text-[11px] text-ink-300">
              python scripts/register_data_sources.py
            </code>{" "}
            to load the provenance manifest from{" "}
            <code className="rounded bg-ground-800 px-1 py-0.5 font-mono text-[11px] text-ink-300">
              data/metadata/
            </code>
            .
          </p>
        ) : (
          <ul className="mt-2 space-y-2">
            {sources.map((source) => (
              <li
                key={source.id}
                className="rounded border border-ground-800 bg-ground-850 px-3 py-2"
              >
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0">
                    <p className="truncate text-sm text-ink-100">{source.name}</p>
                    <p className="truncate text-[11px] text-ink-500">
                      {source.provider} · {source.license}
                    </p>
                  </div>
                  <span
                    className={`shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] uppercase ${
                      ORIGIN_STYLE[source.origin] ?? "border-ground-600 text-ink-500"
                    }`}
                  >
                    {source.origin}
                  </span>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>
    </section>
  );
}
