// lib/providers/statsProvider.ts

import { prisma } from '../db'

const STATS_API_BASE = process.env.STATS_API_BASE
const STATS_API_KEY = process.env.STATS_API_KEY

if (!STATS_API_BASE || !STATS_API_KEY) {
  console.warn('STATS_API_BASE or STATS_API_KEY missing; stats sync will be skipped.')
}

interface ProviderStatRow {
  game_external_id: string
  player_name: string
  team_abbr: string
  team_name: string
  minutes: number
  points: number
  rebounds: number
  assists: number
  threes: number
}

export async function syncRecentPlayerStats(): Promise<void> {
  if (!STATS_API_BASE || !STATS_API_KEY) {
    return
  }

  const res = await fetch(
    `${STATS_API_BASE}/nba/recent_stats?key=${STATS_API_KEY}`,
    { cache: 'no-store' }
  )

  if (!res.ok) {
    console.error('Failed to fetch stats', await res.text())
    return
  }

  const rows = (await res.json()) as ProviderStatRow[]

  for (const row of rows) {
    const team = await prisma.team.upsert({
      where: { abbr: row.team_abbr },
      update: { name: row.team_name },
      create: {
        abbr: row.team_abbr,
        name: row.team_name,
      },
    })

    const player = await prisma.player.upsert({
      where: { name: row.player_name },
      update: { teamId: team.id },
      create: {
        name: row.player_name,
        teamId: team.id,
      },
    })

    const game = await prisma.game.findUnique({
      where: { externalId: row.game_external_id },
    })

    if (!game) {
      continue
    }

    await prisma.playerGameStats.upsert({
      where: {
        gameId_playerId: {
          gameId: game.id,
          playerId: player.id,
        },
      },
      update: {
        minutes: row.minutes,
        points: row.points,
        rebounds: row.rebounds,
        assists: row.assists,
        threes: row.threes,
        createdAt: new Date(),
      },
      create: {
        gameId: game.id,
        playerId: player.id,
        minutes: row.minutes,
        points: row.points,
        rebounds: row.rebounds,
        assists: row.assists,
        threes: row.threes,
      },
    })
  }
}
