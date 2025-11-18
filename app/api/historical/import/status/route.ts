import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET(_request: NextRequest) {
  try {
    // Get statistics about imported historical data
    const [
      totalGames,
      gamesWithResults,
      totalPlayers,
      totalStats,
      oldestGame,
      newestGame,
      gamesByYear
    ] = await Promise.all([
      prisma.game.count(),
      prisma.game.count({
        where: {
          result: {
            isNot: null
          }
        }
      }),
      prisma.player.count(),
      prisma.playerGameStats.count(),
      prisma.game.findFirst({
        orderBy: { date: 'asc' },
        select: { date: true }
      }),
      prisma.game.findFirst({
        orderBy: { date: 'desc' },
        select: { date: true }
      }),
      prisma.$queryRaw<Array<{ year: number; count: bigint }>>`
        SELECT 
          CAST(strftime('%Y', date) AS INTEGER) as year,
          COUNT(*) as count
        FROM Game
        GROUP BY year
        ORDER BY year ASC
      `
    ])

    return NextResponse.json({
      summary: {
        totalGames,
        gamesWithResults,
        totalPlayers,
        totalStats,
        oldestGame: oldestGame?.date || null,
        newestGame: newestGame?.date || null
      },
      gamesByYear: gamesByYear.map((row) => ({
        year: row.year,
        count: Number(row.count)
      }))
    })
  } catch (error) {
    console.error('Status error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

