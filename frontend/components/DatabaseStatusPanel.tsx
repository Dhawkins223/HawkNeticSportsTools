import type { DatabaseStatus } from "../lib/api";
import { DataStatusBadge } from "./DataStatusBadge";

export function DatabaseStatusPanel({ status }: { status?: DatabaseStatus }) {
  if (!status) return <div className="panel"><h3>Railway PostgreSQL</h3><p>Checking database...</p></div>;
  return <div className="panel" id="database-status"><h3>Railway PostgreSQL</h3><DataStatusBadge label="Connection" value={status.ok ? "connected" : status.error || "failed"} state={status.ok && status.railway_postgres ? "ok" : "error"} /><p>{status.table_count} tables visible through {status.engine}.</p>{!status.railway_postgres && <p className="warningText">Railway DATABASE_URL is not configured in this environment.</p>}</div>;
}
