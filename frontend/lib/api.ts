import type { SlipAnalysisRequest, SlipAnalysisResponse } from "../types/betting";

export type ApiEnvelope<T> = T & { detail?: string };

export type DatabaseStatus = {
  ok: boolean;
  connected?: boolean;
  engine: string;
  railway_postgres: boolean;
  database_url_present?: boolean;
  table_count: number;
  error: string | null;
};

export type DatabaseReadiness = {
  engine: string;
  database_url_present: boolean;
  database_connected: boolean;
  table_count: number;
  missing_expected_tables: string[];
  missing_tables?: string[];
  row_counts: Record<string, number | null>;
  dashboard_ready: boolean;
  blocking_reasons: string[];
  warnings: string[];
  empty_important_tables?: string[];
  historical_coverage?: HistoricalCoverage | { error: string } | null;
  latest_import_job?: Record<string, unknown> | null;
};

export type HealthResponse = {
  ok: boolean;
  status: "ok" | "degraded";
  service: string;
  environment: string;
  database_engine: string;
  database_connected: boolean;
  database: DatabaseStatus;
  ball_dont_lie_configured: boolean;
};

export type HistoricalCoverage = {
  start_season: number;
  end_season: number;
  total_seasons: number;
  complete_seasons: number;
  incomplete_seasons: number;
  oldest_scraped_season?: number | null;
  newest_scraped_season?: number | null;
  total_games_stored?: number;
  total_player_game_stat_rows?: number;
  total_team_game_stat_rows?: number;
  missing_seasons?: number[];
  missing_box_scores?: number;
  failed_urls?: number;
  last_scrape_time?: string | null;
  last_import_time?: string | null;
  seasons: Array<{ season: number; status: string; actual_records: number; coverage_percent?: number; details_json?: string }>;
};

export type BdlStatus = {
  counts: Record<string, number>;
  latest: Array<Record<string, unknown>>;
};

export type DataStatus = {
  database: DatabaseStatus;
  readiness?: DatabaseReadiness;
  historical_coverage: HistoricalCoverage | null;
  bdl: BdlStatus;
  mappings: Record<string, number>;
  modeling: Record<string, number>;
  message?: string | null;
};
export type HistoricalScrapeErrorsResponse = {
  ok: boolean;
  season: number;
  exists: boolean;
  error_count: number;
  errors: Array<{ url: string; error: string; status_code: string; response_snippet: string; timestamp: string }>;
  file_path: string;
  message?: string;
};

export type Game = {
  id: number;
  game_date?: string;
  status?: string;
  home_team_name?: string;
  visitor_team_name?: string;
  home_team_abbr?: string;
  visitor_team_abbr?: string;
  home_score?: number;
  away_score?: number;
  home_team_score?: number;
  visitor_team_score?: number;
};

export type Player = {
  id: number;
  full_name: string;
  position?: string;
  team_abbr?: string;
};

export type Prop = {
  id?: number;
  game_id?: number;
  player_id?: number;
  market?: string;
  selection?: string;
  line?: number;
  over_odds?: number;
  under_odds?: number;
  model_probability?: number;
  expected_value?: number;
  confidence_tier?: string;
};

export type Simulation = {
  id: number;
  game_id?: number;
  runs?: number;
  confidence?: number;
  result_json?: string;
  created_at?: string;
};

export type ParlayLegInput = {
  prop_id?: number;
  label: string;
  odds_value?: number;
  probability?: number;
  expected_value?: number;
  confidence_tier?: string;
};

export type ParlayResult = {
  id: number;
  estimated_odds?: number;
  win_probability: number;
  loss_probability: number;
  expected_value: number;
  risk_tier: string;
  confidence_tier?: string;
  correlation_warning?: string;
  trap_leg_warning?: string;
  legs?: ParlayLegInput[];
};

const RAW_API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL;
const API_BASE_URL = RAW_API_BASE_URL || (process.env.NODE_ENV === "production" ? "" : "http://127.0.0.1:8000");

