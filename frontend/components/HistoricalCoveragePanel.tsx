import type { HistoricalCoverage } from "../lib/api";

export function HistoricalCoveragePanel({ coverage }: { coverage?: HistoricalCoverage }) {
  return <div className="panel" id="historical-data"><h3>Historical Coverage</h3>{coverage ? <><div className="metricLine"><strong>{coverage.complete_seasons}/{coverage.total_seasons}</strong><span>complete seasons</span></div><p>{coverage.incomplete_seasons} seasons from 1996-2026 are incomplete until historical backfill data is loaded.</p></> : <p>Loading coverage...</p>}</div>;
}
