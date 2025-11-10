// lib/model/ratings.ts

import { prisma } from '@/lib/db'
import { clamp, normalizeProbs } from './math'

export interface PlayerRating {
  playerId: number
  playerName: string
  baseOverall: number
  matchupOverall: number
  offense: number
  defense: number
  playmaking: number
  usage: number
  fatigue: number
  volatility: number
}

function scaleToRating(value: number, min: number, max: number): number {
  if (max === min) {
    return 50
  }
  return clamp(40 + ((value - min) / (max - min)) * 50, 25, 99)
}

async function fetchRestDays(teamId: number, gameDate: Date): Promise<number> {
  const previousGame = await prisma.game.findFirst({
    where: {
      date: { lt: gameDate },
      OR: [{ homeTeamId: teamId }, { awayTeamId: teamId }]
    },
    orderBy: { date: 'desc' }
  })

  if (!previousGame) {
    return 3
  }

  const diff = Math.max(0, gameDate.getTime() - previousGame.date.getTime())
  return Math.round(diff / (1000 * 60 * 60 * 24))
}

async function fetchOpponentDefensiveIndex(teamId: number): Promise<number> {
  const stats = await prisma.playerGameStats.findMany({
    where: {
      game: {
        OR: [{ homeTeamId: teamId }, { awayTeamId: teamId }]
      }
    },
    take: 50
  })

  if (!stats.length) {
    return 1
  }

  const totals: Record<number, number> = {}
  for (const stat of stats) {
    totals[stat.gameId] = (totals[stat.gameId] ?? 0) + stat.points
  }
  const pointsPerGame = Object.values(totals).map((value) => value)
  const normalized = normalizeProbs(pointsPerGame)
  const weighted = normalized.reduce((acc, value, index) => acc + value * pointsPerGame[index], 0)
  return clamp(weighted / 220, 0.8, 1.2)
}

function injuryMultiplier(status: string | null | undefined): number {
  if (!status) return 1
  const normalized = status.toLowerCase()
  if (normalized === 'out' || normalized === 'doubtful') return 0.6
  if (normalized === 'questionable') return 0.8
  if (normalized === 'probable') return 0.95
  return 1
}

export async function buildTeamRatings(
  teamId: number,
  opponentId: number,
  gameDate: Date
): Promise<PlayerRating[]> {
  const players = await prisma.player.findMany({
    where: { teamId },
    include: {
      baselines: true,
      injuries: {
        orderBy: { updatedAt: 'desc' },
        take: 1
      }
    }
  })

  const restDays = await fetchRestDays(teamId, gameDate)
  const fatiguePenalty = restDays <= 1 ? 0.2 : restDays === 2 ? 0.1 : 0
  const opponentDefense = await fetchOpponentDefensiveIndex(opponentId)

  const ratings: PlayerRating[] = []

  for (const player of players) {
    if (!player.baselines.length) {
      continue
    }

    const meanPoints = player.baselines.find((b) => b.market === 'points')?.mean ?? 0
    const meanAssists = player.baselines.find((b) => b.market === 'assists')?.mean ?? 0
    const meanRebounds = player.baselines.find((b) => b.market === 'rebounds')?.mean ?? 0
    const meanPra = player.baselines.find((b) => b.market === 'pra')?.mean ?? meanPoints + meanRebounds + meanAssists
    const minutes = player.baselines.find((b) => b.market === 'points')?.minutes ?? 24
    const usageRate = player.baselines.find((b) => b.market === 'points')?.usageRate ?? 0.18
    const volatility = player.baselines.find((b) => b.market === 'points')?.stdev ?? 1.5

    const offense = scaleToRating(meanPoints, 5, 35)
    const playmaking = scaleToRating(meanAssists, 1, 12)
    const rebounding = scaleToRating(meanRebounds, 2, 16)
    const defense = clamp(100 - rebounding * 0.6, 40, 95)

    const baselineOverall = clamp(
      (offense * 0.45 + defense * 0.2 + playmaking * 0.2 + rebounding * 0.15) / 1,
      30,
      99
    )

    const injuryStatus = player.injuries[0]?.status ?? null
    const injuryFactor = injuryMultiplier(injuryStatus)
    const paceAdjustment = clamp(1 / opponentDefense, 0.85, 1.15)

    const matchupOverall = clamp(
      baselineOverall * injuryFactor * (1 - fatiguePenalty) * paceAdjustment,
      20,
      99
    )

    ratings.push({
      playerId: player.id,
      playerName: player.name,
      baseOverall: Number(baselineOverall.toFixed(1)),
      matchupOverall: Number(matchupOverall.toFixed(1)),
      offense: Number(offense.toFixed(1)),
      defense: Number(defense.toFixed(1)),
      playmaking: Number(playmaking.toFixed(1)),
      usage: Number(Math.min(1, usageRate).toFixed(3)),
      fatigue: Number((1 - Math.min(1, restDays / 4)).toFixed(3)),
      volatility: Number(clamp(volatility / Math.max(1, minutes), 0.1, 0.8).toFixed(3))
    })
  }

  return ratings.sort((a, b) => b.matchupOverall - a.matchupOverall)
}
