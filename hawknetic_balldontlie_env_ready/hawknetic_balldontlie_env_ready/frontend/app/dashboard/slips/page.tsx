"use client";

import { useEffect, useState, type ReactElement } from "react";
import { api } from "@/lib/api";

type SlipLeg = {
  id: number;
  label: string;
  market_type?: string;
  line?: number | null;
  odds_value?: number | null;
  probability?: number | null;
};

export type SavedSlip = {
  id: number;
  name: string;
  sport?: string;
  estimated_odds?: number | null;
  win_probability?: number | null;
  expected_value?: number | null;
  risk_tier?: string | null;
  created_at?: string;
  legs?: SlipLeg[];
};

type SlipResult = {
  id: number;
  classification: string | null;
  recommended_action: string | null;
  parlay_probability: number | null;
  parlay_ev: number | null;
  confidence_score: number | null;
  simulation_runs: number | null;
  blocked: number;
  blocking_reasons: string | null;
  created_at: string;
};

type State = {
  slips: SavedSlip[];
  loading: boolean;
  error: string | null;
};

function formatPercent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined) return "—";
  return `${(value * 100).toFixed(digits)}%`;
}

function formatOdds(value?: number | null): string {
  if (value === null || value === undefined) return "—";
  return value > 0 ? `+${value}` : String(value);
}

function classificationBadgeColor(c: string | null): string {
  if (!c) return "rgba(255,255,255,0.5)";
  const lower = c.toLowerCase();
  if (lower.includes("strong") || lower.includes("buy")) return "#d8f63a";
  if (lower.includes("playable") || lower.includes("lean")) return "#7dd3fc";
  if (lower.includes("trap") || lower.includes("pass") || lower.includes("avoid")) return "#ff8888";
  return "rgba(255,255,255,0.7)";
}

function LegRow({ leg }: { leg: SlipLeg }): ReactElement {
  return (
    <li style={{ padding: "0.45rem 0.6rem", borderRadius: "6px", background: "rgba(0,0,0,0.35)", marginTop: "0.3rem" }}>
      <strong style={{ fontSize: "0.86rem" }}>{leg.label}</strong>
      <div style={{ fontSize: "0.74rem", opacity: 0.7, marginTop: "0.15rem" }}>
        {leg.market_type?.replaceAll("_", " ") || "—"}{leg.line ? ` · ${leg.line}` : ""} · {formatOdds(leg.odds_value)}
        {leg.probability !== null && leg.probability !== undefined ? ` · model ${formatPercent(leg.probability, 0)}` : ""}
      </div>
    </li>
  );
}

function SlipMetricsRow({ slip }: { slip: SavedSlip }): ReactElement {
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "0.4rem 0.9rem", fontSize: "0.8rem", opacity: 0.85, marginTop: "0.4rem" }}>
      <span>Sport <b>{slip.sport || "—"}</b></span>
      <span>Win prob <b>{formatPercent(slip.win_probability, 0)}</b></span>
      <span>Est. odds <b>{slip.estimated_odds ? formatOdds(slip.estimated_odds) : "—"}</b></span>
      <span>Risk <b>{slip.risk_tier || "—"}</b></span>
      <span>Saved <b>{slip.created_at ? new Date(slip.created_at).toLocaleString() : "—"}</b></span>
    </div>
  );
}

