"use client";

import { useEffect, useMemo, useState } from "react";
import {
  closestCenter,
  DndContext,
  KeyboardSensor,
  PointerSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { api, type Game, type Prop } from "../../lib/api";
import type { BetSlipLeg, Bookmaker, MarketType, SlipAnalysisResponse } from "../../types/betting";

type MarketTab = "Popular" | "Moneyline" | "Spread" | "Total" | "Player Props" | "Same Game";
type SportFilter = "All" | "NBA" | "MLB" | "NFL" | "NHL";

type MarketOption = {
  id: string;
  label: string;
  line?: number | null;
  oddsAmerican: number | null;
  marketType: MarketType;
  eventLabel: string;
  gameId: string;
  startsAt?: string;
  playerId?: string | null;
  playerName?: string | null;
  source: "props" | "odds";
};

const marketTabs: MarketTab[] = ["Popular", "Moneyline", "Spread", "Total", "Player Props", "Same Game"];
const sportFilters: SportFilter[] = ["All", "NBA", "MLB", "NFL", "NHL"];

function formatOdds(value?: number | null) {
  if (value === undefined || value === null) return "No odds";
  return value > 0 ? `+${value}` : String(value);
}

function americanToDecimal(odds: number) {
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}

function payoutPreview(legs: BetSlipLeg[], stake: number) {
  if (!legs.length || !stake) return 0;
  const decimal = legs.reduce((product, leg) => product * americanToDecimal(leg.oddsAmerican), 1);
  return stake * decimal;
}

function marketTypeFromLabel(label?: string): MarketType {
  const text = (label || "").toLowerCase();
  if (text.includes("moneyline")) return "moneyline";
  if (text.includes("spread")) return "spread";
  if (text.includes("total") || text.includes("over") || text.includes("under")) return "total";
  if (text.includes("player") || text.includes("points") || text.includes("rebounds") || text.includes("assists")) return "player_prop";
  if (text.includes("team")) return "team_prop";
  return "player_prop";
}

function eventLabelForGame(game?: Game) {
  if (!game) return "Event data unavailable";
  return `${game.visitor_team_name || game.visitor_team_abbr || "Away"} @ ${game.home_team_name || game.home_team_abbr || "Home"}`;
}

function DragOddsButton({ option, onAdd }: { option: MarketOption; onAdd: (option: MarketOption) => void }) {
  const disabled = option.oddsAmerican === null;
  const { attributes, listeners, setNodeRef, transform } = useDraggable({ id: `option:${option.id}`, disabled });
  const style = transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined;
  return (
    <button ref={setNodeRef} style={style} className="oddsButton" disabled={disabled} onClick={() => onAdd(option)} {...listeners} {...attributes}>
      <span>{option.label}</span>
      {option.line !== undefined && option.line !== null && <small>Line {option.line}</small>}
      <strong>{disabled ? "No odds available" : formatOdds(option.oddsAmerican)}</strong>
    </button>
  );
}

function SortableSlipLeg({ leg, index, onRemove, onMove }: { leg: BetSlipLeg; index: number; onRemove: (id: string) => void; onMove: (index: number, direction: -1 | 1) => void }) {
  const { attributes, listeners, setNodeRef, transform, transition } = useSortable({ id: leg.id });
  return (
    <article ref={setNodeRef} className="betSlipLegCard" style={{ transform: CSS.Transform.toString(transform), transition }}>
      <button className="dragHandle" type="button" {...attributes} {...listeners} aria-label={`Drag ${leg.selection}`}>::</button>
      <div>
        <strong>{leg.selection}</strong>
        <p>{leg.eventLabel}</p>
        <small>{leg.marketType.replaceAll("_", " ")} {leg.line ?? ""} · {formatOdds(leg.oddsAmerican)}</small>
      </div>
      <div className="legControls">
        <button type="button" disabled={index === 0} onClick={() => onMove(index, -1)}>Up</button>
        <button type="button" onClick={() => onMove(index, 1)}>Down</button>
        <button type="button" onClick={() => onRemove(leg.id)}>Remove</button>
      </div>
    </article>
  );
}

function SlipDropArea({ children }: { children: React.ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: "slip-drop" });
  return <div ref={setNodeRef} className={`slipDropArea ${isOver ? "isOver" : ""}`}>{children}</div>;
}

