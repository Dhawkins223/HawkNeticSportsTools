// lib/model/context.ts

import { prisma } from '../db'
import { ContextAdjustments } from './types'

const LEAGUE_AVG_PACE = 99

export async function buildContextForGame(gameId: number): Promise<ContextAdjustments> {
  const game = await prisma.game.findUnique({
    where: { id: gameId },
    include: {
      homeTeam: true,
      awayTeam: true,
      odds: {
        orderBy: { createdAt: 'desc' },
        take: 1,
      },
    },
  })

  if (!game) {
    throw new Error('Game not found')
  }

  const paceFactor = await computePaceFactor(game.id, game.homeTeamId, game.awayTeamId)
  const blowoutRisk = computeBlowoutRisk(game.odds[0]?.spreadHome ?? 0)
  const injuryImpactTeam = await computeInjuryImpact(game.homeTeamId, game.awayTeamId)

  return {
    paceFactor,
    blowoutRisk,
    injuryImpactTeam,
    matchupDifficulty: {},
    restDays: await computeRestDays([game.homeTeamId, game.awayTeamId], game.date),
    travelPenalty: await computeTravelPenalty([game.homeTeamId, game.awayTeamId]),
  }
}

async function computePaceFactor(gameId: number, homeTeamId: number, awayTeamId: number): Promise<number> {
  const recentGames = await prisma.game.findMany({
    where: {
      id: { not: gameId },
      OR: [{ homeTeamId }, { awayTeamId }],
    },
    orderBy: { date: 'desc' },
    take: 5,
    include: {
      stats: true,
    },
  })

  const possessions: number[] = []
  for (const g of recentGames) {
    if (!g.stats.length) continue
    const teamMinutes = g.stats.reduce((acc, s) => acc + s.minutes, 0)
    if (teamMinutes === 0) continue
    const pace = (g.stats.reduce((acc, s) => acc + s.points, 0) / teamMinutes) * 240
    possessions.push(pace)
  }

  const avgPace = possessions.length
    ? possessions.reduce((a, b) => a + b, 0) / possessions.length
    : LEAGUE_AVG_PACE

  return Math.max(0.8, Math.min(1.2, avgPace / LEAGUE_AVG_PACE))
}

function computeBlowoutRisk(spreadHome: number): number {
  const spread = Math.abs(spreadHome)
  return Math.min(0.35, Math.max(0.05, spread / 20))
}

async function computeInjuryImpact(homeTeamId: number, awayTeamId: number): Promise<Record<string, number>> {
  const injuries = await prisma.injury.findMany({
    where: {
      teamId: { in: [homeTeamId, awayTeamId] },
      status: { in: ['out', 'doubtful'] },
    },
    include: {
      team: true,
    },
  })

  const impact: Record<string, number> = {}
  for (const injury of injuries) {
    const abbr = injury.team.abbr
    impact[abbr] = (impact[abbr] ?? 0) + 0.03
  }

  return impact
}

async function computeRestDays(teamIds: number[], referenceDate: Date): Promise<Record<string, number>> {
  const rest: Record<string, number> = {}
  for (const teamId of teamIds) {
    const lastGame = await prisma.game.findFirst({
      where: {
        OR: [{ homeTeamId: teamId }, { awayTeamId: teamId }],
        date: { lt: referenceDate },
      },
      orderBy: { date: 'desc' },
    })

    if (!lastGame) continue

    const days = (referenceDate.getTime() - lastGame.date.getTime()) / (1000 * 60 * 60 * 24)
    const team = await prisma.team.findUnique({ where: { id: teamId } })
    if (!team) continue
    rest[team.abbr] = Math.max(0, Math.round(days))
  }
  return rest
}

async function computeTravelPenalty(teamIds: number[]): Promise<Record<string, number>> {
  const penalties: Record<string, number> = {}
  for (const teamId of teamIds) {
    const team = await prisma.team.findUnique({ where: { id: teamId } })
    if (!team) continue
    penalties[team.abbr] = 0
  }
  return penalties
}
