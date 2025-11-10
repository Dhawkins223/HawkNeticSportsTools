import { NextRequest, NextResponse } from 'next/server'

import { prisma } from '@/lib/db'
import { buildTeamRatings } from '@/lib/model/ratings'

export async function GET(_request: NextRequest, { params }: { params: { id: string } }) {
  const identifier = params.id
  let team = null

  if (/^\d+$/.test(identifier)) {
    team = await prisma.team.findUnique({ where: { id: Number(identifier) } })
  } else {
    team = await prisma.team.findUnique({ where: { abbr: identifier.toUpperCase() } })
  }

  if (!team) {
    return NextResponse.json({ error: 'Team not found' }, { status: 404 })
  }

  const upcomingGame = await prisma.game.findFirst({
    where: {
      date: { gte: new Date() },
      OR: [{ homeTeamId: team.id }, { awayTeamId: team.id }]
    },
    orderBy: { date: 'asc' }
  })

  if (!upcomingGame) {
    return NextResponse.json(
      { error: 'Upstream data unavailable. Configure env & sync.' },
      { status: 503 }
    )
  }

  const opponentId = upcomingGame.homeTeamId === team.id ? upcomingGame.awayTeamId : upcomingGame.homeTeamId
  const ratings = await buildTeamRatings(team.id, opponentId, upcomingGame.date)

  return NextResponse.json({
    id: team.id,
    name: team.name,
    abbr: team.abbr,
    nextGame: {
      id: upcomingGame.id,
      opponentId,
      date: upcomingGame.date.toISOString(),
      venue: upcomingGame.venue,
      isHome: upcomingGame.homeTeamId === team.id
    },
    ratings
  })
}
