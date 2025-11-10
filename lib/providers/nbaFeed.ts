// lib/providers/nbaFeed.ts

import { prisma } from '@/lib/db'

const NBA_API_BASE_URL = process.env.NBA_API_BASE_URL
const NBA_API_KEY = process.env.NBA_API_KEY

function assertEnvConfigured() {
  if (!NBA_API_BASE_URL || !NBA_API_KEY) {
    throw new Error('NBA API credentials are not configured.')
  }
}

interface ExternalTeam {
  id: string
  name: string
  abbreviation: string
}

interface ExternalGame {
  id: string
  start_time: string
  venue?: string
  status: string
  home_team: ExternalTeam
  away_team: ExternalTeam
}

interface ExternalBoxScoreRow {
  game_id: string
  player_id: string
  player_name: string
  team_id: string
  team_abbr: string
  minutes: number
  points: number
  rebounds: number
  assists: number
  threes: number
}

interface ExternalInjuryRow {
  player_id: string
  player_name: string
  team_abbr: string
  team_name: string
  status: string
  note?: string
}

interface ExternalBaselineRow {
  player_id: string
  market: string
  mean: number
  stdev: number
  minutes: number
  usage_rate: number
}

async function authorizedFetch<T>(path: string, init?: RequestInit): Promise<T> {
  assertEnvConfigured()
  const url = `${NBA_API_BASE_URL}${path}`
  const res = await fetch(url, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      Authorization: `Bearer ${NBA_API_KEY}`
    },
    cache: 'no-store'
  })

  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`NBA API request failed (${res.status}): ${detail}`)
  }

  return (await res.json()) as T
}

export async function syncTodayGames(): Promise<void> {
  const games = await authorizedFetch<ExternalGame[]>('/games/today')

  for (const game of games) {
    const homeTeam = await prisma.team.upsert({
      where: { abbr: game.home_team.abbreviation },
      update: { name: game.home_team.name },
      create: {
        abbr: game.home_team.abbreviation,
        name: game.home_team.name
      }
    })

    const awayTeam = await prisma.team.upsert({
      where: { abbr: game.away_team.abbreviation },
      update: { name: game.away_team.name },
      create: {
        abbr: game.away_team.abbreviation,
        name: game.away_team.name
      }
    })

    await prisma.game.upsert({
      where: { externalId: game.id },
      update: {
        date: new Date(game.start_time),
        venue: game.venue ?? '',
        status: game.status,
        homeTeamId: homeTeam.id,
        awayTeamId: awayTeam.id
      },
      create: {
        externalId: game.id,
        date: new Date(game.start_time),
        venue: game.venue ?? '',
        status: game.status,
        homeTeamId: homeTeam.id,
        awayTeamId: awayTeam.id
      }
    })
  }
}

export async function syncBoxScores(gameExternalId: string): Promise<void> {
  const rows = await authorizedFetch<ExternalBoxScoreRow[]>(`/games/${gameExternalId}/boxscore`)

  const game = await prisma.game.findUnique({ where: { externalId: gameExternalId } })
  if (!game) {
    throw new Error(`Game ${gameExternalId} not found in database`)
  }

  for (const row of rows) {
    const team = await prisma.team.upsert({
      where: { abbr: row.team_abbr },
      update: {},
      create: {
        abbr: row.team_abbr,
        name: row.team_abbr
      }
    })

    const player = await prisma.player.upsert({
      where: { externalId: row.player_id },
      update: {
        name: row.player_name,
        teamId: team.id
      },
      create: {
        externalId: row.player_id,
        name: row.player_name,
        teamId: team.id
      }
    })

    await prisma.playerGameStats.upsert({
      where: {
        gameId_playerId: {
          gameId: game.id,
          playerId: player.id
        }
      },
      update: {
        minutes: row.minutes,
        points: row.points,
        rebounds: row.rebounds,
        assists: row.assists,
        threes: row.threes,
        createdAt: new Date()
      },
      create: {
        gameId: game.id,
        playerId: player.id,
        minutes: row.minutes,
        points: row.points,
        rebounds: row.rebounds,
        assists: row.assists,
        threes: row.threes
      }
    })
  }
}

export async function syncInjuries(): Promise<void> {
  const injuries = await authorizedFetch<ExternalInjuryRow[]>('/injuries')

  for (const injury of injuries) {
    const team = await prisma.team.upsert({
      where: { abbr: injury.team_abbr },
      update: { name: injury.team_name },
      create: {
        abbr: injury.team_abbr,
        name: injury.team_name
      }
    })

    const player = await prisma.player.upsert({
      where: { name: injury.player_name },
      update: { teamId: team.id },
      create: {
        name: injury.player_name,
        teamId: team.id
      }
    })

    await prisma.injury.upsert({
      where: { playerId: player.id },
      update: {
        teamId: team.id,
        status: injury.status,
        note: injury.note ?? '',
        updatedAt: new Date()
      },
      create: {
        playerId: player.id,
        teamId: team.id,
        status: injury.status,
        note: injury.note ?? ''
      }
    })
  }
}

export async function syncPlayerBaselines(): Promise<void> {
  const rows = await authorizedFetch<ExternalBaselineRow[]>('/players/baselines')

  for (const row of rows) {
    const player = await prisma.player.findFirst({
      where: { externalId: row.player_id }
    })

    if (!player) {
      continue
    }

    await prisma.playerBaseline.upsert({
      where: {
        playerId_market: {
          playerId: player.id,
          market: row.market
        }
      },
      update: {
        mean: row.mean,
        stdev: row.stdev,
        minutes: row.minutes,
        usageRate: row.usage_rate,
        updatedAt: new Date()
      },
      create: {
        playerId: player.id,
        market: row.market,
        mean: row.mean,
        stdev: row.stdev,
        minutes: row.minutes,
        usageRate: row.usage_rate
      }
    })
  }
}

export async function syncPropsForGame(gameExternalId: string): Promise<void> {
  await syncBoxScores(gameExternalId)
}
