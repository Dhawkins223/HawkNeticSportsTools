import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET(_request: NextRequest) {
  try {
    const [
      gameCount,
      playerCount,
      teamCount,
      oddsCount,
      injuryCount,
      baselineCount,
      historicalOddsCount,
      historicalBaselineCount,
      recentGames,
      recentSync
    ] = await Promise.all([
      prisma.game.count(),
      prisma.player.count(),
      prisma.team.count(),
      prisma.gameOdds.count(),
      prisma.injury.count(),
      prisma.playerBaseline.count(),
      prisma.historicalOddsSnapshot.count(),
      prisma.historicalBaselineSnapshot.count(),
      prisma.game.findMany({
        take: 5,
        orderBy: { date: 'desc' },
        include: {
          homeTeam: true,
          awayTeam: true,
          result: true,
        },
      }),
      prisma.gameOdds.findFirst({
        orderBy: { createdAt: 'desc' },
        select: { createdAt: true },
      }),
    ])

    return NextResponse.json({
      counts: {
        games: gameCount,
        players: playerCount,
        teams: teamCount,
        odds: oddsCount,
        injuries: injuryCount,
        baselines: baselineCount,
        historicalOdds: historicalOddsCount,
        historicalBaselines: historicalBaselineCount,
      },
      recentGames: recentGames.map((game) => ({
        id: game.id,
        date: game.date,
        homeTeam: game.homeTeam.name,
        awayTeam: game.awayTeam.name,
        status: game.status,
        hasResult: !!game.result,
      })),
      lastSync: recentSync?.createdAt || null,
    })
  } catch (error) {
    console.error('Stats error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

