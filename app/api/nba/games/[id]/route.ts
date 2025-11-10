import { NextRequest, NextResponse } from 'next/server'

import { prisma } from '@/lib/db'
import { buildTeamRatings } from '@/lib/model/ratings'
import type { PlayerRating } from '@/lib/model/ratings'
import { evaluateMarketEdge, type MarketEdgeResult } from '@/lib/model/edgeEngine'
import {
  americanToDecimal,
  decimalToAmerican,
  impliedProbFromAmerican,
  normalCdf,
  clamp
} from '@/lib/model/math'

interface PropEdge {
  id: number
  market: string
  line: number
  overOdds: number
  underOdds: number
  player: {
    id: number
    name: string
    team: string
  }
  projection: {
    mean: number
    stdev: number
  }
  over: MarketEdgeResult
  under: MarketEdgeResult
}

export async function GET(_request: NextRequest, { params }: { params: { id: string } }) {
  const id = Number(params.id)
  if (Number.isNaN(id)) {
    return NextResponse.json({ error: 'Invalid game id' }, { status: 400 })
  }

  const game = await prisma.game.findUnique({
    where: { id },
    include: {
      homeTeam: true,
      awayTeam: true,
      odds: {
        orderBy: { createdAt: 'desc' }
      },
      props: {
        include: {
          player: {
            include: {
              team: true,
              baselines: true,
              injuries: {
                orderBy: { updatedAt: 'desc' },
                take: 1
              }
            }
          }
        }
      }
    }
  })

  if (!game) {
    return NextResponse.json({ error: 'Game not found' }, { status: 404 })
  }

  if (!game.odds.length) {
    return NextResponse.json(
      { error: 'Upstream data unavailable. Configure env & sync.' },
      { status: 503 }
    )
  }

  const latestOdds = game.odds[0]
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

  const markets = buildMarketSummaries({
    game,
    latestOdds,
    injuryImpact,
    fatigueImpact,
    travelImpact,
    paceFactor,
    publicBias,
    matchupEdgeHome,
    matchupEdgeAway
  })

  const props: PropEdge[] = []

  for (const prop of game.props) {
    if (prop.overOdds === null || prop.underOdds === null) continue

    const baseline = prop.player.baselines.find((b) => b.market === prop.market)
    if (!baseline) continue

    const rating = [...homeRatings, ...awayRatings].find((item) => item.playerId === prop.playerId)
    const matchupAdjustment = rating ? (rating.matchupOverall - rating.baseOverall) / 100 : 0
    const injuryStatus = prop.player.injuries[0]?.status ?? 'active'
    const injuryPenalty = injuryStatus !== 'active' ? 0.1 : 0

    const adjustedMean = baseline.mean * (1 + matchupAdjustment) * paceFactor * (1 - injuryPenalty)
    const adjustedStdev = clamp(baseline.stdev * (1 + Math.abs(matchupAdjustment)), 0.5, 12)

    const zScore = (prop.line - adjustedMean) / adjustedStdev
    const pUnder = normalCdf(zScore)
    const pOver = 1 - pUnder

    const overEdge = buildEdgeFromProbability(pOver, prop.overOdds)
    const underEdge = buildEdgeFromProbability(pUnder, prop.underOdds)

    props.push({
      id: prop.id,
      market: prop.market,
      line: prop.line,
      overOdds: prop.overOdds,
      underOdds: prop.underOdds,
      player: {
        id: prop.player.id,
        name: prop.player.name,
        team: prop.player.team.abbr
      },
      projection: {
        mean: Number(adjustedMean.toFixed(2)),
        stdev: Number(adjustedStdev.toFixed(2))
      },
      over: overEdge,
      under: underEdge
    })
  }

  const response = {
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
    oddsHistory: game.odds.map((odds) => ({
      id: odds.id,
      createdAt: odds.createdAt.toISOString(),
      spreadHome: odds.spreadHome,
      spreadAway: odds.spreadAway,
      total: odds.total,
      mlHome: odds.mlHome,
      mlAway: odds.mlAway
    })),
    props: props.sort((a, b) => b.over.evPct - a.over.evPct)
  }

  return NextResponse.json(response)
}

function buildEdgeFromProbability(trueProb: number, marketOdds: number): MarketEdgeResult {
  const marketProb = impliedProbFromAmerican(marketOdds)
  const fairOdds = decimalToAmerican(1 / trueProb)
  const decimalOdds = americanToDecimal(marketOdds)
  const evPct = (trueProb * decimalOdds - 1) * 100
  let safety: 'safe' | 'neutral' | 'risky' = 'neutral'
  if (evPct >= 4 && trueProb >= 0.6) safety = 'safe'
  if (evPct < 0) safety = 'risky'
  return {
    trueProb,
    fairOdds,
    marketProb,
    marketOdds,
    evPct,
    safety
  }
}

function buildMarketSummaries({
  game,
  latestOdds,
  injuryImpact,
  fatigueImpact,
  travelImpact,
  paceFactor,
  publicBias,
  matchupEdgeHome,
  matchupEdgeAway
}: {
  game: Awaited<ReturnType<typeof prisma.game.findUnique>>
  latestOdds: NonNullable<Awaited<ReturnType<typeof prisma.game.findUnique>>['odds'][0]>
  injuryImpact: number
  fatigueImpact: number
  travelImpact: number
  paceFactor: number
  publicBias: number
  matchupEdgeHome: number
  matchupEdgeAway: number
}): Array<{
  type: 'moneyline' | 'spread' | 'total'
  label: string
  line: number | null
  odds: number
  edge: MarketEdgeResult
}> {
  const markets: Array<{
    type: 'moneyline' | 'spread' | 'total'
    label: string
    line: number | null
    odds: number
    edge: MarketEdgeResult
  }> = []

  if (latestOdds.mlHome !== null) {
    markets.push({
      type: 'moneyline',
      label: `${game!.homeTeam.abbr} ML`,
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
      label: `${game!.awayTeam.abbr} ML`,
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
      label: `${game!.homeTeam.abbr} ${latestOdds.spreadHome}`,
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
      label: `${game!.awayTeam.abbr} ${latestOdds.spreadAway}`,
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

  return markets
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
