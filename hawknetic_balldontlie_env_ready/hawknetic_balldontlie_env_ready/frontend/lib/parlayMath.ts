import type { ParlayLegInput } from "./api";

export type SlipOptimizerMode = "safer" | "upside" | "ev" | "trap";

export type LegImpact = {
  edge: number;
  drag: number;
  label: string;
};

export type SlipMetrics = {
  winProbability: number;
  lossProbability: number;
  estimatedOdds?: number;
  riskTier: string;
  grade: string;
  volatility: string;
  averageProbability: number;
  averageEdge: number;
  weakestLegIndex: number;
  strongestLegIndex: number;
  legImpacts: LegImpact[];
  recommendation: string;
};

// --- Probability bounds ---
const MIN_PROBABILITY = 0.01;
const MAX_PROBABILITY = 0.99;
const DEFAULT_PROBABILITY = 0.5;
const DEFAULT_DECIMAL_ODDS = 2;

// --- Risk-tier thresholds ---
const HIGH_RISK_LEG_COUNT = 4;
const HIGH_RISK_WIN_PROBABILITY = 0.2;
const MEDIUM_RISK_LEG_COUNT = 2;

// --- Edge labels ---
const EDGE_SHARP = 0.08;
const EDGE_POSITIVE = 0.02;
const EDGE_FAIR_LOWER_BOUND = -0.03;

// --- Grade scoring weights & thresholds ---
const SCORE_WEIGHT_WIN_PROBABILITY = 60;
const SCORE_WEIGHT_AVG_PROBABILITY = 25;
const SCORE_WEIGHT_AVG_EDGE = 100;
const SCORE_EDGE_FLOOR = -0.15;
const SCORE_EDGE_CEILING = 0.25;
const GRADE_A_THRESHOLD = 58;
const GRADE_B_PLUS_THRESHOLD = 48;
const GRADE_B_THRESHOLD = 38;
const GRADE_C_PLUS_THRESHOLD = 28;

// --- Volatility ---
const VOLATILITY_CONTROLLED_UPSIDE_EDGE = 0.05;

export function clampProbability(value?: number): number {
  return Math.max(MIN_PROBABILITY, Math.min(value ?? DEFAULT_PROBABILITY, MAX_PROBABILITY));
}

export function impliedProbabilityFromOdds(odds?: number): number {
  if (!odds) return DEFAULT_PROBABILITY;
  return odds > 0 ? 100 / (odds + 100) : Math.abs(odds) / (Math.abs(odds) + 100);
}

function edgeForLeg(leg: ParlayLegInput): number {
  return clampProbability(leg.probability) - impliedProbabilityFromOdds(leg.odds_value);
}

function decimalOdds(odds?: number): number {
  if (!odds) return DEFAULT_DECIMAL_ODDS;
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}

function product(values: number[]): number {
  return values.reduce((current, value) => current * value, 1);
}

function classifyEdge(edge: number): string {
  if (edge >= EDGE_SHARP) return "Sharp edge";
  if (edge >= EDGE_POSITIVE) return "Positive lean";
  if (edge > EDGE_FAIR_LOWER_BOUND) return "Fair price";
  return "Trap risk";
}

function deriveRiskTier(legCount: number, winProbability: number): string {
  if (legCount === 0) return "ungraded";
  if (legCount >= HIGH_RISK_LEG_COUNT || winProbability < HIGH_RISK_WIN_PROBABILITY) return "high";
  if (legCount >= MEDIUM_RISK_LEG_COUNT) return "medium";
  return "low";
}

function deriveGrade(legCount: number, score: number): string {
  if (legCount === 0) return "--";
  if (score >= GRADE_A_THRESHOLD) return "A";
  if (score >= GRADE_B_PLUS_THRESHOLD) return "B+";
  if (score >= GRADE_B_THRESHOLD) return "B";
  if (score >= GRADE_C_PLUS_THRESHOLD) return "C+";
  return "D";
}

