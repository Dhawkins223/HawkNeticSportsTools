"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type AdminResult = Record<string, unknown> | null;

export default function AdminPage() {
  const [loading, setLoading] = useState<string | null>(null);
  const [result, setResult] = useState<AdminResult>(null);

  async function run(label: string, action: () => Promise<unknown>) {
    setLoading(label);
    setResult(null);
    try {
      setResult(await action() as Record<string, unknown>);
    } catch (err) {
      setResult({ error: err instanceof Error ? err.message : "Admin request failed" });
    } finally {
      setLoading(null);
    }
  }

  return (
    <main className="adminPage">
      <header>
        <a href="/">Back to HawkNetic Predictor</a>
        <h1>Admin / Data Tools</h1>
        <p>Operational tools for database readiness, data status, backfill checks, and table counts.</p>
      </header>
      <section className="adminToolGrid">
        <button disabled={loading !== null} onClick={() => run("health", api.health)}>Check API health</button>
        <button disabled={loading !== null} onClick={() => run("data-status", api.dataStatus)}>Fetch data status</button>
        <button disabled={loading !== null} onClick={() => run("readiness", api.databaseReadiness)}>Fetch database readiness</button>
        <button disabled={loading !== null} onClick={() => run("table-counts", api.tableCounts)}>Fetch table counts</button>
        <button disabled={loading !== null} onClick={() => run("backfill", () => api.historicalBackfillSeason(2024))}>Run 2024 backfill test</button>
      </section>
      {loading && <p className="adminLoading">Running {loading}...</p>}
      {result && <pre className="adminResult">{JSON.stringify(result, null, 2)}</pre>}
    </main>
  );
}