function ResultRow({ result }: { result: SlipResult }): ReactElement {
  return (
    <li style={{ padding: "0.5rem 0.7rem", borderRadius: "8px", background: "rgba(0,0,0,0.4)", marginTop: "0.35rem", fontSize: "0.8rem" }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
        <strong style={{ color: classificationBadgeColor(result.classification) }}>{result.classification || (result.blocked ? "Blocked" : "Run")}</strong>
        <span style={{ opacity: 0.6, fontSize: "0.72rem" }}>{new Date(result.created_at).toLocaleString()}</span>
      </div>
      <div style={{ marginTop: "0.25rem", opacity: 0.8 }}>
        Prob <b>{formatPercent(result.parlay_probability, 1)}</b> · EV <b>{formatPercent(result.parlay_ev, 1)}</b> · Conf <b>{result.confidence_score?.toFixed(0) || "—"}</b> · Runs <b>{result.simulation_runs?.toLocaleString() || "—"}</b>
      </div>
      {result.blocked === 1 && result.blocking_reasons && (
        <div style={{ marginTop: "0.25rem", color: "#ff9090", fontSize: "0.74rem" }}>{result.blocking_reasons}</div>
      )}
    </li>
  );
}

function SlipCard({ slip, onDelete, onRunComplete }: { slip: SavedSlip; onDelete: (id: number) => void; onRunComplete: () => void }): ReactElement {
  const [running, setRunning] = useState(false);
  const [results, setResults] = useState<SlipResult[] | null>(null);
  const [showResults, setShowResults] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function loadResults() {
    try {
      const data = await api.slipResults(slip.id);
      setResults(data.items);
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : "Failed to load results");
    }
  }

  async function handleRun() {
    setRunning(true);
    setError(null);
    try {
      await api.runSlip(slip.id);
      await loadResults();
      setShowResults(true);
      onRunComplete();
    } catch (ex) {
      setError(ex instanceof Error ? ex.message : "Run failed");
    } finally {
      setRunning(false);
    }
  }

  async function handleToggleResults() {
    if (!showResults && results === null) await loadResults();
    setShowResults(!showResults);
  }

  return (
    <article
      data-testid={`saved-slip-${slip.id}`}
      style={{ padding: "1rem 1.2rem", borderRadius: "12px", background: "rgba(255,255,255,0.04)", border: "1px solid rgba(255,255,255,0.1)", marginBottom: "1rem" }}
    >
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "0.5rem" }}>
        <div>
          <h2 style={{ margin: 0, fontSize: "1.05rem" }}>{slip.name}</h2>
          <SlipMetricsRow slip={slip} />
        </div>
        <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <button
            type="button"
            disabled={running}
            onClick={handleRun}
            data-testid={`run-saved-slip-${slip.id}`}
            style={{ padding: "0.55rem 1.1rem", borderRadius: "999px", border: "none", background: "#d8f63a", color: "#0b1606", fontWeight: 700, cursor: running ? "not-allowed" : "pointer" }}
          >
            {running ? "Running…" : "Run again"}
          </button>
          <button
            type="button"
            onClick={handleToggleResults}
            data-testid={`toggle-results-${slip.id}`}
            style={{ padding: "0.55rem 1.1rem", borderRadius: "999px", border: "1px solid rgba(216,246,58,0.35)", background: "transparent", color: "#d8f63a", cursor: "pointer" }}
          >
            {showResults ? "Hide history" : "Run history"}
          </button>
          <button
            type="button"
            onClick={() => onDelete(slip.id)}
            data-testid={`delete-saved-slip-${slip.id}`}
            style={{ padding: "0.55rem 1.1rem", borderRadius: "999px", border: "1px solid rgba(255,255,255,0.16)", background: "transparent", color: "rgba(255,255,255,0.7)", cursor: "pointer" }}
          >
            Delete
          </button>
        </div>
      </header>
      {error && <div style={{ marginTop: "0.5rem", color: "#ff8888", fontSize: "0.8rem" }} data-testid={`run-error-${slip.id}`}>{error}</div>}
      {slip.legs && slip.legs.length > 0 && (
        <ul style={{ listStyle: "none", padding: 0, margin: "0.6rem 0 0" }}>
          {slip.legs.map((leg) => <LegRow key={leg.id} leg={leg} />)}
        </ul>
      )}
      {showResults && (
        <section style={{ marginTop: "0.8rem" }} data-testid={`results-${slip.id}`}>
          <h3 style={{ margin: "0 0 0.25rem", fontSize: "0.85rem", letterSpacing: "0.1em", color: "#d8f63a", textTransform: "uppercase" }}>Run history</h3>
          {results === null && <p style={{ fontSize: "0.8rem", opacity: 0.7 }}>Loading…</p>}
          {results && results.length === 0 && <p style={{ fontSize: "0.8rem", opacity: 0.7 }}>No runs yet. Click "Run again" to score this slip.</p>}
          {results && results.length > 0 && (
            <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {results.map((r) => <ResultRow key={r.id} result={r} />)}
            </ul>
          )}
        </section>
      )}
    </article>
  );
}

