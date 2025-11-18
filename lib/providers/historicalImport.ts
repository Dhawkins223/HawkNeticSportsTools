// lib/providers/historicalImport.ts

import { prisma } from '@/lib/db'
import { storeGameResult } from './historicalSync'

const NBA_API_BASE_URL = process.env.NBA_API_BASE_URL
const NBA_API_KEY = process.env.NBA_API_KEY

function assertEnvConfigured() {
  if (!NBA_API_BASE_URL || !NBA_API_KEY) {
    throw new Error('NBA API credentials are not configured.')
  }
}

interface ExternalGame {
  id: number
  date?: string
  datetime?: string
  status: string | null
  home_team: {
    id: number
    name?: string
    full_name?: string
    abbreviation: string
  }
  visitor_team?: {
    id: number
    name?: string
    full_name?: string
    abbreviation: string
  }
  away_team?: {
    id: number
    name?: string
    full_name?: string
    abbreviation: string
  }
  home_team_score?: number
  visitor_team_score?: number
  away_team_score?: number
}

interface ExternalBoxScore {
  game?: {
    id: number
  }
  home_team?: {
    team: {
      id: number
      abbreviation: string
      full_name: string
    }
    players?: Array<{
      player: {
        id: number
        first_name: string
        last_name: string
        team?: {
          id: number
        }
      }
      min?: string
      pts?: number
      reb?: number
      ast?: number
      fg3m?: number
    }>
  }
  visitor_team?: {
    team: {
      id: number
      abbreviation: string
      full_name: string
    }
    players?: Array<{
      player: {
        id: number
        first_name: string
        last_name: string
        team?: {
          id: number
        }
      }
      min?: string
      pts?: number
      reb?: number
      ast?: number
      fg3m?: number
    }>
  }
}

async function authorizedFetch<T>(path: string, init?: RequestInit): Promise<T> {
  assertEnvConfigured()
  if (!NBA_API_BASE_URL || !NBA_API_KEY) {
    throw new Error('NBA API credentials are not configured')
  }
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
    if (res.status === 429) {
      throw new Error(`NBA API rate limit exceeded. Please wait before retrying.`)
    }
    throw new Error(`NBA API request failed (${res.status}): ${detail}`)
  }

  const json = await res.json()
  return (json.data ?? json) as T
}

/**
 * Get all dates for an NBA season (October to June)
 */
function getSeasonDates(year: number): Date[] {
  const dates: Date[] = []
  // NBA season starts in October of the year and ends in June of the next year
  const startDate = new Date(year, 9, 1) // October 1
  const endDate = new Date(year + 1, 5, 30) // June 30 of next year
  
  const current = new Date(startDate)
  while (current <= endDate) {
    dates.push(new Date(current))
    current.setDate(current.getDate() + 1)
  }
  
  return dates
}

/**
 * Import games for a specific date
 */
