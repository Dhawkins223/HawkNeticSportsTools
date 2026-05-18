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
import { calculateSlipMetrics, optimizeSlip, type SlipOptimizerMode } from "../lib/parlayMath";

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
  const savedSlipPreview = useMemo(() => parlays.slice(0, 6), [parlays]);
  const currentSlipMetrics = useMemo(() => calculateSlipMetrics(legs), [legs]);

  function addLeg(leg: ParlayLegInput) {
    setBuiltParlay(undefined);
    setLegs((current) => [...current, leg]);
  }

  function moveLeg(from: number, to: number) {
    if (to < 0 || to >= legs.length) return;
    const copy = [...legs];
    const [item] = copy.splice(from, 1);
    copy.splice(to, 0, item);
    setLegs(copy);
    setBuiltParlay(undefined);
  }

  function removeLeg(index: number) {
    setBuiltParlay(undefined);
    setLegs((current) => current.filter((_, i) => i !== index));
  }

  function optimizeCurrentSlip(mode: SlipOptimizerMode) {
    setBuiltParlay(undefined);
    setLegs((current) => optimizeSlip(current, mode));
  }

  async function buildParlay() {
    if (!legs.length) return;
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
          <p className="eyebrow">HawkNetic · Predictor lobby</p>
          <h1>Build the ticket. Let the model grade the chance.</h1>
          <p className="queryHint">A sportsbook-familiar board for ranking NBA legs and parlays, with analytics in place of betting.</p>
        </div>
        <div className="badgeStack">
          <DataStatusBadge label="Backend" value={error ? "error" : "connected"} state={error ? "error" : "ok"} />
          <DataStatusBadge label="Database" value={status?.database.railway_postgres ? "railway connected" : "sqlite fallback"} state={status?.database.railway_postgres ? "ok" : "warning"} />
          <DataStatusBadge label="Live Feed" value={status?.bdl ? "synced" : "checking"} state={status?.bdl ? "ok" : "warning"} />
        </div>
      </header>

      {error && <div className="errorBanner">{error}</div>}

      <section className="modeDeck">
        <a href="#props">
          <span>Mode 01</span>
          <strong>Build Slip</strong>
          <small>Scan markets by model edge.</small>
        </a>
        <a href="#parlays">
          <span>Mode 02</span>
          <strong>Smart Slip Lab</strong>
          <small>Watch probability, grade, and risk move live.</small>
        </a>
        <a href="#simulations">
          <span>Mode 03</span>
          <strong>Run Simulation</strong>
          <small>Save model-backed predictor results.</small>
        </a>
        <a href="#bankroll">
          <span>Mode 04</span>
          <strong>Review Tickets</strong>
          <small>Track history without taking bets.</small>
        </a>
      </section>

      <section className="sportsbookStats">
        <div className="statTile">
          <span>Active slip</span>
          <strong>{legs.length}</strong>
          <small>legs in order</small>
        </div>
        <div className="statTile">
          <span>Model win</span>
          <strong>{legs.length ? `${Math.round((builtParlay?.win_probability ?? currentSlipMetrics.winProbability) * 100)}%` : "--"}</strong>
          <small>{builtParlay ? "saved score" : "live lab estimate"}</small>
        </div>
        <div className="statTile">
          <span>Slip grade</span>
          <strong>{currentSlipMetrics.grade}</strong>
          <small>{currentSlipMetrics.volatility}</small>
        </div>
        <div className="statTile">
          <span>NBA board</span>
          <strong>{props.length}</strong>
          <small>available markets</small>
        </div>
        <div className="statTile">
          <span>Saved tickets</span>
          <strong>{parlays.length}</strong>
          <small>predictor history</small>
        </div>
      </section>

      <section className="sportsbookLayout">
        <PropTable props={props} onAdd={addLeg} />
        <ParlaySlip legs={legs} result={builtParlay} onRemove={removeLeg} onMove={moveLeg} onBuild={buildParlay} onOptimize={optimizeCurrentSlip} />
      </section>

      <section className="grid two" id="games">
        <div className="panel">
          <div className="panelHeader">
            <div>
              <p className="eyebrow">2K-style scouting</p>
              <h3>Tonight&apos;s matchups</h3>
            </div>
            <span className="pill">{topGames.length} games</span>
          </div>
          <div className="gameGrid">{topGames.length ? topGames.map((game) => <GameCard key={game.id} game={game} />) : <p>No games in PostgreSQL yet. Sync BDL games or backfill historical/current data.</p>}</div>
        </div>
        <PlayerSearch players={players} />
      </section>

      <section className="grid three">
        <EVTable props={props} />
        <SimulationCard simulations={simulations} onRun={runSimulation} />
        <div className="panel savedTickets" id="bankroll">
          <div className="panelHeader">
            <div>
              <p className="eyebrow">Ticket history</p>
              <h3>User slips</h3>
            </div>
            <span className="pill">analytics only</span>
          </div>
          {savedSlipPreview.length ? (
            <ul className="ticketTimeline">
              {savedSlipPreview.map((p, index) => (
                <li key={p.id}>
                  <span className="timelineDot">{index + 1}</span>
                  <div>
                    <strong>{Math.round((p.win_probability || 0) * 100)}% win · {p.risk_tier}</strong>
                    <small>Odds {p.estimated_odds ?? "-"} · Confidence {p.confidence_tier || "pending"} · EV {p.expected_value ?? 0}</small>
                  </div>
                </li>
              ))}
            </ul>
          ) : (
            <p>No saved parlays yet.</p>
          )}
        </div>
      </section>

      <section className="grid four">
        <DatabaseStatusPanel status={status?.database} />
        <HistoricalCoveragePanel coverage={status?.historical_coverage} />
        <LiveApiStatusPanel status={status?.bdl} />
        <IngestionStatusPanel logs={logs} />
      </section>

      <section className="grid one">
        <div className="panel adminPanel" id="admin-backfill-test">
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
