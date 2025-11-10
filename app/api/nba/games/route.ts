import { NextRequest, NextResponse } from 'next/server'

import { prisma } from '@/lib/db'
import { evaluateMarketEdge, type MarketEdgeResult } from '@/lib/model/edgeEngine'
import { buildTeamRatings } from '@/lib/model/ratings'
import type { PlayerRating } from '@/lib/model/ratings'

interface GameMarketSummary {
  type: 'moneyline' | 'spread' | 'total'
  label: string
  line: number | null
  odds: number
  edge: MarketEdgeResult
}

interface TeamSummary {
  id: number
  name: string
  abbr: string
  ratings: PlayerRating[]
}

interface GameSummary {
  id: number
  externalId: string
  startTime: string
  venue: string | null
  status: string
  home: TeamSummary
  away: TeamSummary
  markets: GameMarketSummary[]
  latestOdds: {
    spreadHome: number | null
    spreadAway: number | null
    total: number | null
    mlHome: number | null
    mlAway: number | null
  }
}

export async function GET(_request: NextRequest) {
  const now = new Date()
  const startOfDay = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  const endOfDay = new Date(startOfDay)
  endOfDay.setDate(endOfDay.getDate() + 1)

  const games = await prisma.game.findMany({
    where: {
      date: {
        gte: startOfDay,
        lt: endOfDay
      }
    },
    include: {
      homeTeam: true,
      awayTeam: true,
      odds: {
        orderBy: { createdAt: 'desc' },
        take: 1
      }
    },
    orderBy: { date: 'asc' }
  })

  if (!games.length) {
    return NextResponse.json(
      { error: 'Upstream data unavailable. Configure env & sync.' },
      { status: 503 }
    )
  }

  const summaries: GameSummary[] = []

  for (const game of games) {
    const latestOdds = game.odds[0]
    if (!latestOdds) {
      return NextResponse.json(
        { error: 'Upstream data unavailable. Configure env & sync.' },
        { status: 503 }
      )
    }

    const homeRatings = await buildTeamRatings(game.homeTeamId, game.awayTeamId, game.date)
    const awayRatings = await buildTeamRatings(game.awayTeamId, game.homeTeamId, game.date)

    const injuries = await prisma.injury.findMany({
      where: { teamId: { in: [game.homeTeamId, game.awayTeamId] } }
    })

    const injuryImpact = injuries.filter((injury) => injury.status !== 'active').length * 0.02
    const fatigueImpact = await computeFatigueImpact(game)
    const travelImpact = await computeTravelImpact(game)
    const paceFactor = await computePaceFactor(game.homeTeamId, game.awayTeamId)
    const publicBias = computePublicBias(latestOdds)
    const matchupEdgeHome = computeMatchupEdge(homeRatings, awayRatings)
    const matchupEdgeAway = -matchupEdgeHome

    const markets: GameMarketSummary[] = []

    if (latestOdds.mlHome !== null) {
      markets.push({
        type: 'moneyline',
        label: `${game.homeTeam.abbr} ML`,
        line: null,
        odds: latestOdds.mlHome,
        edge: evaluateMarketEdge(latestOdds.mlHome, {
          injuryImpact,
          fatigueImpact,
          travelImpact,
          paceFactor,
          matchupEdge: matchupEdgeHome,
          publicBias
        })
      })
    }

    if (latestOdds.mlAway !== null) {
      markets.push({
        type: 'moneyline',
        label: `${game.awayTeam.abbr} ML`,
        line: null,
        odds: latestOdds.mlAway,
        edge: evaluateMarketEdge(latestOdds.mlAway, {
          injuryImpact,
          fatigueImpact,
          travelImpact,
          paceFactor,
          matchupEdge: matchupEdgeAway,
          publicBias: -publicBias
        })
      })
    }

    if (latestOdds.spreadHome !== null && latestOdds.spreadHomeOdds !== null) {
      markets.push({
        type: 'spread',
        label: `${game.homeTeam.abbr} ${latestOdds.spreadHome}`,
        line: latestOdds.spreadHome,
        odds: latestOdds.spreadHomeOdds,
        edge: evaluateMarketEdge(latestOdds.spreadHomeOdds, {
          injuryImpact,
          fatigueImpact,
          travelImpact,
          paceFactor,
          matchupEdge: matchupEdgeHome - latestOdds.spreadHome * 0.01,
          publicBias
        })
      })
    }

    if (latestOdds.spreadAway !== null && latestOdds.spreadAwayOdds !== null) {
      markets.push({
        type: 'spread',
        label: `${game.awayTeam.abbr} ${latestOdds.spreadAway}`,
        line: latestOdds.spreadAway,
        odds: latestOdds.spreadAwayOdds,
        edge: evaluateMarketEdge(latestOdds.spreadAwayOdds, {
          injuryImpact,
          fatigueImpact,
          travelImpact,
          paceFactor,
          matchupEdge: matchupEdgeAway - latestOdds.spreadAway * 0.01,
          publicBias: -publicBias
        })
      })
    }

    if (latestOdds.total !== null && latestOdds.overOdds !== null) {
      markets.push({
        type: 'total',
        label: `Over ${latestOdds.total}`,
        line: latestOdds.total,
        odds: latestOdds.overOdds,
        edge: evaluateMarketEdge(latestOdds.overOdds, {
          injuryImpact: injuryImpact * 0.5,
          fatigueImpact,
          travelImpact,
          paceFactor: paceFactor * 1.05,
          matchupEdge: matchupEdgeHome,
          publicBias
        })
      })
    }

    if (latestOdds.total !== null && latestOdds.underOdds !== null) {
      markets.push({
        type: 'total',
        label: `Under ${latestOdds.total}`,
        line: latestOdds.total,
        odds: latestOdds.underOdds,
        edge: evaluateMarketEdge(latestOdds.underOdds, {
          injuryImpact: injuryImpact * 0.5,
          fatigueImpact,
          travelImpact,
          paceFactor: paceFactor * 0.95,
          matchupEdge: matchupEdgeAway,
          publicBias: -publicBias
        })
      })
    }

    summaries.push({
      id: game.id,
      externalId: game.externalId,
      startTime: game.date.toISOString(),
      venue: game.venue,
      status: game.status,
      home: {
        id: game.homeTeam.id,
        name: game.homeTeam.name,
        abbr: game.homeTeam.abbr,
        ratings: homeRatings
      },
      away: {
        id: game.awayTeam.id,
        name: game.awayTeam.name,
        abbr: game.awayTeam.abbr,
        ratings: awayRatings
      },
      markets,
      latestOdds: {
        spreadHome: latestOdds.spreadHome,
        spreadAway: latestOdds.spreadAway,
        total: latestOdds.total,
        mlHome: latestOdds.mlHome,
        mlAway: latestOdds.mlAway
      }
    })
  }

  return NextResponse.json(summaries)
}

