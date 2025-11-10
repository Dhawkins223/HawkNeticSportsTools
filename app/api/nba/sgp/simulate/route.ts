import { NextRequest, NextResponse } from 'next/server'

import { prisma } from '@/lib/db'
import { buildTeamRatings } from '@/lib/model/ratings'
import { simulateSgp } from '@/lib/model/sgpSim'
import { kellyFraction, normalCdf, clamp, americanToDecimal } from '@/lib/model/math'

interface RequestLeg {
  gameId: number
  playerId: number
  market: string
  line: number
  direction: 'over' | 'under'
  odds: number
}

export async function POST(request: NextRequest) {
  let body: { legs: RequestLeg[]; offeredOdds: number }
  try {
    body = await request.json()
  } catch (error) {
    return NextResponse.json({ error: 'Invalid JSON payload' }, { status: 400 })
  }

  const { legs, offeredOdds } = body

  if (typeof offeredOdds !== 'number' || Number.isNaN(offeredOdds)) {
    return NextResponse.json({ error: 'offeredOdds must be a valid American odds number' }, { status: 400 })
  }

  if (!Array.isArray(legs) || legs.length === 0) {
    return NextResponse.json({ error: 'Legs are required for simulation' }, { status: 400 })
  }

  const gameContexts = new Map<number, {
    paceFactor: number
    ratings: Map<number, number>
  }>()

  const sgpLegs = []
  const legBreakdown: Array<{ id: string; baseHitProb: number }> = []

  for (const leg of legs) {
    if (!leg.gameId || !leg.playerId || !leg.market || !leg.direction) {
      return NextResponse.json({ error: 'Each leg must include gameId, playerId, market, and direction' }, { status: 400 })
    }

    let context = gameContexts.get(leg.gameId)
    if (!context) {
      const game = await prisma.game.findUnique({
        where: { id: leg.gameId },
        include: {
          homeTeam: true,
          awayTeam: true
        }
      })

      if (!game) {
        return NextResponse.json({ error: `Game ${leg.gameId} not found` }, { status: 404 })
      }

      const paceFactor = await computePaceFactor(game.homeTeamId, game.awayTeamId)
      const homeRatings = await buildTeamRatings(game.homeTeamId, game.awayTeamId, game.date)
      const awayRatings = await buildTeamRatings(game.awayTeamId, game.homeTeamId, game.date)
      const ratings = new Map<number, number>()
      for (const rating of [...homeRatings, ...awayRatings]) {
        ratings.set(rating.playerId, rating.matchupOverall)
      }

      context = { paceFactor, ratings }
      gameContexts.set(leg.gameId, context)
    }

    const baseline = await prisma.playerBaseline.findUnique({
      where: { playerId_market: { playerId: leg.playerId, market: leg.market } }
    })

    if (!baseline) {
      return NextResponse.json(
        { error: 'Upstream data unavailable. Configure env & sync.' },
        { status: 503 }
      )
    }

    const playerRating = context.ratings.get(leg.playerId) ?? 60
    const matchupAdjustment = (playerRating - 60) / 100
    const adjustedMean = baseline.mean * (1 + matchupAdjustment) * context.paceFactor
    const adjustedStdev = clamp(baseline.stdev * (1 + Math.abs(matchupAdjustment)), 0.5, 12)

    const zScore = (leg.line - adjustedMean) / adjustedStdev
    const pUnder = normalCdf(zScore)
    const pOver = 1 - pUnder
    const baseHitProb = leg.direction === 'over' ? pOver : pUnder

    const id = `${leg.playerId}-${leg.market}-${leg.direction}`
    sgpLegs.push({ id, baseHitProb, corrKey: `player-${leg.playerId}` })
    legBreakdown.push({ id, baseHitProb: Number(baseHitProb.toFixed(4)) })
  }

  const result = simulateSgp(sgpLegs, offeredOdds)
  const stakeFraction = Number(kellyFraction(result.jointProb, americanToDecimal(offeredOdds), 0.5).toFixed(4))

  return NextResponse.json({
    jointProb: result.jointProb,
    fairOdds: result.fairOdds,
    evPct: result.evPct,
    kellyFraction: stakeFraction,
    legs: legBreakdown
  })
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
