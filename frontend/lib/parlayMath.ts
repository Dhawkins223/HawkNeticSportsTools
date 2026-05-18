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

export function clampProbability(value?: number) {
  return Math.max(0.01, Math.min(value ?? 0.5, 0.99));
}

export function impliedProbabilityFromOdds(odds?: number) {
  if (!odds) return 0.5;
  return odds > 0 ? 100 / (odds + 100) : Math.abs(odds) / (Math.abs(odds) + 100);
}

function edgeForLeg(leg: ParlayLegInput) {
  return clampProbability(leg.probability) - impliedProbabilityFromOdds(leg.odds_value);
}

function decimalOdds(odds?: number) {
  if (!odds) return 2;
  return odds > 0 ? 1 + odds / 100 : 1 + 100 / Math.abs(odds);
}

function product(values: number[]) {
  return values.reduce((current, value) => current * value, 1);
}

export function calculateSlipMetrics(legs: ParlayLegInput[]): SlipMetrics {
  const probabilities = legs.map((leg) => clampProbability(leg.probability));
  const winProbability = legs.length ? product(probabilities) : 0;
  const lossProbability = legs.length ? 1 - winProbability : 0;
  const estimatedOdds = winProbability > 0 ? Math.round((1 / winProbability - 1) * 100) : undefined;
  const riskTier = !legs.length ? "ungraded" : legs.length >= 4 || winProbability < 0.2 ? "high" : legs.length >= 2 ? "medium" : "low";
  const legImpacts = legs.map((leg, index) => {
    const edge = edgeForLeg(leg);
    const otherProbability = product(probabilities.filter((_, probabilityIndex) => probabilityIndex !== index));
    const drag = otherProbability - winProbability;
    return {
      edge,
      drag,
      label: edge >= 0.08 ? "Sharp edge" : edge >= 0.02 ? "Positive lean" : edge > -0.03 ? "Fair price" : "Trap risk",
    };
  });
  const averageProbability = probabilities.length ? probabilities.reduce((sum, value) => sum + value, 0) / probabilities.length : 0;
  const averageEdge = legImpacts.length ? legImpacts.reduce((sum, impact) => sum + impact.edge, 0) / legImpacts.length : 0;
  const weakestLegIndex = legImpacts.reduce((weakest, impact, index) => impact.edge < (legImpacts[weakest]?.edge ?? Infinity) ? index : weakest, 0);
  const strongestLegIndex = legImpacts.reduce((strongest, impact, index) => impact.edge > (legImpacts[strongest]?.edge ?? -Infinity) ? index : strongest, 0);
  const score = winProbability * 60 + averageProbability * 25 + Math.max(-0.15, Math.min(averageEdge, 0.25)) * 100;
  const grade = !legs.length ? "--" : score >= 58 ? "A" : score >= 48 ? "B+" : score >= 38 ? "B" : score >= 28 ? "C+" : "D";
  const volatility = !legs.length ? "No ticket" : riskTier === "high" ? "Volatile" : averageEdge >= 0.05 ? "Controlled upside" : "Balanced";
  const recommendation = !legs.length
    ? "Add legs to unlock Smart Slip Lab."
    : legImpacts[weakestLegIndex]?.edge < -0.03
      ? "Optimizer sees one leg priced worse than the model."
      : riskTier === "high"
        ? "High variance slip: consider reducing leg count."
        : "Model profile is playable for analysis.";

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

export function optimizeSlip(legs: ParlayLegInput[], mode: SlipOptimizerMode) {
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