function PageHeader({ count, busy, onRefresh }: { count: number; busy: boolean; onRefresh: () => void }): ReactElement {
  return (
    <header style={{ marginBottom: "1.5rem", display: "flex", justifyContent: "space-between", alignItems: "baseline", flexWrap: "wrap", gap: "0.6rem" }}>
      <div>
        <a href="/" style={{ color: "#d8f63a", textDecoration: "none", fontSize: "0.78rem", letterSpacing: "0.08em" }}>← Back to dashboard</a>
        <h1 style={{ margin: "0.4rem 0 0", fontSize: "1.8rem" }}>Saved Slips</h1>
        <p style={{ margin: "0.3rem 0 0", opacity: 0.65, fontSize: "0.85rem" }}>
          {count === 0 ? "Save a slip from the dashboard to start tracking algorithm runs." : `${count} saved slip${count === 1 ? "" : "s"} · click Run again to score with the latest data.`}
        </p>
      </div>
      <button
        type="button"
        onClick={onRefresh}
        disabled={busy}
        data-testid="slips-refresh-btn"
        style={{ padding: "0.5rem 1rem", borderRadius: "999px", border: "1px solid rgba(216,246,58,0.4)", background: "transparent", color: "#d8f63a", cursor: busy ? "not-allowed" : "pointer", fontSize: "0.85rem" }}
      >
        {busy ? "Loading…" : "Refresh"}
      </button>
    </header>
  );
}

function EmptyState(): ReactElement {
  return (
    <div
      data-testid="slips-empty"
      style={{ padding: "3rem 1.5rem", textAlign: "center", borderRadius: "14px", border: "1px dashed rgba(255,255,255,0.15)", background: "rgba(255,255,255,0.02)" }}
    >
      <h2 style={{ margin: 0, fontSize: "1.1rem", opacity: 0.85 }}>No slips saved yet</h2>
      <p style={{ margin: "0.6rem 0 1.2rem", opacity: 0.6, maxWidth: "44ch", marginInline: "auto", fontSize: "0.88rem" }}>
        Head to the dashboard, build a slip, click "Run Algorithm", then "Save slip to my account". You'll see it here with full run history.
      </p>
      <a
        href="/"
        data-testid="slips-empty-cta"
        style={{ display: "inline-block", padding: "0.7rem 1.3rem", borderRadius: "999px", background: "#d8f63a", color: "#0b1606", textDecoration: "none", fontWeight: 700 }}
      >
        Build a slip
      </a>
    </div>
  );
}

export default function DashboardSlipsPage(): ReactElement {
  const [state, setState] = useState<State>({ slips: [], loading: true, error: null });

  // setState is a stable React setter — listed here only to satisfy exhaustive-deps.
  async function load(): Promise<void> {
    setState((s) => ({ ...s, loading: true, error: null }));
    try {
      const data = await api.listSlips();
      setState({ slips: data.items as unknown as SavedSlip[], loading: false, error: null });
    } catch (ex) {
      const msg = ex instanceof Error ? ex.message : "Failed to load slips";
      const requiresAuth = msg.toLowerCase().includes("auth") || msg.includes("401");
      if (requiresAuth) {
        window.location.href = "/login?next=/dashboard/slips";
        return;
      }
      setState({ slips: [], loading: false, error: msg });
    }
  }

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function handleDelete(id: number): Promise<void> {
    if (!confirm("Delete this slip? This cannot be undone.")) return;
    await api.deleteSlip(id);
    load();
  }

  return (
    <main style={{ minHeight: "100vh", padding: "2rem 1.5rem 4rem", maxWidth: "920px", margin: "0 auto" }} data-testid="dashboard-slips-page">
      <PageHeader count={state.slips.length} busy={state.loading} onRefresh={load} />
      {state.error && <div data-testid="slips-error" style={{ padding: "1rem", borderRadius: "10px", background: "rgba(255,80,80,0.1)", color: "#ff9090", fontSize: "0.85rem" }}>{state.error}</div>}
      {!state.loading && state.slips.length === 0 && <EmptyState />}
      {state.slips.map((slip) => (
        <SlipCard key={slip.id} slip={slip} onDelete={handleDelete} onRunComplete={load} />
      ))}
    </main>
  );
}
