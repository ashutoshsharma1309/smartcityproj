import type { ModuleState, ModuleStatus } from "@/lib/types";

const STATE_STYLE: Record<ModuleState, { chip: string; text: string }> = {
  implemented: {
    chip: "border-signal-ok/40 bg-signal-ok/10 text-signal-ok",
    text: "live",
  },
  interface_only: {
    chip: "border-ground-600 bg-ground-800 text-ink-500",
    text: "interface only",
  },
  not_configured: {
    chip: "border-signal-warn/40 bg-signal-warn/10 text-signal-warn",
    text: "not configured",
  },
};

/**
 * Renders `/api/v1/meta` verbatim.
 *
 * The backend is the only authority on what is built; this component adds no
 * status of its own, so the dashboard cannot claim a capability the API lacks.
 */
export function ModulePanel({ modules }: { modules: ModuleStatus[] }) {
  return (
    <section className="border-t border-ground-800">
      <header className="flex items-baseline justify-between px-5 py-3">
        <h2 className="font-mono text-[11px] uppercase tracking-widest text-ink-500">
          Pipeline modules
        </h2>
        <span className="font-mono text-[11px] text-ink-500">
          {modules.filter((m) => m.state === "implemented").length}/{modules.length} live
        </span>
      </header>

      <ul className="divide-y divide-ground-850">
        {modules.map((module) => (
          <li key={module.key} className="px-5 py-3">
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="truncate text-sm font-medium text-ink-100">{module.name}</p>
                <p className="mt-1 text-xs leading-relaxed text-ink-500">
                  {module.description}
                </p>
              </div>
              <span
                className={`shrink-0 rounded border px-2 py-0.5 font-mono text-[10px] uppercase tracking-wider ${STATE_STYLE[module.state].chip}`}
              >
                {STATE_STYLE[module.state].text}
              </span>
            </div>
            {module.planned_phase && (
              <p className="mt-1.5 font-mono text-[11px] text-ink-500">
                planned: {module.planned_phase}
              </p>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
