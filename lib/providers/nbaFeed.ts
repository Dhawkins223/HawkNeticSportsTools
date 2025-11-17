// lib/providers/nbaFeed.ts

import { prisma } from '@/lib/db'
import { storeHistoricalBaselineSnapshot, storeHistoricalInjurySnapshot } from '@/lib/providers/historicalSync'

const NBA_API_BASE_URL = process.env.NBA_API_BASE_URL
const NBA_API_KEY = process.env.NBA_API_KEY

function assertEnvConfigured() {
  if (!NBA_API_BASE_URL || !NBA_API_KEY) {
    throw new Error('NBA API credentials are not configured.')
  }
}

interface ExternalTeam {
  id: number
  name?: string
  full_name?: string
  abbreviation: string
}

interface ExternalGame {
  id: number
  date?: string
  datetime?: string
  status: string | null
  home_team: ExternalTeam
  visitor_team?: ExternalTeam
  away_team?: ExternalTeam
  home_team_score?: number
  visitor_team_score?: number
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
      Authorization: NBA_API_KEY
    },
    cache: 'no-store'
  })

  if (!res.ok) {
    const detail = await res.text()
    // Handle rate limiting
    if (res.status === 429) {
      throw new Error(`NBA API rate limit exceeded. Please wait before retrying.`)
    }
    throw new Error(`NBA API request failed (${res.status}): ${detail}`)
  }

  const json = await res.json()
  // API returns { data: T, meta?: {...} } format, extract data
  return (json.data ?? json) as T
}

export async function syncTodayGames(): Promise<void> {
  const today = new Date().toISOString().split('T')[0] // YYYY-MM-DD format
  // Use proper array format for dates parameter
  const games = await authorizedFetch<ExternalGame[]>(`/nba/v1/games?dates[]=${encodeURIComponent(today)}`)
  
  // Add small delay to avoid rate limiting
  await new Promise(resolve => setTimeout(resolve, 500))

  for (const game of games) {
    const awayTeamData = game.away_team ?? game.visitor_team
    if (!awayTeamData) continue
    
    const homeTeam = await prisma.team.upsert({
      where: { abbr: game.home_team.abbreviation },
      update: { name: game.home_team.full_name ?? game.home_team.name },
      create: {
        abbr: game.home_team.abbreviation,
        name: game.home_team.full_name ?? game.home_team.name
      }
    })

    const awayTeam = await prisma.team.upsert({
      where: { abbr: awayTeamData.abbreviation },
      update: { name: awayTeamData.full_name ?? awayTeamData.name },
      create: {
        abbr: awayTeamData.abbreviation,
        name: awayTeamData.full_name ?? awayTeamData.name
      }
    })

    const gameDate = game.datetime ? new Date(game.datetime) : (game.date ? new Date(game.date) : new Date())
    
    await prisma.game.upsert({
      where: { externalId: game.id.toString() },
      update: {
        date: gameDate,
        venue: '',
        status: game.status ?? 'scheduled',
        homeTeamId: homeTeam.id,
        awayTeamId: awayTeam.id
      },
      create: {
        externalId: game.id.toString(),
        date: gameDate,
        venue: '',
        status: game.status ?? 'scheduled',
        homeTeamId: homeTeam.id,
        awayTeamId: awayTeam.id
      }
    })
  }
}

