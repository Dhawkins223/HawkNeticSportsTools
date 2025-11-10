// app/api/props/route.ts

import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'
import { buildContextForGame } from '@/lib/model/context'
import { projectPlayerStat } from '@/lib/model/projection'
import { americanToProb, evPercent, normalCdf } from '@/lib/model/math'
import { StatType } from '@/lib/model/types'

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const gameIdParam = searchParams.get('game_id')
  const statTypeParam = searchParams.get('stat_type') as StatType | null
  const minEvParam = searchParams.get('min_ev')

  if (!gameIdParam) {
    return NextResponse.json({ error: 'game_id is required' }, { status: 400 })
  }

  const gameId = Number(gameIdParam)
  const minEv = minEvParam ? Number(minEvParam) : 0

  if (Number.isNaN(gameId)) {
    return NextResponse.json({ error: 'game_id must be numeric' }, { status: 400 })
  }

  const ctx = await buildContextForGame(gameId)

  const props = await prisma.propOdds.findMany({
    where: { gameId },
    include: {
      player: {
        include: { team: true },
      },
    },
  })

  const response = [] as Array<{
    id: number
    game_id: number
    player_name: string
    team: string
    stat_type: StatType
    line: number
    over_odds: number
    under_odds: number
    projection: number
    ev: number
    implied_prob: number
  }>

  for (const prop of props) {
    const market = prop.market as StatType
    if (statTypeParam && market !== statTypeParam) continue

    const projection = await projectPlayerStat(
      prop.playerId,
      prop.player.name,
      prop.player.team.abbr,
      market,
      ctx
    )

    if (!projection) continue

    const stdev = projection.stdev || 1
    const zScore = (prop.line - projection.mean) / stdev
    const pUnder = normalCdf(zScore)
    const pOver = 1 - pUnder

    const evOver = evPercent(pOver, prop.overOdds)
    const evUnder = evPercent(pUnder, prop.underOdds)

    const useOver = evOver >= evUnder
    const bestEv = useOver ? evOver : evUnder
    if (bestEv < minEv) continue

    const implied = americanToProb(useOver ? prop.overOdds : prop.underOdds)

    response.push({
      id: prop.id,
      game_id: gameId,
      player_name: prop.player.name,
      team: prop.player.team.abbr,
      stat_type: market,
      line: prop.line,
      over_odds: prop.overOdds,
      under_odds: prop.underOdds,
      projection: projection.mean,
      ev: bestEv,
      implied_prob: implied,
    })
  }

  return NextResponse.json(response)
}
