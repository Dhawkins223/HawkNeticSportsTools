// lib/model/simulation.ts

import { randn, americanToProb, probToAmerican, evPercent } from './math'
import { SimulationLeg, SimulationResult, ContextAdjustments } from './types'
import { projectPlayerStat } from './projection'

function legCorrelation(a: SimulationLeg, b: SimulationLeg): number {
  if (a.playerId === b.playerId) {
    if (a.stat === b.stat) return 0.8
    return 0.4
  }
  if (a.teamAbbr === b.teamAbbr) return 0.2
  return 0.05
}

function buildCorrelationMatrix(legs: SimulationLeg[]): number[][] {
  const n = legs.length
  const matrix = Array.from({ length: n }, () => Array(n).fill(0))

  for (let i = 0; i < n; i++) {
    matrix[i][i] = 1
    for (let j = i + 1; j < n; j++) {
      const corr = legCorrelation(legs[i], legs[j])
      matrix[i][j] = corr
      matrix[j][i] = corr
    }
  }

  return matrix
}

function cholesky(matrix: number[][]): number[][] {
  const n = matrix.length
  const lower: number[][] = Array.from({ length: n }, () => Array(n).fill(0))

  for (let i = 0; i < n; i++) {
    for (let j = 0; j <= i; j++) {
      let sum = 0
      for (let k = 0; k < j; k++) {
        sum += lower[i][k] * lower[j][k]
      }

      if (i === j) {
        lower[i][j] = Math.sqrt(Math.max(matrix[i][i] - sum, 1e-8))
      } else {
        lower[i][j] = (matrix[i][j] - sum) / lower[j][j]
      }
    }
  }

  return lower
}

export async function runParlaySimulation(
  gameId: number,
  legs: SimulationLeg[],
  bookmakerOdds: number,
  ctx: ContextAdjustments,
  iterations = 20000
): Promise<SimulationResult> {
  const correlation = buildCorrelationMatrix(legs)
  const decomposition = cholesky(correlation)

  const configs = []
  for (const leg of legs) {
    const projection =
      (await projectPlayerStat(
        leg.playerId,
        leg.playerName,
        leg.teamAbbr,
        leg.stat,
        ctx
      )) ?? {
        mean: leg.line,
        stdev: Math.max(2, Math.abs(leg.line) * 0.25),
      }

    configs.push({ leg, projection })
  }

  let hits = 0
  const n = legs.length

  for (let iter = 0; iter < iterations; iter++) {
    const z = Array.from({ length: n }, () => randn())
    const y = new Array(n).fill(0)

    for (let i = 0; i < n; i++) {
      let sum = 0
      for (let j = 0; j <= i; j++) {
        sum += decomposition[i][j] * z[j]
      }
      y[i] = sum
    }

    let allHit = true
    for (let i = 0; i < n; i++) {
      const { leg, projection } = configs[i]
      const simulatedValue = projection.mean + projection.stdev * y[i]
      const hit =
        leg.direction === 'over'
          ? simulatedValue >= leg.line
          : simulatedValue <= leg.line
      if (!hit) {
        allHit = false
        break
      }
    }

    if (allHit) {
      hits++
    }
  }

  const p_joint = hits / iterations
  const implied_prob = americanToProb(bookmakerOdds)
  const fair_odds = probToAmerican(p_joint)
  const ev = evPercent(p_joint, bookmakerOdds)

  return {
    legs,
    p_joint,
    implied_prob,
    fair_odds,
    ev,
    bookmaker_odds: bookmakerOdds,
    model_inputs: ctx,
  }
}
