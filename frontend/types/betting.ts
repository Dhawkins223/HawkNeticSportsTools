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
};
