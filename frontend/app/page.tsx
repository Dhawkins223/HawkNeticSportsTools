"use client";

import { useEffect, useMemo, useState } from "react";
import { api, type DataStatus, type Game, type ParlayLegInput, type ParlayResult, type Player, type Prop, type Simulation } from "../lib/api";
import { DashboardLayout } from "../components/DashboardLayout";
import { DataStatusBadge } from "../components/DataStatusBadge";
import { DatabaseStatusPanel } from "../components/DatabaseStatusPanel";
import { EVTable } from "../components/EVTable";
import { GameCard } from "../components/GameCard";
import { HistoricalCoveragePanel } from "../components/HistoricalCoveragePanel";
import { IngestionStatusPanel } from "../components/IngestionStatusPanel";
import { LiveApiStatusPanel } from "../components/LiveApiStatusPanel";
import { ParlaySlip } from "../components/ParlaySlip";
import { PlayerSearch } from "../components/PlayerSearch";
import { PropTable } from "../components/PropTable";
import { SimulationCard } from "../components/SimulationCard";

export default function DashboardPage() {
  const [collapsed, setCollapsed] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<DataStatus | null>(null);
  const [games, setGames] = useState<Game[]>([]);
  const [players, setPlayers] = useState<Player[]>([]);
  const [props, setProps] = useState<Prop[]>([]);
  const [logs, setLogs] = useState<Array<Record<string, unknown>>>([]);
  const [simulations, setSimulations] = useState<Simulation[]>([]);
  const [parlays, setParlays] = useState<ParlayResult[]>([]);
  const [legs, setLegs] = useState<ParlayLegInput[]>([]);
  const [builtParlay, setBuiltParlay] = useState<ParlayResult | undefined>();
  const [adminLoading, setAdminLoading] = useState<"backfill" | "status" | "readiness" | null>(null);
  const [adminResult, setAdminResult] = useState<any>(null);

  async function refresh() {
    setError(null);
    try {
      const [dataStatus, gameData, playerData, propData, simData, parlayData, logData] = await Promise.all([
        api.dataStatus(),
        api.games(),
        api.players(),
        api.props(),
        api.simulations(),
        api.parlays(),
        api.bdlLogs(),
      ]);
      setStatus(dataStatus);
      setGames(gameData.items || []);
      setPlayers(playerData.items || []);
      setProps(propData.items || []);
      setSimulations(simData.items || []);
      setParlays(parlayData.items || []);
      setLogs(logData.items || []);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown backend failure");
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  const topGames = useMemo(() => games.slice(0, 6), [games]);

  function moveLeg(from: number, to: number) {
    if (to < 0 || to >= legs.length) return;
    const copy = [...legs];
    const [item] = copy.splice(from, 1);
    copy.splice(to, 0, item);
    setLegs(copy);
  }

  async function buildParlay() {
    try {
      const result = await api.buildParlay(legs);
      setBuiltParlay(result.parlay);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build parlay");
    }
  }

  async function runSimulation() {
    try {
      await api.runSimulation(1000);
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not run simulation");
    }
  }

  async function runBackfillTest2024() {
    setAdminLoading("backfill");
    setAdminResult(null);
    try {
      const result = await api.historicalBackfillSeason(2024);
      setAdminResult(result);
      await refresh();
    } catch (err) {
      setAdminResult({ error: err instanceof Error ? err.message : "Backfill failed" });
    } finally {
      setAdminLoading(null);
    }
  }

  async function loadDataStatus() {
    setAdminLoading("status");
    setAdminResult(null);
    try {
      const result = await api.dataStatus();
      setAdminResult(result);
      await refresh();
    } catch (err) {
      setAdminResult({ error: err instanceof Error ? err.message : "Status failed" });
    } finally {
      setAdminLoading(null);
    }
  }

  async function loadDatabaseReadiness() {
    setAdminLoading("readiness");
    setAdminResult(null);
    try {
      const result = await api.databaseReadiness();
      setAdminResult(result);
      await refresh();
    } catch (err) {
      setAdminResult({ error: err instanceof Error ? err.message : "Readiness failed" });
    } finally {
      setAdminLoading(null);
    }
  }

  return (
    <DashboardLayout collapsed={collapsed} onToggle={() => setCollapsed((value) => !value)}>
      <header className="heroPanel" id="dashboard">
        <div className="queryHeader">
          <p className="eyebrow">HawkNetic · NBA Analytics Workspace</p>
          <h1>What are the best NBA edges on the board tonight?</h1>
          <p className="queryHint">Search-like, StatMuse-inspired workflow: filter props, build a slip, then run simulations instantly.</p>
        </div>
        <div className="badgeStack">
          <DataStatusBadge label="Backend" value={error ? "error" : "connected"} state={error ? "error" : "ok"} />
          <DataStatusBadge label="Database" value={status?.database.railway_postgres ? "railway connected" : "sqlite fallback"} state={status?.database.railway_postgres ? "ok" : "warning"} />
          <DataStatusBadge label="Live Feed" value={status?.bdl ? "synced" : "checking"} state={status?.bdl ? "ok" : "warning"} />
        </div>
      </header>

      {error && <div className="errorBanner">{error}</div>}

      <section className="grid four">
        <DatabaseStatusPanel status={status?.database} />
        <HistoricalCoveragePanel coverage={status?.historical_coverage} />
        <LiveApiStatusPanel status={status?.bdl} />
        <IngestionStatusPanel logs={logs} />
      </section>

      <section className="grid two" id="games">
        <div className="panel">
          <h3>Tonight&apos;s Games</h3>
          <div className="gameGrid">{topGames.length ? topGames.map((game) => <GameCard key={game.id} game={game} />) : <p>No games in PostgreSQL yet. Sync BDL games or backfill historical/current data.</p>}</div>
        </div>
        <PlayerSearch players={players} />
      </section>

      <section className="grid two">
        <PropTable props={props} onAdd={(leg) => setLegs((current) => [...current, leg])} />
        <ParlaySlip legs={legs} result={builtParlay} onRemove={(index) => setLegs((current) => current.filter((_, i) => i !== index))} onMove={moveLeg} onBuild={buildParlay} />
      </section>

      <section className="grid three">
        <EVTable props={props} />
        <SimulationCard simulations={simulations} onRun={runSimulation} />
        <div className="panel" id="bankroll"><h3>User Slips / Tickets</h3>{parlays.length ? <ul className="compactList">{parlays.slice(0, 8).map((p) => <li key={p.id}>{p.risk_tier}<span>{Math.round((p.win_probability || 0) * 100)}% win</span></li>)}</ul> : <p>No saved parlays yet.</p>}</div>
      </section>

      <section className="grid one">
        <div className="panel" id="admin-backfill-test">
          <h3>Admin / Testing Controls</h3>
          <p>This may take several minutes and should only be used for testing ingestion.</p>
          <div className="actionsRow">
            <button type="button" onClick={runBackfillTest2024} disabled={adminLoading !== null}>
              {adminLoading === "backfill" ? "Running 2024 Backfill..." : "Run 2024 Historical Backfill Test"}
            </button>
            <button type="button" onClick={loadDataStatus} disabled={adminLoading !== null}>
              {adminLoading === "status" ? "Loading Data Status..." : "Fetch /api/data-status"}
            </button>
            <button type="button" onClick={loadDatabaseReadiness} disabled={adminLoading !== null}>
              {adminLoading === "readiness" ? "Loading Readiness..." : "Fetch /api/database/readiness"}
            </button>
          </div>
          {adminResult && <pre style={{ marginTop: 12, whiteSpace: "pre-wrap" }}>{JSON.stringify(adminResult, null, 2)}</pre>}
        </div>
      </section>
    </DashboardLayout>
  );
}
