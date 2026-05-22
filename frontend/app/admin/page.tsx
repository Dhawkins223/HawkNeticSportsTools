"use client";

import { useState } from "react";
import { api } from "@/lib/api";

type AdminResult = Record<string, unknown> | null;
type AdminAction = () => Promise<unknown>;
type ToolGroup = { title: string; description: string; tools: Array<{ id: string; label: string; run: AdminAction }> };

const BACKFILL_TEST_SEASON = 2024;

export default function AdminPage() {
  const [loading, setLoading] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [result, setResult] = useState<AdminResult>(null);

  async function run(label: string, action: AdminAction): Promise<void> {
    setLoading(label);
    setActiveId(label);
    setResult(null);
    try {
      setResult(await action() as Record<string, unknown>);
    } catch (err) {
      setResult({ error: err instanceof Error ? err.message : "Admin request failed" });
    } finally {
      setLoading(null);
    }
  }

  const groups: ToolGroup[] = [
    {
      title: "Live Data",
      description: "Live-data readiness, freshness, and snapshot history. These checks gate the Run Algorithm flow.",
      tools: [
        { id: "live-readiness", label: "Live readiness", run: api.liveReadiness },
        { id: "live-snapshots", label: "Latest snapshots", run: api.liveSnapshots },
        { id: "live-odds", label: "Live odds", run: () => api.liveOdds() },
        { id: "games-today", label: "Today's games", run: api.gamesToday },
      ],
    },
    {
      title: "Database",
      description: "Schema, table counts, and dashboard readiness flags.",
      tools: [
        { id: "db-status", label: "Database status", run: api.databaseStatus },
        { id: "db-readiness", label: "Database readiness", run: api.databaseReadiness },
        { id: "table-counts", label: "Table counts", run: api.tableCounts },
        { id: "data-status", label: "Data status overview", run: api.dataStatus },
      ],
    },
    {
      title: "Backfill & Sync",
      description: "Pull historical seasons, sync Ball Don't Lie data, and inspect provider logs.",
      tools: [
        { id: "backfill", label: `Run ${BACKFILL_TEST_SEASON} backfill test`, run: () => api.historicalBackfillSeason(BACKFILL_TEST_SEASON) },
        { id: "bdl-logs", label: "Ball Don't Lie logs", run: api.bdlLogs },
        { id: "historical-coverage", label: "Historical coverage", run: api.historicalCoverage },
      ],
    },
    {
      title: "Health",
      description: "Generic API health.",
      tools: [{ id: "health", label: "API health", run: api.health }],
    },
  ];

  return (
    <main className="adminPage" data-testid="admin-page">
      <header style={{ marginBottom: "2rem" }}>
        <a href="/" data-testid="admin-back-link" style={{ color: "#d8f63a", textDecoration: "none", fontSize: "0.85rem", letterSpacing: "0.04em" }}>← Back to HawkNetic Predictor</a>
        <h1 style={{ margin: "0.6rem 0 0.4rem", fontSize: "2rem" }}>HawkNetic Admin</h1>
        <p style={{ opacity: 0.75, maxWidth: "62ch" }}>
          Operational tools — separate from the public dashboard. Live readiness, database status, backfill, and provider logs live here so users see only the betting interface.
        </p>
      </header>
      {groups.map((group) => (
        <section key={group.title} style={{ marginBottom: "2rem" }} data-testid={`admin-group-${group.title.toLowerCase().replace(/\s+/g, "-")}`}>
          <h2 style={{ margin: "0 0 0.3rem", fontSize: "1.05rem", letterSpacing: "0.06em", textTransform: "uppercase", color: "#d8f63a" }}>{group.title}</h2>
          <p style={{ opacity: 0.6, fontSize: "0.85rem", marginTop: 0 }}>{group.description}</p>
          <div className="adminToolGrid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: "0.6rem", marginTop: "0.7rem" }}>
            {group.tools.map((tool) => (
              <button
                key={tool.id}
                disabled={loading !== null}
                onClick={() => run(tool.id, tool.run)}
                data-testid={`admin-${tool.id}`}
                style={{ padding: "0.7rem 0.9rem", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.15)", background: activeId === tool.id ? "rgba(216,246,58,0.18)" : "rgba(255,255,255,0.04)", color: "inherit", textAlign: "left", cursor: loading ? "not-allowed" : "pointer", fontSize: "0.85rem" }}
              >
                {loading === tool.id ? `${tool.label} (running…)` : tool.label}
              </button>
            ))}
          </div>
        </section>
      ))}
      {result && (
        <pre className="adminResult" data-testid="admin-result" style={{ background: "rgba(0,0,0,0.55)", padding: "1rem 1.2rem", borderRadius: "10px", maxHeight: "60vh", overflow: "auto", fontSize: "0.78rem", lineHeight: 1.45 }}>
          {JSON.stringify(result, null, 2)}
        </pre>
      )}
    </main>
  );
}
