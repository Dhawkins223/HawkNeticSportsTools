// lib/model/sgpSim.ts

import { americanToDecimal, decimalToAmerican, inverseNormal, normalizeProbs } from './math'

export interface SgpLeg {
  id: string
  baseHitProb: number
  corrKey: string
}

export interface SgpResult {
  jointProb: number
  fairOdds: number
  evPct: number
}

export function simulateSgp(legs: SgpLeg[], offeredOdds: number, iterations = 25000): SgpResult {
  if (!legs.length) {
    throw new Error('At least one leg is required to simulate an SGP')
  }

  const grouped = legs.reduce<Record<string, SgpLeg[]>>((acc, leg) => {
    acc[leg.corrKey] = acc[leg.corrKey] ?? []
    acc[leg.corrKey].push(leg)
    return acc
  }, {})

  const groupWeights = normalizeProbs(Object.values(grouped).map((group) => group.length))
  const groupKeys = Object.keys(grouped)

  const thresholds = legs.map((leg) => inverseNormal(leg.baseHitProb))

  let hits = 0

  for (let i = 0; i < iterations; i++) {
    const groupShocks: Record<string, number> = {}
    groupKeys.forEach((key, index) => {
      const weight = groupWeights[index] ?? 0.2
      groupShocks[key] = gaussian() * (0.5 + weight)
    })

    let allHit = true

    for (let j = 0; j < legs.length; j++) {
      const leg = legs[j]
      const threshold = thresholds[j]
      const sharedShock = groupShocks[leg.corrKey] ?? gaussian() * 0.3
      const idShock = gaussian() * 0.7
      const combined = 0.55 * sharedShock + idShock
      if (combined > threshold) {
        allHit = false
        break
      }
    }

    if (allHit) {
      hits += 1
    }
  }

  const jointProb = Math.max(hits / iterations, 1e-6)
  const decimalOdds = americanToDecimal(offeredOdds)
  const fairOdds = decimalToAmerican(1 / jointProb)
  const evPct = (jointProb * decimalOdds - 1) * 100

  return {
    jointProb,
    fairOdds,
    evPct
  }
}

function gaussian(): number {
  let u = 0
  let v = 0
  while (u === 0) u = Math.random()
  while (v === 0) v = Math.random()
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v)
}