export async function syncBoxScores(gameExternalId: string): Promise<void> {
  // Get the game date first to query box scores
  const game = await prisma.game.findUnique({ where: { externalId: gameExternalId } })
  if (!game) {
    throw new Error(`Game ${gameExternalId} not found in database`)
  }
  
  const gameDate = game.date.toISOString().split('T')[0] // YYYY-MM-DD format
  const boxScores = await authorizedFetch<any[]>(`/nba/v1/box_scores?date=${gameDate}`)
  
  // Find the specific game in the box scores
  const gameBoxScore = boxScores.find((bs: any) => bs.game?.id?.toString() === gameExternalId)
  if (!gameBoxScore) {
    return // No box score data available yet
  }
  
  // Transform box score data to match expected format
  const rows: ExternalBoxScoreRow[] = []
  const allPlayers = [
    ...(gameBoxScore.home_team?.players ?? []),
    ...(gameBoxScore.visitor_team?.players ?? [])
  ]
  
  for (const playerStat of allPlayers) {
    if (!playerStat.player) continue
    
    const team = gameBoxScore.home_team?.team?.id === playerStat.player.team?.id 
      ? gameBoxScore.home_team.team 
      : gameBoxScore.visitor_team.team
    
    rows.push({
      game_id: gameExternalId,
      player_id: playerStat.player.id.toString(),
      player_name: `${playerStat.player.first_name} ${playerStat.player.last_name}`,
      team_id: team?.id.toString() ?? '',
      team_abbr: team?.abbreviation ?? '',
      minutes: parseFloat(playerStat.min?.replace(':', '.') ?? '0') || 0,
      points: playerStat.pts ?? 0,
      rebounds: playerStat.reb ?? 0,
      assists: playerStat.ast ?? 0,
      threes: playerStat.fg3m ?? 0
    })
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
  // Note: This endpoint may not be available in all API tiers
  // If it fails, we'll skip it gracefully
  try {
    const injuriesResponse = await authorizedFetch<any[]>('/nba/v1/player_injuries')
  
  // Transform API response to match expected format
  const injuries: ExternalInjuryRow[] = injuriesResponse.map((injury: any) => ({
    player_id: injury.player?.id?.toString() ?? '',
    player_name: injury.player ? `${injury.player.first_name} ${injury.player.last_name}` : '',
    team_abbr: injury.player?.team?.abbreviation ?? '',
    team_name: injury.player?.team?.full_name ?? '',
    status: injury.status ?? '',
    note: injury.description ?? ''
  }))

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

    // Store historical snapshot
    await storeHistoricalInjurySnapshot(player.id)
  }
  } catch (error) {
    // Injuries endpoint may not be available - log and continue
    console.warn('Injuries sync skipped:', error instanceof Error ? error.message : 'Unknown error')
    // Don't throw - allow sync to continue with other data
  }
}

export async function syncPlayerBaselines(): Promise<void> {
  // Get current season year
  const currentYear = new Date().getFullYear()
  const season = new Date().getMonth() >= 9 ? currentYear : currentYear - 1 // NBA season starts in October
  
  // Get all players from database
  const players = await prisma.player.findMany({
    where: { externalId: { not: null } },
    take: 50 // Limit to avoid too many requests and rate limiting
  })
  
  const rows: ExternalBaselineRow[] = []
  
  // Fetch season averages for each player to calculate baselines
  for (const player of players) {
    if (!player.externalId) continue
    
    try {
      // Add delay between requests to avoid rate limiting
      await new Promise(resolve => setTimeout(resolve, 200))
      
      const seasonAverages = await authorizedFetch<any[]>(
        `/nba/v1/season_averages?season=${season}&player_id=${player.externalId}`
      )
      
      if (seasonAverages && seasonAverages.length > 0) {
        const avg = seasonAverages[0]
        // Calculate baselines from season averages
        // Points baseline
        if (avg.pts !== undefined) {
          rows.push({
            player_id: player.externalId,
            market: 'points',
            mean: avg.pts,
            stdev: Math.max(1.5, avg.pts * 0.3), // Estimate stdev as 30% of mean
            minutes: parseFloat(avg.min?.replace(':', '.') ?? '24') || 24,
            usage_rate: 0.2 // Default usage rate, could be calculated from advanced stats
          })
        }
        // Assists baseline
        if (avg.ast !== undefined) {
          rows.push({
            player_id: player.externalId,
            market: 'assists',
            mean: avg.ast,
            stdev: Math.max(0.5, avg.ast * 0.4),
            minutes: parseFloat(avg.min?.replace(':', '.') ?? '24') || 24,
            usage_rate: 0.2
          })
        }
        // Rebounds baseline
        if (avg.reb !== undefined) {
          rows.push({
            player_id: player.externalId,
            market: 'rebounds',
            mean: avg.reb,
            stdev: Math.max(0.5, avg.reb * 0.35),
            minutes: parseFloat(avg.min?.replace(':', '.') ?? '24') || 24,
            usage_rate: 0.2
          })
        }
        // Threes baseline
        if (avg.fg3m !== undefined) {
          rows.push({
            player_id: player.externalId,
            market: 'threes',
            mean: avg.fg3m,
            stdev: Math.max(0.3, avg.fg3m * 0.5),
            minutes: parseFloat(avg.min?.replace(':', '.') ?? '24') || 24,
            usage_rate: 0.2
          })
        }
      }
    } catch (error) {
      // Skip players without season data
      continue
    }
  }

  for (const row of rows) {
    const player = await prisma.player.findFirst({
      where: { externalId: row.player_id }
    })

    if (!player) {
      continue
    }

    const wasUpdate = await prisma.playerBaseline.findUnique({
      where: {
        playerId_market: {
          playerId: player.id,
          market: row.market
        }
      }
    })

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

    // Store historical snapshot if this was an update
    if (wasUpdate) {
      await storeHistoricalBaselineSnapshot(player.id)
    }
  }
}

export async function syncPropsForGame(gameExternalId: string): Promise<void> {
  await syncBoxScores(gameExternalId)
}
