// lib/providers/historicalSync.ts

import { prisma } from '@/lib/db'

/**
 * Store historical odds snapshot - called whenever odds are updated
 */
export async function storeHistoricalOddsSnapshot(gameId: number): Promise<void> {
  const currentOdds = await prisma.gameOdds.findMany({
    where: { gameId },
  })

  for (const odds of currentOdds) {
    await prisma.historicalOddsSnapshot.create({
      data: {
        gameId: odds.gameId,
        bookmaker: odds.bookmaker,
        spreadHome: odds.spreadHome,
        spreadAway: odds.spreadAway,
        spreadHomeOdds: odds.spreadHomeOdds,
        spreadAwayOdds: odds.spreadAwayOdds,
        total: odds.total,
        overOdds: odds.overOdds,
        underOdds: odds.underOdds,
        mlHome: odds.mlHome,
        mlAway: odds.mlAway,
        snapshotTime: new Date(),
      },
    })
  }
}

/**
 * Store historical baseline snapshot - called when baselines are updated
 */
export async function storeHistoricalBaselineSnapshot(playerId: number): Promise<void> {
  const baselines = await prisma.playerBaseline.findMany({
    where: { playerId },
  })

  for (const baseline of baselines) {
    await prisma.historicalBaselineSnapshot.create({
      data: {
        playerId: baseline.playerId,
        market: baseline.market,
        mean: baseline.mean,
        stdev: baseline.stdev,
        minutes: baseline.minutes,
        usageRate: baseline.usageRate,
        snapshotTime: new Date(),
      },
    })
  }
}

/**
 * Store historical injury snapshot - called when injuries are updated
 */
export async function storeHistoricalInjurySnapshot(playerId: number): Promise<void> {
  const injury = await prisma.injury.findUnique({
    where: { playerId },
  })

  if (injury) {
    await prisma.historicalInjurySnapshot.create({
      data: {
        playerId: injury.playerId,
        teamId: injury.teamId,
        status: injury.status,
        note: injury.note,
        snapshotTime: new Date(),
      },
    })
  }
}

/**
 * Store game result when game is completed
 */
export async function storeGameResult(
  gameId: number,
  homeScore: number | null,
  awayScore: number | null,
  finalStatus: string
): Promise<void> {
  await prisma.gameResult.upsert({
    where: { gameId },
    update: {
      homeScore,
      awayScore,
      finalStatus,
      recordedAt: new Date(),
    },
    create: {
      gameId,
      homeScore,
      awayScore,
      finalStatus,
      recordedAt: new Date(),
    },
  })
}

/**
 * Sync historical data for completed games
 */
export async function syncHistoricalGameResults(): Promise<void> {
  // Get completed games without results
  const completedGames = await prisma.game.findMany({
    where: {
      status: 'Final',
      result: null,
    },
    include: {
      homeTeam: true,
      awayTeam: true,
    },
  })

  for (const game of completedGames) {
    // Try to get final scores from box scores or game data
    // For now, we'll mark as completed
    await storeGameResult(game.id, null, null, 'completed')
  }
}

