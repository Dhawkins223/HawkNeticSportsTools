import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET(request: NextRequest) {
  try {
    const userId = request.cookies.get('user-id')?.value

    if (!userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const { searchParams } = new URL(request.url)
    const format = searchParams.get('format') || 'json'
    const type = searchParams.get('type') || 'all'

    let data: any = {}

    if (type === 'all' || type === 'games') {
      const games = await prisma.game.findMany({
        include: {
          homeTeam: true,
          awayTeam: true,
          result: true,
          odds: true,
        },
      })
      data.games = games
    }

    if (type === 'all' || type === 'players') {
      const players = await prisma.player.findMany({
        include: {
          team: true,
          stats: true,
          baselines: true,
        },
      })
      data.players = players
    }

    if (type === 'all' || type === 'odds') {
      const odds = await prisma.gameOdds.findMany({
        include: {
          game: {
            include: {
              homeTeam: true,
              awayTeam: true,
            },
          },
        },
      })
      data.odds = odds
    }

    if (type === 'all' || type === 'historical') {
      const historicalOdds = await prisma.historicalOddsSnapshot.findMany({
        include: {
          game: {
            include: {
              homeTeam: true,
              awayTeam: true,
            },
          },
        },
      })
      data.historicalOdds = historicalOdds
    }

    if (format === 'csv') {
      // Convert to CSV format (simplified)
      const csv = convertToCSV(data)
      return new NextResponse(csv, {
        headers: {
          'Content-Type': 'text/csv',
          'Content-Disposition': `attachment; filename="nba_data_${Date.now()}.csv"`,
        },
      })
    }

    return NextResponse.json(data, {
      headers: {
        'Content-Disposition': `attachment; filename="nba_data_${Date.now()}.json"`,
      },
    })
  } catch (error) {
    console.error('Export error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

function convertToCSV(data: any): string {
  // Simplified CSV conversion
  let csv = ''
  
  if (data.games) {
    csv += 'Game ID,Date,Home Team,Away Team,Status\n'
    data.games.forEach((game: any) => {
      csv += `${game.id},${game.date},${game.homeTeam.name},${game.awayTeam.name},${game.status}\n`
    })
  }

  return csv
}