async function computeFatigueImpact(game: { homeTeamId: number; awayTeamId: number; date: Date }): Promise<number> {
  const penalties = await Promise.all([
    fatigueForTeam(game.homeTeamId, game.date),
    fatigueForTeam(game.awayTeamId, game.date)
  ])
  return penalties.reduce((acc, value) => acc + value, 0) / penalties.length
}

async function fatigueForTeam(teamId: number, date: Date): Promise<number> {
  const lastGame = await prisma.game.findFirst({
    where: {
      date: { lt: date },
      OR: [{ homeTeamId: teamId }, { awayTeamId: teamId }]
    },
    orderBy: { date: 'desc' }
  })

  if (!lastGame) {
    return 0.05
  }

  const diff = (date.getTime() - lastGame.date.getTime()) / (1000 * 60 * 60 * 24)
  if (diff <= 1) return 0.25
  if (diff <= 2) return 0.15
  if (diff <= 3) return 0.08
  return 0.03
}

async function computeTravelImpact(game: { homeTeamId: number; awayTeamId: number; date: Date }): Promise<number> {
  const awayLastGame = await prisma.game.findFirst({
    where: {
      date: { lt: game.date },
      OR: [{ homeTeamId: game.awayTeamId }, { awayTeamId: game.awayTeamId }]
    },
    orderBy: { date: 'desc' }
  })

  if (!awayLastGame) {
    return 0.05
  }

  const turnaround = (game.date.getTime() - awayLastGame.date.getTime()) / (1000 * 60 * 60 * 24)
  return turnaround <= 1 ? 0.2 : turnaround <= 2 ? 0.1 : 0.05
}

async function computePaceFactor(homeTeamId: number, awayTeamId: number): Promise<number> {
  const homeBaselines = await prisma.playerBaseline.findMany({
    where: { player: { teamId: homeTeamId }, market: 'points' }
  })
  const awayBaselines = await prisma.playerBaseline.findMany({
    where: { player: { teamId: awayTeamId }, market: 'points' }
  })

  const totalMean =
    homeBaselines.reduce((acc, baseline) => acc + baseline.mean, 0) +
    awayBaselines.reduce((acc, baseline) => acc + baseline.mean, 0)

  return Math.min(1.3, Math.max(0.8, totalMean / 220))
}

function computePublicBias(odds: {
  spreadHome: number | null
  spreadAway: number | null
  mlHome: number | null
  mlAway: number | null
}): number {
  const spread = Math.abs(odds.spreadHome ?? odds.spreadAway ?? 0)
  const moneylineDiff = Math.abs((odds.mlHome ?? 0) - (odds.mlAway ?? 0))
  return Math.min(0.15, spread / 12 + moneylineDiff / 8000)
}

function computeMatchupEdge(home: PlayerRating[], away: PlayerRating[]): number {
  const avgHome = average(home.map((rating) => rating.matchupOverall))
  const avgAway = average(away.map((rating) => rating.matchupOverall))
  return (avgHome - avgAway) / 100
}

function average(values: number[]): number {
  if (!values.length) return 0
  return values.reduce((acc, value) => acc + value, 0) / values.length
}
