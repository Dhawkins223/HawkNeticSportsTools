import type { DataStatusBadgeState } from "../lib/api";

export function DataStatusBadge({ label, value, state }: { label: string; value: string; state: DataStatusBadgeState }) {
  return <span className={`statusBadge ${state}`}><strong>{label}</strong>{value}</span>;
}
