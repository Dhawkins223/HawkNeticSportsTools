// lib/model/edgeEngine.ts

import {
  americanToDecimal,
  decimalToAmerican,
  impliedProbFromAmerican,
  clamp,
  logit,
  sigmoid
} from './math'

export interface ModelInputs {
  injuryImpact: number
  fatigueImpact: number
  travelImpact: number
  paceFactor: number
  matchupEdge: number
  publicBias: number
}

export interface MarketEdgeResult {
  trueProb: number
  fairOdds: number
  marketProb: number
  marketOdds: number
  evPct: number
  safety: 'safe' | 'neutral' | 'risky'
}

export function evaluateMarketEdge(marketOdds: number, inputs: ModelInputs): MarketEdgeResult {
  const marketProb = impliedProbFromAmerican(marketOdds)
  const baseLogit = logit(clamp(marketProb, 0.001, 0.999))

  const injuryPenalty = -inputs.injuryImpact * 0.9
  const fatiguePenalty = -inputs.fatigueImpact * 0.7
  const travelPenalty = -inputs.travelImpact * 0.5
  const paceAdjustment = Math.log(clamp(inputs.paceFactor, 0.8, 1.25))
  const matchupBonus = inputs.matchupEdge
  const biasAdjustment = -inputs.publicBias * 0.35

  const adjustedLogit =
    baseLogit + injuryPenalty + fatiguePenalty + travelPenalty + paceAdjustment + matchupBonus + biasAdjustment

  const trueProb = clamp(sigmoid(adjustedLogit), 0.001, 0.999)
  const marketDecimal = americanToDecimal(marketOdds)
  const fairOdds = decimalToAmerican(1 / trueProb)
  const evPct = (trueProb * marketDecimal - 1) * 100

  let safety: 'safe' | 'neutral' | 'risky' = 'neutral'
  if (evPct >= 4 && trueProb >= 0.6) {
    safety = 'safe'
  } else if (evPct < 0) {
    safety = 'risky'
  }

  return {
    trueProb,
    fairOdds,
    marketProb,
    marketOdds,
    evPct,
    safety
  }
}
