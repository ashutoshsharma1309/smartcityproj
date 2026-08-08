import { StatusDot, StatusLabel } from "@/components/StatusDot";
import { API_BASE_URL } from "@/lib/api";
import type { ReadinessResponse, SystemMeta } from "@/lib/types";

export function SystemHeader({
  meta,
  readiness,
  apiError,
}: {
  meta: SystemMeta | null;
  readiness: ReadinessResponse | null;
  apiError: string | null;
}) {
  return (
    <header className="border-b border-ground-800 bg-ground-900">
      <div className="flex flex-wrap items-center justify-between gap-4 px-5 py-3">
        <div className="flex items-baseline gap-3">
          <h1 className="text-base font-semibold tracking-tight text-ink-100">
            UrbanPulse
          </h1>
          <p className="font-mono text-[11px] uppercase tracking-widest text-ink-500">
            Flood risk command centre
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
          {meta && (
            <>
              <Meta label="env" value={meta.environment} />
              <Meta label="api" value={`${meta.api_version} · v${meta.version}`} />
              <Meta
                label="llm"
                value={meta.llm_configured ? meta.llm_provider : "not configured"}
                muted={!meta.llm_configured}
              />
            </>
          )}

          {readiness ? (
            <div className="flex items-center gap-3">
              {readiness.dependencies.map((dep) => (
                <span key={dep.name} className="flex items-center gap-1.5" title={dep.detail ?? ""}>
                  <StatusDot state={dep.state} />
                  <span className="font-mono text-[11px] text-ink-300">{dep.name}</span>
                </span>
              ))}
              <StatusLabel state={readiness.status} />
            </div>
          ) : (
            <span className="flex items-center gap-1.5">
              <StatusDot state="unavailable" />
              <span className="font-mono text-[11px] text-signal-down">backend unreachable</span>
            </span>
          )}
        </div>
      </div>

      {apiError && (
        <div className="border-t border-signal-down/30 bg-signal-down/10 px-5 py-2">
          <p className="text-xs text-signal-down">
            {apiError} Expected the API at{" "}
            <code className="font-mono">{API_BASE_URL}</code>. Start it with{" "}
            <code className="font-mono">docker compose up</code> or{" "}
            <code className="font-mono">uvicorn app.main:app --reload</code>.
          </p>
        </div>
      )}
    </header>
  );
}

function Meta({ label, value, muted }: { label: string; value: string; muted?: boolean }) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="font-mono text-[10px] uppercase tracking-widest text-ink-500">
        {label}
      </span>
      <span className={`font-mono text-[11px] ${muted ? "text-ink-500" : "text-ink-300"}`}>
        {value}
      </span>
    </span>
  );
}
