import type { HealthState } from "@/lib/types";

const TONE: Record<HealthState, { dot: string; label: string }> = {
  ok: { dot: "bg-signal-ok", label: "text-signal-ok" },
  degraded: { dot: "bg-signal-warn", label: "text-signal-warn" },
  unavailable: { dot: "bg-signal-down", label: "text-signal-down" },
  disabled: { dot: "bg-signal-idle", label: "text-signal-idle" },
};

export function StatusDot({ state }: { state: HealthState }) {
  return (
    <span
      className={`inline-block size-2 shrink-0 rounded-full ${TONE[state].dot}`}
      aria-hidden="true"
    />
  );
}

export function StatusLabel({ state }: { state: HealthState }) {
  return (
    <span className={`font-mono text-xs uppercase tracking-wider ${TONE[state].label}`}>
      {state}
    </span>
  );
}
