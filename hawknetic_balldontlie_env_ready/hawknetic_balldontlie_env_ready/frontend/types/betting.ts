export type Bookmaker = "bet365" | "manual" | string;

export type MarketType =
  | "moneyline"
  | "spread"
  | "total"
  | "player_prop"
  | "team_prop"
  | "same_game_parlay";

export type Recommendation =
  | "PLACE"
  | "PASS"
  | "ADJUST"
  | "HEDGE"
  | "INSUFFICIENT_DATA";

export type BetSlipLeg = {
  id: string;
  sport: "NBA" | "MLB" | "NFL" | "NHL" | "NCAAB" | string;
  bookmaker: Bookmaker;
  gameId: string;
  eventLabel: string;
  startsAt?: string;
  marketType: MarketType;
  selection: string;
  line?: number | null;
  oddsAmerican: number;
  teamId?: string | null;
  playerId?: string | null;
  playerName?: string | null;
  notes?: string | null;
};

export type SlipAnalysisRequest = {
  bookmaker: Bookmaker;
  stake: number;
  legs: BetSlipLeg[];
};

export type LegClassification = "Strong play" | "Playable" | "Lean" | "Pass" | "Trap";

export type LegAnalysis = {
  legId: string;
  selection: string;
  marketType: MarketType;
  modelProbability: number | null;
  impliedProbability: number | null;
  edgePct: number | null;
  confidenceTier: "HIGH" | "MEDIUM" | "LOW" | "FRAGILE" | "INSUFFICIENT_DATA";
  verdict: Recommendation;
  warnings: string[];
  explanation: string;
  // v2 spec §25 additions
  noVigProbability?: number;
  noVigAvailable?: boolean;
  americanOdds?: number;
  decimalOdds?: number;
  ev?: number;
  evPerUnit?: number;
  projection?: number;
  projectionStd?: number;
  marginOfError?: number | null;
  ci95?: [number, number] | null;
  confidenceScore?: number;
  classification?: LegClassification;
  edgeLabel?: string;
  trapFlags?: string[];
  kellyFraction?: number;
  kellyRecommended?: number;
  statLabel?: string;
  inactivePlayer?: boolean;
  fairAmericanOdds?: number | null;
};

export type SlipReadiness = {
  ready: boolean;
  status: "ready" | "not_ready";
  blocking_reasons: string[];
  warnings: string[];
  last_updated: string | null;
  checks: Record<string, boolean>;
};

export type SlipAnalysisResponse = {
  ok: boolean;
  slipId?: string;
  bookmaker: Bookmaker;
  stake: number;
  legCount: number;
  parlayAmericanOdds: number | null;
  impliedProbability: number | null;
  modelWinProbability: number | null;
  edgePct: number | null;
  expectedValue: number | null;
  fairAmericanOdds: number | null;
  recommendation: Recommendation;
  confidenceTier: "HIGH" | "MEDIUM" | "LOW" | "FRAGILE" | "INSUFFICIENT_DATA";
  summary: string;
  warnings: string[];
  legAnalyses: LegAnalysis[];
  betterAlternatives: Array<{
    title: string;
    reason: string;
    replacementLeg?: BetSlipLeg;
  }>;
  // v2 spec §25 additions
  parlayDecimalOdds?: number;
  parlayProbability?: number;
  parlayEv?: number;
  parlayEvPerUnit?: number;
  parlayEdge?: number;
  parlayConfidenceScore?: number;
  parlayClassification?: LegClassification | "INSUFFICIENT_DATA";
  parlayCi95?: [number, number] | null;
  parlayKellyFraction?: number;
  parlayKellyRecommended?: number;
  correlationMatrix?: number[][];
  correlationWarning?: string | null;
  bestLeg?: string;
  worstLeg?: string;
  trapLegs?: string[];
  simulationRuns?: number;
  readiness?: SlipReadiness;
};