async function importGamesForDate(date: Date, onProgress?: (message: string) => void): Promise<number> {
  const dateStr = date.toISOString().split('T')[0]
  onProgress?.(`Fetching games for ${dateStr}...`)
  
  try {
    const games = await authorizedFetch<ExternalGame[]>(
      `/nba/v1/games?dates[]=${encodeURIComponent(dateStr)}`
    )
    
    let imported = 0
    for (const game of games) {
      const awayTeamData = game.away_team ?? game.visitor_team
      if (!awayTeamData) continue
      
      const homeTeamName = game.home_team.full_name ?? game.home_team.name ?? game.home_team.abbreviation
      const homeTeam = await prisma.team.upsert({
        where: { abbr: game.home_team.abbreviation },
        update: { name: homeTeamName },
        create: {
          abbr: game.home_team.abbreviation,
          name: homeTeamName
        }
      })

      const awayTeamName = awayTeamData.full_name ?? awayTeamData.name ?? awayTeamData.abbreviation
      const awayTeam = await prisma.team.upsert({
        where: { abbr: awayTeamData.abbreviation },
        update: { name: awayTeamName },
        create: {
          abbr: awayTeamData.abbreviation,
          name: awayTeamName
        }
      })

      const gameDate = game.datetime ? new Date(game.datetime) : (game.date ? new Date(game.date) : date)
      
      const dbGame = await prisma.game.upsert({
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

      // If game is completed, store the result
      if (game.status === 'Final' || game.status === 'finished') {
        const homeScore = game.home_team_score ?? game.visitor_team_score ?? null
        const awayScore = game.away_team_score ?? game.visitor_team_score ?? null
        
        await storeGameResult(
          dbGame.id,
          homeScore,
          awayScore,
          'completed'
        )
      }

      imported++
    }
    
    // Delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 300))
    
    return imported
  } catch (error) {
    onProgress?.(`Error importing games for ${dateStr}: ${error instanceof Error ? error.message : 'Unknown error'}`)
    // Continue with next date even if one fails
    return 0
  }
}

/**
 * Import box scores for a specific date
 */
async function importBoxScoresForDate(date: Date, onProgress?: (message: string) => void): Promise<number> {
  const dateStr = date.toISOString().split('T')[0]
  onProgress?.(`Fetching box scores for ${dateStr}...`)
  
  try {
    const boxScores = await authorizedFetch<ExternalBoxScore[]>(
      `/nba/v1/box_scores?date=${dateStr}`
    )
    
    let imported = 0
    for (const boxScore of boxScores) {
      if (!boxScore.game?.id) continue
      
      const game = await prisma.game.findUnique({
        where: { externalId: boxScore.game.id.toString() }
      })
      
      if (!game) continue
      
      const allPlayers = [
        ...(boxScore.home_team?.players ?? []),
        ...(boxScore.visitor_team?.players ?? [])
      ]
      
      for (const playerStat of allPlayers) {
        if (!playerStat.player) continue
        
        let team = boxScore.home_team?.team
        if (!team || team.id !== playerStat.player.team?.id) {
          team = boxScore.visitor_team?.team
        }
        
        if (!team) continue
        
        const dbTeam = await prisma.team.upsert({
          where: { abbr: team.abbreviation },
          update: { name: team.full_name },
          create: {
            abbr: team.abbreviation,
            name: team.full_name
          }
        })
        
        const playerName = `${playerStat.player.first_name} ${playerStat.player.last_name}`
        const externalId = playerStat.player.id.toString()
        
        // Try to find by externalId first, then by name
        let dbPlayer = await prisma.player.findFirst({
          where: {
            OR: [
              { externalId },
              { name: playerName }
            ]
          }
        })
        
        if (dbPlayer) {
          dbPlayer = await prisma.player.update({
            where: { id: dbPlayer.id },
            data: {
              name: playerName,
              teamId: dbTeam.id,
              externalId
            }
          })
        } else {
          dbPlayer = await prisma.player.create({
            data: {
              name: playerName,
              teamId: dbTeam.id,
              externalId
            }
          })
        }
        
        await prisma.playerGameStats.upsert({
          where: {
            gameId_playerId: {
              gameId: game.id,
              playerId: dbPlayer.id
            }
          },
          update: {
            minutes: parseFloat(playerStat.min?.replace(':', '.') ?? '0') || 0,
            points: playerStat.pts ?? 0,
            rebounds: playerStat.reb ?? 0,
            assists: playerStat.ast ?? 0,
            threes: playerStat.fg3m ?? 0
          },
          create: {
            gameId: game.id,
            playerId: dbPlayer.id,
            minutes: parseFloat(playerStat.min?.replace(':', '.') ?? '0') || 0,
            points: playerStat.pts ?? 0,
            rebounds: playerStat.reb ?? 0,
            assists: playerStat.ast ?? 0,
            threes: playerStat.fg3m ?? 0
          }
        })
      }
      
      imported++
    }
    
    // Delay to avoid rate limiting
    await new Promise(resolve => setTimeout(resolve, 300))
    
    return imported
  } catch (error) {
    onProgress?.(`Error importing box scores for ${dateStr}: ${error instanceof Error ? error.message : 'Unknown error'}`)
    return 0
  }
}

/**
 * Import historical data for a range of years
 */
export async function importHistoricalData(
  startYear: number = 2000,
  endYear?: number,
  onProgress?: (message: string) => void
): Promise<{ gamesImported: number; boxScoresImported: number; errors: string[] }> {
  const currentYear = new Date().getFullYear()
  const finalEndYear = endYear ?? currentYear
  
  onProgress?.(`Starting historical import from ${startYear} to ${finalEndYear}...`)
  
  let totalGamesImported = 0
  let totalBoxScoresImported = 0
  const errors: string[] = []
  
  // Process each year
  for (let year = startYear; year <= finalEndYear; year++) {
    onProgress?.(`\n=== Processing ${year}-${year + 1} season ===`)
    
    const seasonDates = getSeasonDates(year)
    onProgress?.(`Found ${seasonDates.length} days in season`)
    
    // Process dates in batches to avoid overwhelming the API
    const batchSize = 7 // Process one week at a time
    for (let i = 0; i < seasonDates.length; i += batchSize) {
      const batch = seasonDates.slice(i, i + batchSize)
      onProgress?.(`Processing batch ${Math.floor(i / batchSize) + 1} of ${Math.ceil(seasonDates.length / batchSize)}`)
      
      for (const date of batch) {
        try {
          const gamesCount = await importGamesForDate(date, onProgress)
          totalGamesImported += gamesCount
          
          // Only import box scores for completed games (after the game date)
          const today = new Date()
          today.setHours(0, 0, 0, 0)
          if (date < today) {
            const boxScoresCount = await importBoxScoresForDate(date, onProgress)
            totalBoxScoresImported += boxScoresCount
          }
        } catch (error) {
          const errorMsg = `Error processing ${date.toISOString().split('T')[0]}: ${error instanceof Error ? error.message : 'Unknown error'}`
          errors.push(errorMsg)
          onProgress?.(errorMsg)
        }
      }
      
      // Longer delay between batches
      await new Promise(resolve => setTimeout(resolve, 2000))
    }
    
    onProgress?.(`\nCompleted ${year}-${year + 1} season. Total games: ${totalGamesImported}, Box scores: ${totalBoxScoresImported}`)
  }
  
  onProgress?.(`\n=== Import Complete ===`)
  onProgress?.(`Total games imported: ${totalGamesImported}`)
  onProgress?.(`Total box scores imported: ${totalBoxScoresImported}`)
  onProgress?.(`Errors: ${errors.length}`)
  
  return {
    gamesImported: totalGamesImported,
    boxScoresImported: totalBoxScoresImported,
    errors
  }
}

