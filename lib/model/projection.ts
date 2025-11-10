// lib/model/projection.ts

import { prisma } from '../db'
import { ContextAdjustments, PlayerProjection, StatType } from './types'

type StatSelectorKey = 'points' | 'assists' | 'rebounds' | 'threes' | 'pra'

const MARKET_STAT_MAP: Record<StatType, StatSelectorKey> = {
  points: 'points',
  assists: 'assists',
  rebounds: 'rebounds',
  threes: 'threes',
  pra: 'pra',
}

const statSelector: Record<StatSelectorKey, (row: any) => number> = {
  points: (row: any) => row.points,
  assists: (row: any) => row.assists,
  rebounds: (row: any) => row.rebounds,
  threes: (row: any) => row.threes,
  pra: (row: any) => row.points + row.rebounds + row.assists,
}

export async function getPlayerBaseline(playerId: number, market: StatType) {
  return prisma.playerBaseline.findFirst({
    where: { playerId, market },
  })
}

export function adjustProjectionFromBaseline(
  mean: number,
  stdev: number,
  teamAbbr: string,
  playerName: string,
  ctx: ContextAdjustments
): PlayerProjection {
  let adjustedMean = mean
  let adjustedStdev = stdev

  adjustedMean *= ctx.paceFactor

  const teamInjury = ctx.injuryImpactTeam[teamAbbr] ?? 0
  adjustedMean *= 1 + teamInjury

  const matchupMultiplier = ctx.matchupDifficulty[playerName] ?? 1
  adjustedMean *= matchupMultiplier

  const restDays = ctx.restDays[teamAbbr]
  if (typeof restDays === 'number' && restDays <= 1) {
    adjustedMean *= 0.97
  }

  const travelAdjustment = ctx.travelPenalty[teamAbbr] ?? 0
  adjustedMean *= 1 + travelAdjustment

  adjustedMean *= 1 - ctx.blowoutRisk * 0.25
  adjustedStdev *= 1 + 0.15 * ctx.blowoutRisk

  return {
    mean: adjustedMean,
    stdev: Math.max(0.5, adjustedStdev),
  }
}

export async function projectPlayerStat(
  playerId: number,
  playerName: string,
  teamAbbr: string,
  market: StatType,
  ctx: ContextAdjustments
): Promise<PlayerProjection | null> {
  let baseline = await getPlayerBaseline(playerId, market)
  if (!baseline) {
    baseline = await computeBaselineFromHistory(playerId, market)
  }

  if (!baseline) {
    return null
  }

  return adjustProjectionFromBaseline(
    baseline.mean,
    baseline.stdev,
    teamAbbr,
    playerName,
    ctx
  )
}

async function computeBaselineFromHistory(playerId: number, market: StatType) {
  const recentStats = await prisma.playerGameStats.findMany({
    where: { playerId },
    orderBy: { createdAt: 'desc' },
    take: 20,
  })

  if (!recentStats.length) {
    return null
  }

  const extractor = statSelector[MARKET_STAT_MAP[market]]
  const samples = recentStats.map((row) => extractor(row))
  const minutes = recentStats.map((row) => row.minutes)

  const mean = average(samples)
  const stdev = standardDeviation(samples, mean)
  const avgMinutes = average(minutes)

  const usageRate = avgMinutes ? mean / avgMinutes : 0

  return prisma.playerBaseline.upsert({
    where: { playerId_market: { playerId, market } },
    update: {
      mean,
      stdev,
      minutes: avgMinutes,
      usageRate,
      updatedAt: new Date(),
    },
    create: {
      playerId,
      market,
      mean,
      stdev,
      minutes: avgMinutes,
      usageRate,
    },
  })
}

function average(values: number[]): number {
  if (!values.length) return 0
  return values.reduce((acc, val) => acc + val, 0) / values.length
}

function standardDeviation(values: number[], mean: number): number {
  if (values.length <= 1) return 0
  const variance =
    values.reduce((acc, val) => acc + Math.pow(val - mean, 2), 0) /
    (values.length - 1)
  return Math.sqrt(Math.max(variance, 0.01))
}