function deriveVolatility(legCount: number, riskTier: string, averageEdge: number): string {
  if (legCount === 0) return "No ticket";
  if (riskTier === "high") return "Volatile";
  if (averageEdge >= VOLATILITY_CONTROLLED_UPSIDE_EDGE) return "Controlled upside";
  return "Balanced";
}

function deriveRecommendation(legCount: number, weakestLegEdge: number, riskTier: string): string {
  if (legCount === 0) return "Add legs to unlock Smart Slip Lab.";
  if (weakestLegEdge < EDGE_FAIR_LOWER_BOUND) return "Optimizer sees one leg priced worse than the model.";
  if (riskTier === "high") return "High variance slip: consider reducing leg count.";
  return "Model profile is playable for analysis.";
}

function computeLegImpacts(legs: ParlayLegInput[], probabilities: number[], winProbability: number): LegImpact[] {
  return legs.map((leg, index) => {
    const edge = edgeForLeg(leg);
    const otherProbability = product(probabilities.filter((_, i) => i !== index));
    const drag = otherProbability - winProbability;
    return { edge, drag, label: classifyEdge(edge) };
  });
}

function indexOfExtreme(impacts: LegImpact[], comparator: (current: number, candidate: number) => boolean): number {
  let bestIndex = 0;
  for (let index = 0; index < impacts.length; index += 1) {
    if (comparator(impacts[bestIndex].edge, impacts[index].edge)) bestIndex = index;
  }
  return bestIndex;
}

export function calculateSlipMetrics(legs: ParlayLegInput[]): SlipMetrics {
  const probabilities = legs.map((leg) => clampProbability(leg.probability));
  const winProbability = legs.length ? product(probabilities) : 0;
  const lossProbability = legs.length ? 1 - winProbability : 0;
  const estimatedOdds = winProbability > 0 ? Math.round((1 / winProbability - 1) * 100) : undefined;
  const riskTier = deriveRiskTier(legs.length, winProbability);
  const legImpacts = computeLegImpacts(legs, probabilities, winProbability);

  const averageProbability = probabilities.length
    ? probabilities.reduce((sum, value) => sum + value, 0) / probabilities.length
    : 0;
  const averageEdge = legImpacts.length
    ? legImpacts.reduce((sum, impact) => sum + impact.edge, 0) / legImpacts.length
    : 0;

  const weakestLegIndex = legImpacts.length ? indexOfExtreme(legImpacts, (current, candidate) => candidate < current) : 0;
  const strongestLegIndex = legImpacts.length ? indexOfExtreme(legImpacts, (current, candidate) => candidate > current) : 0;

  const clampedAverageEdge = Math.max(SCORE_EDGE_FLOOR, Math.min(averageEdge, SCORE_EDGE_CEILING));
  const score =
    winProbability * SCORE_WEIGHT_WIN_PROBABILITY +
    averageProbability * SCORE_WEIGHT_AVG_PROBABILITY +
    clampedAverageEdge * SCORE_WEIGHT_AVG_EDGE;

  const grade = deriveGrade(legs.length, score);
  const volatility = deriveVolatility(legs.length, riskTier, averageEdge);
  const weakestLegEdge = legImpacts[weakestLegIndex]?.edge ?? 0;
  const recommendation = deriveRecommendation(legs.length, weakestLegEdge, riskTier);

  return {
    winProbability,
    lossProbability,
    estimatedOdds,
    riskTier,
    grade,
    volatility,
    averageProbability,
    averageEdge,
    weakestLegIndex,
    strongestLegIndex,
    legImpacts,
    recommendation,
  };
}

export function optimizeSlip(legs: ParlayLegInput[], mode: SlipOptimizerMode): ParlayLegInput[] {
  if (mode === "trap") {
    const metrics = calculateSlipMetrics(legs);
    return legs.filter((_, index) => index !== metrics.weakestLegIndex);
  }

  return [...legs].sort((a, b) => {
    if (mode === "safer") return clampProbability(b.probability) - clampProbability(a.probability);
    if (mode === "upside") return decimalOdds(b.odds_value) - decimalOdds(a.odds_value);
    return edgeForLeg(b) - edgeForLeg(a);
  });
}
