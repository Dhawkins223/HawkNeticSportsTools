import type { DatabaseReadiness, DatabaseStatus } from "../lib/api";
import { DataStatusBadge } from "./DataStatusBadge";

export function DatabaseStatusPanel({ status, readiness, apiError }: { status?: DatabaseStatus; readiness?: DatabaseReadiness; apiError?: string | null }) {
  if (apiError) {
    return <div className="panel apiStatusPanel" id="database-status"><h3>Database / API Status</h3><DataStatusBadge label="API connected" value="no" state="error" /><p className="warningText">Frontend cannot reach backend API. Check NEXT_PUBLIC_API_BASE_URL.</p><p>{apiError}</p></div>;
  }
  if (!status) return <div className="panel apiStatusPanel"><h3>Database / API Status</h3><p>Loading API and database status...</p></div>;
  const connected = status.connected ?? status.ok;
  const ready = Boolean(readiness?.dashboard_ready);
  const counts = readiness?.row_counts || {};
  const countSummary = ["historical_games", "historical_players", "bdl_games", "props", "simulations"].map((key) => `${key}: ${counts[key] ?? "missing"}`);
  return (
    <div className="panel apiStatusPanel" id="database-status">
      <div className="panelHeader">
        <div>
          <p className="eyebrow">Production data path</p>
          <h3>Database / API Status</h3>
        </div>
        <DataStatusBadge label="Dashboard ready" value={ready ? "yes" : "no"} state={ready ? "ok" : "warning"} />
      </div>
      <div className="statusGrid">
        <DataStatusBadge label="API connected" value="yes" state="ok" />
        <DataStatusBadge label="Database connected" value={connected ? "yes" : "no"} state={connected ? "ok" : "error"} />
        <DataStatusBadge label="Engine" value={status.engine} state={status.railway_postgres ? "ok" : "warning"} />
        <DataStatusBadge label="Tables" value={String(status.table_count)} state={status.table_count ? "ok" : "warning"} />
      </div>
      {!status.railway_postgres && <p className="warningText">Railway PostgreSQL is not active. Production must set DATABASE_URL and HAWKNETIC_ENV=production.</p>}
      {readiness?.blocking_reasons?.length ? <div className="statusCallout warningText">{readiness.blocking_reasons.join(" ")}</div> : null}
      {readiness?.empty_important_tables?.length ? <p>Database connected, but required tables are empty. Run historical backfill or Ball Don&apos;t Lie sync.</p> : null}
      <div className="summaryGrid">
        {countSummary.map((item) => <span key={item}>{item}</span>)}
      </div>
      {readiness?.latest_import_job && <p>Latest import/backfill: {String(readiness.latest_import_job.source || "job")} · {String(readiness.latest_import_job.status || "unknown")}</p>}
    </div>
  );
}
