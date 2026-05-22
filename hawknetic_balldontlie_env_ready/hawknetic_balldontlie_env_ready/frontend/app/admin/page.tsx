"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import { AdminToolGroup, type AdminTool, type ToolGroup } from "./AdminToolGroup";

type AdminResult = Record<string, unknown> | null;

const BACKFILL_TEST_SEASON = 2024;

const TOOL_GROUPS: ToolGroup[] = [
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

function AdminHeader() {
  return (
    <header style={{ marginBottom: "2rem" }}>
      <a href="/" data-testid="admin-back-link" style={{ color: "#d8f63a", textDecoration: "none", fontSize: "0.85rem", letterSpacing: "0.04em" }}>
        ← Back to HawkneticSportsTools
      </a>
      <h1 style={{ margin: "0.6rem 0 0.4rem", fontSize: "2rem" }}>HawkneticSports Admin</h1>
      <p style={{ opacity: 0.75, maxWidth: "62ch" }}>
        Operational tools — separate from the public dashboard. Live readiness, database status, backfill, and provider logs live here so users see only the betting interface.
      </p>
    </header>
  );
}

function AdminResultPanel({ result }: { result: AdminResult }) {
  if (!result) return null;
  return (
    <pre
      className="adminResult"
      data-testid="admin-result"
      style={{ background: "rgba(0,0,0,0.55)", padding: "1rem 1.2rem", borderRadius: "10px", maxHeight: "60vh", overflow: "auto", fontSize: "0.78rem", lineHeight: 1.45 }}
    >
      {JSON.stringify(result, null, 2)}
    </pre>
  );
}

export default function AdminPage() {
  const [loadingId, setLoadingId] = useState<string | null>(null);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [result, setResult] = useState<AdminResult>(null);

  async function runTool(tool: AdminTool): Promise<void> {
    setLoadingId(tool.id);
    setActiveId(tool.id);
    setResult(null);
    try {
      setResult(await tool.run() as Record<string, unknown>);
    } catch (err) {
      setResult({ error: err instanceof Error ? err.message : "Admin request failed" });
    } finally {
      setLoadingId(null);
    }
  }

  return (
    <main className="adminPage" data-testid="admin-page">
      <AdminHeader />
      {TOOL_GROUPS.map((group) => (
        <AdminToolGroup
          key={group.title}
          group={group}
          loadingId={loadingId}
          activeId={activeId}
          onRun={runTool}
        />
      ))}
      <AdminResultPanel result={result} />
    </main>
  );
}