function apiBaseUrl() {
  if (!API_BASE_URL) {
    throw new Error("Frontend cannot reach backend API. Check NEXT_PUBLIC_API_BASE_URL.");
  }
  if (process.env.NODE_ENV === "production" && /^(http:\/\/)?(localhost|127\.0\.0\.1)(:\d+)?/i.test(API_BASE_URL)) {
    throw new Error("Frontend cannot reach backend API. Check NEXT_PUBLIC_API_BASE_URL.");
  }
  return API_BASE_URL.replace(/\/$/, "");
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    const response = await fetch(`${apiBaseUrl()}${path}`, {
      credentials: "same-origin",
      cache: "no-store",
      mode: "cors",
      headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
      ...init,
    });
    const data = (await response.json().catch(() => ({ detail: "Backend returned a non-JSON response." }))) as ApiEnvelope<T>;
    if (!response.ok) {
      throw new Error(data.detail || `FastAPI request failed with ${response.status}`);
    }
    return data as T;
  } catch (err) {
    if (err instanceof Error && err.message.includes("NEXT_PUBLIC_API_BASE_URL")) {
      throw err;
    }
    throw new Error(`Frontend cannot reach backend API. Check NEXT_PUBLIC_API_BASE_URL. ${err instanceof Error ? err.message : ""}`.trim());
  }
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  dataStatus: () => request<DataStatus>("/api/data-status"),
  databaseStatus: () => request<DatabaseStatus>("/api/database/status"),
  databaseReadiness: () => request<DatabaseReadiness>("/api/database/readiness"),
  tableCounts: () => request<{ ok: boolean; row_counts: Record<string, number | null>; missing_tables: string[]; errors: Record<string, string> }>("/api/debug/table-counts"),
  games: () => request<{ items: Game[] }>("/api/games"),
  getGames: () => request<{ items: Game[] }>("/api/games"),
  players: () => request<{ items: Player[] }>("/api/players"),
  props: () => request<{ items: Prop[] }>("/api/props"),
  getProps: () => request<{ items: Prop[] }>("/api/props"),
  odds: () => request<{ items: unknown[] }>("/api/odds"),
  getOdds: () => request<{ items: unknown[] }>("/api/odds"),
  analyzeSlip: (payload: SlipAnalysisRequest) => request<SlipAnalysisResponse>("/api/slips/analyze", {
    method: "POST",
    body: JSON.stringify(payload),
  }),
  simulations: () => request<{ items: Simulation[] }>("/api/simulations"),
  runSimulation: (runs = 1000, gameId?: number) => request<{ ok: boolean; result: Simulation }>("/api/simulations/run", {
    method: "POST",
    body: JSON.stringify({ runs, game_id: gameId }),
  }),
  parlays: () => request<{ items: ParlayResult[] }>("/api/parlays"),
  buildParlay: (legs: ParlayLegInput[], name = "React Dashboard Parlay") => request<{ ok: boolean; parlay: ParlayResult }>("/api/parlays/build", {
    method: "POST",
    body: JSON.stringify({ name, legs }),
  }),
  reorderParlay: (parlayId: number, legIds: number[]) => request<{ ok: boolean }>("/api/parlays/reorder", {
    method: "POST",
    body: JSON.stringify({ parlay_id: parlayId, leg_ids: legIds }),
  }),
  bdlLogs: () => request<{ items: Array<Record<string, unknown>> }>("/api/bdl/logs"),
  historicalCoverage: () => request<HistoricalCoverage>("/api/historical/coverage"),
  historicalScrapeErrors: (season: number) => request<HistoricalScrapeErrorsResponse>(`/api/historical/scrape-errors/${season}`),
  backfillSeason: (season: number, maxBoxScores?: number) => request<{ ok: boolean; season: number; coverage: HistoricalCoverage }>(`/api/historical/backfill/${season}${maxBoxScores ? `?max_box_scores=${maxBoxScores}` : ""}`, { method: "POST" }),
  historicalBackfillSeason: (season: number, maxBoxScores?: number) => request<{ ok: boolean; season: number; coverage: HistoricalCoverage }>(`/api/historical/backfill/${season}${maxBoxScores ? `?max_box_scores=${maxBoxScores}` : ""}`, { method: "POST" }),
  backfillRecent: (maxBoxScores?: number) => request<{ ok: boolean; seasons: number[]; coverage: HistoricalCoverage }>(`/api/historical/backfill/recent${maxBoxScores ? `?max_box_scores=${maxBoxScores}` : ""}`, { method: "POST" }),
  cavsPractice: () => request<{ games_available: number; completed_games: number; recent_wins: number; recent_losses: number; practice_confidence: number; games: Game[] }>("/api/practice/cavs"),

  // ---- HawkNetic v2 (live data + math correctness) ----
  liveReadiness: () => request<LiveReadiness>("/api/live/readiness"),
  gamesToday: () => request<{ items: Game[] }>("/api/games/today"),
  gameMarkets: (gameId: string | number) => request<GameMarketsResponse>(`/api/games/${gameId}/markets`),
  liveOdds: (gameId?: string | number) => request<{ items: Array<Record<string, unknown>> }>(`/api/live/odds${gameId ? `?game_id=${gameId}` : ""}`),
  liveSnapshots: () => request<{ items: Array<Record<string, unknown>> }>("/api/live/snapshots"),
  liveSync: (kind: string, payload: Record<string, unknown>) => request<{ ok: boolean; kind?: string; rows_written?: number }>("/api/live/sync", {
    method: "POST",
    body: JSON.stringify({ kind, payload }),
  }),
  // ---- HawkNetic v3: multi-sport + auth + saved slips ----
  sports: () => request<{ items: Array<{ key: string; name: string; marketTypes: string[]; trapRules: string[]; correlationExamples: Record<string, string>; readinessKeys: string[] }> }>("/api/sports"),
  saveSlip: (name: string, sport: string, legs: Array<Record<string, unknown>>, resultJson?: Record<string, unknown>) => request<{ ok: boolean; slip: Record<string, unknown> }>("/api/slips", {
    method: "POST",
    body: JSON.stringify({ name, sport, legs, result_json: resultJson || null }),
  }),
  listSlips: () => request<{ items: Array<Record<string, unknown>> }>("/api/slips"),
  deleteSlip: (id: number) => request<{ ok: boolean }>(`/api/slips/${id}`, { method: "DELETE" }),
};

export type LiveReadiness = {
  ready: boolean;
  status: "ready" | "not_ready";
  blocking_reasons: string[];
  warnings: string[];
  last_updated: string | null;
  checks: Record<string, boolean>;
};

export type GameMarketsResponse = {
  gameId: number;
  props: Prop[];
  odds: Array<Record<string, unknown>>;
  liveOdds: Array<Record<string, unknown>>;
  liveGame: Record<string, unknown> | null;
  lineMovement: Array<Record<string, unknown>>;
};
