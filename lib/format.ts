export function americanToImpliedProbability(odds: number): number {
  if (odds === 0) return 0;
  if (odds > 0) {
    return 100 / (odds + 100);
  }
  return -odds / (-odds + 100);
}

export function impliedProbabilityToAmerican(prob: number): number {
  if (prob <= 0 || prob >= 1) {
    throw new Error("Probability must be between 0 and 1");
  }
  return prob > 0.5 ? Math.round((-prob / (1 - prob)) * 100) : Math.round(((1 - prob) / prob) * 100);
}

export function expectedValue({
  odds,
  probability,
  stake
}: {
  odds: number;
  probability: number;
  stake: number;
}): number {
  const decimalOdds = odds > 0 ? odds / 100 + 1 : 100 / -odds + 1;
  const payout = decimalOdds * stake;
  const loss = stake;
  return probability * (payout - stake) - (1 - probability) * loss;
}

export function formatPercent(value: number, fractionDigits = 1): string {
  return `${(value * 100).toFixed(fractionDigits)}%`;
}

export function formatOdds(odds: number): string {
  return odds > 0 ? `+${odds}` : `${odds}`;
}

export function classForEv(ev: number): string {
  return ev >= 0 ? "badge-ev bg-emerald-500/20 text-emerald-300" : "badge-ev bg-red-500/20 text-red-400";
}