function makeLeg(option: MarketOption, bookmaker: Bookmaker): BetSlipLeg {
  return {
    id: `${option.id}-${Date.now()}`,
    sport: "NBA",
    bookmaker,
    gameId: option.gameId,
    eventLabel: option.eventLabel,
    startsAt: option.startsAt,
    marketType: option.marketType,
    selection: option.label,
    line: option.line ?? null,
    oddsAmerican: option.oddsAmerican || 100,
    playerId: option.playerId ?? null,
    playerName: option.playerName ?? null,
    notes: option.source === "props" ? option.id : null,
  };
}

export default function HawkBet365DecisionDashboard() {
  const [games, setGames] = useState<Game[]>([]);
  const [props, setProps] = useState<Prop[]>([]);
  const [odds, setOdds] = useState<Array<Record<string, unknown>>>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [sport, setSport] = useState<SportFilter>("NBA");
  const [activeTab, setActiveTab] = useState<MarketTab>("Popular");
  const [activeGameId, setActiveGameId] = useState<string | null>(null);
  const [bookmaker, setBookmaker] = useState<Bookmaker>("bet365");
  const [stake, setStake] = useState(10);
  const [legs, setLegs] = useState<BetSlipLeg[]>([]);
  const [analysis, setAnalysis] = useState<SlipAnalysisResponse | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [slipOpen, setSlipOpen] = useState(false);
  const [manual, setManual] = useState({ eventLabel: "", marketType: "player_prop" as MarketType, selection: "", line: "", oddsAmerican: "" });

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  useEffect(() => {
    load();
  }, []);

  async function load() {
    setLoading(true);
    setError(null);
    try {
      const [gameResult, propResult, oddsResult] = await Promise.all([
        api.getGames(),
        api.getProps(),
        api.getOdds(),
      ]);
      setGames(gameResult.items || []);
      setProps(propResult.items || []);
      setOdds((oddsResult.items || []) as Array<Record<string, unknown>>);
      setActiveGameId(String(gameResult.items?.[0]?.id || propResult.items?.[0]?.game_id || "manual"));
    } catch {
      setError("Markets are temporarily unavailable. You can still add a market manually for the algorithm to score.");
    } finally {
      setLoading(false);
    }
  }

  const gameMap = useMemo(() => new Map(games.map((game) => [String(game.id), game])), [games]);
  const marketOptions = useMemo<MarketOption[]>(() => {
    const fromProps = props.flatMap((prop) => {
      const gameId = String(prop.game_id || "manual");
      const game = gameMap.get(gameId);
      const base = {
        line: prop.line ?? null,
        marketType: marketTypeFromLabel(prop.market || prop.selection),
        eventLabel: eventLabelForGame(game),
        gameId,
        startsAt: game?.game_date,
        playerId: prop.player_id ? String(prop.player_id) : null,
        source: "props" as const,
      };
      const label = `${prop.market || prop.selection || "Prop"} ${prop.line ?? ""}`.trim();
      return [
        { ...base, id: `prop-${prop.id || label}-over`, label, oddsAmerican: prop.over_odds ?? null },
        { ...base, id: `prop-${prop.id || label}-under`, label: label.toLowerCase().includes("under") ? label : `${label} under`, oddsAmerican: prop.under_odds ?? null },
      ].filter((option) => option.oddsAmerican !== null || prop.over_odds === undefined && prop.under_odds === undefined);
    });
    const fromOdds = odds.map((row, index) => {
      const gameId = String(row.game_id || "manual");
      return {
        id: `odds-${row.id || index}`,
        label: String(row.selection || row.market || "Market"),
        line: null,
        oddsAmerican: typeof row.odds_value === "number" ? row.odds_value : null,
        marketType: marketTypeFromLabel(String(row.market || "")),
        eventLabel: eventLabelForGame(gameMap.get(gameId)),
        gameId,
        source: "odds" as const,
      };
    });
    return [...fromProps, ...fromOdds];
  }, [gameMap, odds, props]);

  const filteredOptions = marketOptions.filter((option) => {
    const activeGameMatch = !activeGameId || activeGameId === "manual" || option.gameId === activeGameId;
    const tabMatch = activeTab === "Popular" || activeTab === "Player Props" && option.marketType === "player_prop" || activeTab === "Moneyline" && option.marketType === "moneyline" || activeTab === "Spread" && option.marketType === "spread" || activeTab === "Total" && option.marketType === "total" || activeTab === "Same Game";
    return activeGameMatch && tabMatch;
  });

  function addOption(option: MarketOption) {
    if (option.oddsAmerican === null) return;
    setAnalysis(null);
    setLegs((current) => [...current, makeLeg(option, bookmaker)]);
    setSlipOpen(true);
  }

  function removeLeg(id: string) {
    setAnalysis(null);
    setLegs((current) => current.filter((leg) => leg.id !== id));
  }

  function moveLeg(index: number, direction: -1 | 1) {
    setAnalysis(null);
    setLegs((current) => {
      const target = index + direction;
      if (target < 0 || target >= current.length) return current;
      return arrayMove(current, index, target);
    });
  }

  function onDragEnd(event: DragEndEvent) {
    const { active, over } = event;
    if (!over) return;
    const activeId = String(active.id);
    const overId = String(over.id);
    if (activeId.startsWith("option:") && overId === "slip-drop") {
      const option = marketOptions.find((item) => `option:${item.id}` === activeId);
      if (option) addOption(option);
      return;
    }
    if (activeId !== overId && legs.some((leg) => leg.id === activeId)) {
      const oldIndex = legs.findIndex((leg) => leg.id === activeId);
      const newIndex = legs.findIndex((leg) => leg.id === overId);
      if (oldIndex !== -1 && newIndex !== -1) setLegs((current) => arrayMove(current, oldIndex, newIndex));
    }
  }

  function addManualLeg() {
    const oddsAmerican = Number(manual.oddsAmerican);
    if (!manual.eventLabel || !manual.selection || !Number.isFinite(oddsAmerican) || oddsAmerican === 0) return;
    setAnalysis(null);
    setLegs((current) => [...current, {
      id: `manual-${Date.now()}`,
      sport: sport === "All" ? "NBA" : sport,
      bookmaker,
      gameId: `manual-${manual.eventLabel.toLowerCase().replace(/[^a-z0-9]+/g, "-")}`,
      eventLabel: manual.eventLabel,
      marketType: manual.marketType,
      selection: manual.selection,
      line: manual.line ? Number(manual.line) : null,
      oddsAmerican,
      notes: "Manual market entry",
    }]);
    setManual({ eventLabel: "", marketType: "player_prop", selection: "", line: "", oddsAmerican: "" });
    setSlipOpen(true);
  }

  async function analyze() {
    if (!legs.length) return;
    setAnalyzing(true);
    setError(null);
    try {
      setAnalysis(await api.analyzeSlip({ bookmaker, stake, legs }));
      setSlipOpen(true);
    } catch {
      setError("Algorithm run is temporarily unavailable. Try again shortly.");
    } finally {
      setAnalyzing(false);
    }
  }

  const slipContent = (
    <aside className="hnSlip" data-testid="algorithm-slip">
      <div className="hnSlipHeader">
        <div>
          <p>Prediction tool · no wagers placed</p>
          <h2>Algorithm Run</h2>
        </div>
        <strong data-testid="slip-leg-count">{legs.length}</strong>
      </div>
      <label className="hnField">Data source
        <select value={bookmaker} onChange={(event) => setBookmaker(event.target.value)} data-testid="bookmaker-select">
          <option value="bet365">Reference sportsbook lines</option>
          <option value="manual">Manual entry</option>
        </select>
      </label>
      <SlipDropArea>
        <SortableContext items={legs.map((leg) => leg.id)} strategy={verticalListSortingStrategy}>
          {legs.length ? legs.map((leg, index) => <SortableSlipLeg key={leg.id} leg={leg} index={index} onRemove={removeLeg} onMove={moveLeg} />) : <div className="hnEmptySlip">Click or drag a market here to add it to your algorithm run. This tool predicts — it does not place wagers.</div>}
        </SortableContext>
      </SlipDropArea>
      <details className="manualEntry">
        <summary>Manual market entry</summary>
        <input placeholder="Event label" value={manual.eventLabel} onChange={(event) => setManual({ ...manual, eventLabel: event.target.value })} />
        <select value={manual.marketType} onChange={(event) => setManual({ ...manual, marketType: event.target.value as MarketType })}>
          <option value="moneyline">Moneyline</option>
          <option value="spread">Spread</option>
          <option value="total">Total</option>
          <option value="player_prop">Player prop</option>
          <option value="team_prop">Team prop</option>
          <option value="same_game_parlay">Same game parlay</option>
        </select>
        <input placeholder="Selection" value={manual.selection} onChange={(event) => setManual({ ...manual, selection: event.target.value })} />
        <input placeholder="Line" value={manual.line} onChange={(event) => setManual({ ...manual, line: event.target.value })} />
        <input placeholder="American odds" value={manual.oddsAmerican} onChange={(event) => setManual({ ...manual, oddsAmerican: event.target.value })} />
        <button type="button" onClick={addManualLeg}>Add manual leg</button>
      </details>
      <label className="hnField">Confidence weight
        <input type="number" min="0" value={stake} onChange={(event) => setStake(Number(event.target.value))} data-testid="stake-input" />
      </label>
      <div className="payoutPreview"><span>Projected payout multiple</span><strong data-testid="payout-preview">${payoutPreview(legs, stake).toFixed(2)}</strong></div>
      <button className="analyzeButton" type="button" disabled={!legs.length || analyzing} onClick={analyze} data-testid="run-algorithm-button">{analyzing ? "Running algorithm..." : "Run Algorithm"}</button>
      {analysis && <section className={`analysisPanel ${analysis.recommendation.toLowerCase()}`} data-testid="algorithm-result">
        <p>Algorithm verdict</p>
        <h3>{analysis.recommendation.replaceAll("_", " ")}</h3>
        <strong>{analysis.summary}</strong>
        <div className="analysisMetrics">
          <span>Model win <b>{analysis.modelWinProbability === null ? "Insufficient data" : `${Math.round(analysis.modelWinProbability * 100)}%`}</b></span>
          <span>Market implied <b>{analysis.impliedProbability === null ? "-" : `${Math.round(analysis.impliedProbability * 100)}%`}</b></span>
          <span>Edge <b>{analysis.edgePct === null ? "-" : `${analysis.edgePct.toFixed(1)}%`}</b></span>
          <span>Expected value <b>{analysis.expectedValue === null ? "-" : `$${analysis.expectedValue.toFixed(2)}`}</b></span>
          <span>Fair odds <b>{analysis.fairAmericanOdds ?? "-"}</b></span>
          <span>Confidence <b>{analysis.confidenceTier}</b></span>
        </div>
        {analysis.warnings.length ? <div className="warningList"><b>Trap warnings</b>{analysis.warnings.map((warning) => <span key={warning}>{warning}</span>)}</div> : null}
        <div className="legAnalysisList">{analysis.legAnalyses.map((leg) => <article key={leg.legId}><strong>{leg.selection} · {leg.verdict}</strong><p>{leg.explanation}</p>{leg.warnings.map((warning) => <small key={warning}>{warning}</small>)}</article>)}</div>
        {analysis.betterAlternatives.length ? <div className="betterAlternatives"><b>Smarter alternatives</b>{analysis.betterAlternatives.map((item) => <span key={item.title}>{item.title}: {item.reason}</span>)}</div> : null}
      </section>}
    </aside>
  );

  return (
    <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
      <main className="hnBetDashboard" data-testid="hawknetic-dashboard">
        <header className="hnTopbar">
          <div>
            <p>Prediction tool · no wagers placed</p>
            <h1>HawkNetic Predictor Tools</h1>
            <span>Build an event slate the way a sportsbook would display one, then press <strong>Run Algorithm</strong> to score every leg with the HawkNetic prediction models.</span>
          </div>
          <div className="hnStatusChips" data-testid="status-chips">
            <span>Algorithm-Powered</span>
            <span>No wagers placed here</span>
            <span>Prediction &amp; Decision Support</span>
            <button type="button" onClick={() => load()} disabled={loading} data-testid="refresh-markets-btn" style={{ background: "rgba(216,246,58,.14)", color: "#d8f63a", borderColor: "rgba(216,246,58,.4)" }}>{loading ? "Refreshing…" : "Refresh markets"}</button>
          </div>
        </header>
        {loading && <div className="hnNotice">Loading available markets...</div>}
        {error && <div className="hnError">{error}</div>}
        <section className="hnMainGrid">
          <aside className="hnSportsBoard" data-testid="sports-board">
            <h2>Sports &amp; Events</h2>
            <div className="sportFilters">{sportFilters.map((item) => <button key={item} className={sport === item ? "active" : ""} onClick={() => setSport(item)} data-testid={`sport-filter-${item.toLowerCase()}`}>{item}</button>)}</div>
            <div className="gameList">
              {games.length ? games.map((game) => <button type="button" key={game.id} className={activeGameId === String(game.id) ? "active" : ""} onClick={() => setActiveGameId(String(game.id))} data-testid={`game-${game.id}`}><strong>{eventLabelForGame(game)}</strong><span>{game.game_date || "Start time pending"}</span><small>{game.status || "Market status pending"}</small></button>) : <p>Not enough data available yet. You can still add a market manually for the algorithm to score.</p>}
            </div>
          </aside>
          <section className="hnMarketBoard" data-testid="market-board">
            <div className="marketTabs">{marketTabs.map((tab) => <button key={tab} className={activeTab === tab ? "active" : ""} onClick={() => setActiveTab(tab)} data-testid={`market-tab-${tab.toLowerCase().replace(/ /g, "-")}`}>{tab}</button>)}</div>
            <div className="marketRows">
              {filteredOptions.length ? filteredOptions.map((option) => <article key={option.id} className="marketRow"><div><strong>{option.eventLabel}</strong><span>{option.marketType.replaceAll("_", " ")}</span></div><DragOddsButton option={option} onAdd={addOption} /></article>) : <div className="hnEmptyMarket">Not enough data available yet. Add a market manually and HawkNetic will score what it can.</div>}
            </div>
          </section>
          <div className="hnDesktopSlip">{slipContent}</div>
        </section>
        <button className="mobileSlipToggle" type="button" onClick={() => setSlipOpen((open) => !open)} data-testid="mobile-slip-toggle">Run ({legs.length}) · Predict</button>
        <div className={`hnMobileSlip ${slipOpen ? "open" : ""}`}>{slipContent}</div>
        <footer className="hnFooter"><span>Prediction tool only. HawkNetic does not accept or place wagers.</span><a href="/admin" data-testid="admin-link">Admin</a></footer>
      </main>
    </DndContext>
  );
}
