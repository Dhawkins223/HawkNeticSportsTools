export type DataStatusBadgeState = "ok" | "warning" | "error";

export type ApiEnvelope<T> = T & { detail?: string };

export type DatabaseStatus = {
  ok: boolean;
  engine: string;
  railway_postgres: boolean;
  table_count: number;
  error: string | null;
};

export type HealthResponse = {
  status: "ok" | "degraded";
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
  historical_coverage: HistoricalCoverage;
  bdl: BdlStatus;
  mappings: Record<string, number>;
  modeling: Record<string, number>;
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

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8000";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    credentials: "include",
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
    ...init,
  });
  const data = (await response.json().catch(() => ({ detail: "Backend returned a non-JSON response." }))) as ApiEnvelope<T>;
  if (!response.ok) {
    throw new Error(data.detail || `FastAPI request failed with ${response.status}`);
  }
  return data as T;
}

export const api = {
  health: () => request<HealthResponse>("/api/health"),
  dataStatus: () => request<DataStatus>("/api/data-status"),
  games: () => request<{ items: Game[] }>("/api/games"),
  players: () => request<{ items: Player[] }>("/api/players"),
  props: () => request<{ items: Prop[] }>("/api/props"),
  odds: () => request<{ items: unknown[] }>("/api/odds"),
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
  backfillSeason: (season: number, maxBoxScores?: number) => request<{ ok: boolean; season: number; coverage: HistoricalCoverage }>(`/api/historical/backfill/${season}${maxBoxScores ? `?max_box_scores=${maxBoxScores}` : ""}`, { method: "POST" }),
  backfillRecent: (maxBoxScores?: number) => request<{ ok: boolean; seasons: number[]; coverage: HistoricalCoverage }>(`/api/historical/backfill/recent${maxBoxScores ? `?max_box_scores=${maxBoxScores}` : ""}`, { method: "POST" }),
  cavsPractice: () => request<{ games_available: number; completed_games: number; recent_wins: number; recent_losses: number; practice_confidence: number; games: Game[] }>("/api/practice/cavs"),
};
