export function IngestionStatusPanel({ logs }: { logs: Array<Record<string, unknown>> }) {
  return <div className="panel" id="ingestion-status"><h3>Ingestion Status</h3>{logs.length ? <ul className="compactList">{logs.slice(0, 6).map((log, index) => <li key={index}>{String(log.resource || "resource")}<span>{String(log.status || "unknown")}</span></li>)}</ul> : <p>No BDL ingestion logs yet.</p>}</div>;
}
