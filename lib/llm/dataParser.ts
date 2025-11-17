// lib/llm/dataParser.ts

import { prisma } from '@/lib/db'

interface LLMGameData {
  homeTeam: string
  awayTeam: string
  date: string
  venue?: string
  status?: string
  odds?: {
    bookmaker: string
    spreadHome?: number
    spreadAway?: number
    total?: number
    overOdds?: number
    underOdds?: number
    mlHome?: number
    mlAway?: number
  }
  result?: {
    homeScore?: number
    awayScore?: number
    finalStatus?: string
  }
  players?: Array<{
    name: string
    team: string
    stats?: {
      points?: number
      rebounds?: number
      assists?: number
      threes?: number
      minutes?: number
    }
  }>
}

interface LLMPlayerData {
  name: string
  team: string
  baselines?: Array<{
    market: string
    mean: number
    stdev?: number
    minutes?: number
    usageRate?: number
  }>
}

interface LLMInjuryData {
  playerName: string
  team: string
  status: string
  note?: string
}

/**
 * Extract JSON data from LLM response
 */
export function extractJSONFromResponse(response: string): any | null {
  // Try to find JSON in code blocks
  const codeBlockMatch = response.match(/```(?:json)?\s*(\{[\s\S]*?\})\s*```/)
  if (codeBlockMatch) {
    try {
      return JSON.parse(codeBlockMatch[1])
    } catch (e) {
      // Continue to try other methods
    }
  }

  // Try to find JSON object directly
  const jsonMatch = response.match(/\{[\s\S]*\}/)
  if (jsonMatch) {
    try {
      return JSON.parse(jsonMatch[0])
    } catch (e) {
      // Continue
    }
  }

  // Try to find array
  const arrayMatch = response.match(/\[[\s\S]*\]/)
  if (arrayMatch) {
    try {
      return JSON.parse(arrayMatch[0])
    } catch (e) {
      // Continue
    }
  }

  return null
}

/**
 * Check if user is requesting data to be added/updated
 */
export function isDataRequest(message: string): boolean {
  const lowerMessage = message.toLowerCase()
  const dataKeywords = [
    'add game',
    'create game',
    'add player',
    'create player',
    'add odds',
    'update odds',
    'add stats',
    'update stats',
    'add injury',
    'update injury',
    'add baseline',
    'update baseline',
    'provide data',
    'give me data',
    'generate data',
    'create data',
    'insert data',
    'store data',
  ]

  return dataKeywords.some((keyword) => lowerMessage.includes(keyword))
}

/**
 * Store game data from LLM
 */
export async function storeLLMGameData(gameData: LLMGameData): Promise<number> {
  // Normalize team abbreviations
  const normalizeTeam = (name: string): string => {
    const teamMap: Record<string, string> = {
      'lakers': 'LAL',
      'los angeles lakers': 'LAL',
      'warriors': 'GSW',
      'golden state warriors': 'GSW',
      'celtics': 'BOS',
      'boston celtics': 'BOS',
      'heat': 'MIA',
      'miami heat': 'MIA',
      'knicks': 'NYK',
      'new york knicks': 'NYK',
      '76ers': 'PHI',
      'philadelphia 76ers': 'PHI',
      'nuggets': 'DEN',
      'denver nuggets': 'DEN',
      'suns': 'PHX',
      'phoenix suns': 'PHX',
      'bucks': 'MIL',
      'milwaukee bucks': 'MIL',
      'nets': 'BKN',
      'brooklyn nets': 'BKN',
      'clippers': 'LAC',
      'los angeles clippers': 'LAC',
      'mavericks': 'DAL',
      'dallas mavericks': 'DAL',
      'bulls': 'CHI',
      'chicago bulls': 'CHI',
      'rockets': 'HOU',
      'houston rockets': 'HOU',
      'thunder': 'OKC',
      'oklahoma city thunder': 'OKC',
      'trail blazers': 'POR',
      'portland trail blazers': 'POR',
      'kings': 'SAC',
      'sacramento kings': 'SAC',
      'spurs': 'SAS',
      'san antonio spurs': 'SAS',
      'raptors': 'TOR',
      'toronto raptors': 'TOR',
      'wizards': 'WAS',
      'washington wizards': 'WAS',
      'hawks': 'ATL',
      'atlanta hawks': 'ATL',
      'hornets': 'CHA',
      'charlotte hornets': 'CHA',
      'cavaliers': 'CLE',
      'cleveland cavaliers': 'CLE',
      'pistons': 'DET',
      'detroit pistons': 'DET',
      'pacers': 'IND',
      'indiana pacers': 'IND',
      'grizzlies': 'MEM',
      'memphis grizzlies': 'MEM',
      'timberwolves': 'MIN',
      'minnesota timberwolves': 'MIN',
      'pelicans': 'NOP',
      'new orleans pelicans': 'NOP',
      'magic': 'ORL',
      'orlando magic': 'ORL',
    }

    const normalized = name.toLowerCase().trim()
    if (teamMap[normalized]) {
      return teamMap[normalized]
    }

    // Try to extract abbreviation from name
    const words = name.split(' ')
    if (words.length >= 2) {
      return words
        .map((w) => w[0])
        .join('')
        .toUpperCase()
        .slice(0, 3)
    }

    return name.toUpperCase().slice(0, 3)
  }

  const homeAbbr = normalizeTeam(gameData.homeTeam)
  const awayAbbr = normalizeTeam(gameData.awayTeam)

  // Upsert teams
  const homeTeam = await prisma.team.upsert({
    where: { abbr: homeAbbr },
    update: {},
    create: {
      abbr: homeAbbr,
      name: gameData.homeTeam,
    },
  })

  const awayTeam = await prisma.team.upsert({
    where: { abbr: awayAbbr },
    update: {},
    create: {
      abbr: awayAbbr,
      name: gameData.awayTeam,
    },
  })

  // Parse date
  const gameDate = new Date(gameData.date)

  // Create game with LLM-generated external ID
  const externalId = `llm-${Date.now()}-${Math.random().toString(36).substring(7)}`
  const dbGame = await prisma.game.upsert({
    where: { externalId },
    update: {
      date: gameDate,
      venue: gameData.venue || '',
      status: gameData.status || 'scheduled',
      homeTeamId: homeTeam.id,
      awayTeamId: awayTeam.id,
    },
    create: {
      externalId,
      date: gameDate,
      venue: gameData.venue || '',
      status: gameData.status || 'scheduled',
      homeTeamId: homeTeam.id,
      awayTeamId: awayTeam.id,
    },
  })

  // Store odds if provided
  if (gameData.odds) {
    await prisma.gameOdds.create({
      data: {
        gameId: dbGame.id,
        bookmaker: gameData.odds.bookmaker || 'LLM Generated',
        spreadHome: gameData.odds.spreadHome ?? null,
        spreadAway: gameData.odds.spreadAway ?? null,
        total: gameData.odds.total ?? null,
        overOdds: gameData.odds.overOdds ?? null,
        underOdds: gameData.odds.underOdds ?? null,
        mlHome: gameData.odds.mlHome ?? null,
        mlAway: gameData.odds.mlAway ?? null,
      },
    })
  }

  // Store result if provided
  if (gameData.result) {
    await prisma.gameResult.upsert({
      where: { gameId: dbGame.id },
      update: {
        homeScore: gameData.result.homeScore ?? null,
        awayScore: gameData.result.awayScore ?? null,
        finalStatus: gameData.result.finalStatus || 'completed',
      },
      create: {
        gameId: dbGame.id,
        homeScore: gameData.result.homeScore ?? null,
        awayScore: gameData.result.awayScore ?? null,
        finalStatus: gameData.result.finalStatus || 'completed',
      },
    })
  }

  // Store player stats if provided
  if (gameData.players) {
    for (const playerData of gameData.players) {
      const playerTeam = await prisma.team.findFirst({
        where: {
          OR: [
            { abbr: normalizeTeam(playerData.team) },
            { name: { contains: playerData.team, mode: 'insensitive' } },
          ],
        },
      })

      if (!playerTeam) continue

      // Find or create player
      let player = await prisma.player.findFirst({
        where: {
          name: playerData.name,
          teamId: playerTeam.id,
        },
      })

      if (!player) {
        player = await prisma.player.create({
          data: {
            name: playerData.name,
            teamId: playerTeam.id,
          },
        })
      }

      if (playerData.stats) {
        await prisma.playerGameStats.upsert({
          where: {
            gameId_playerId: {
              gameId: dbGame.id,
              playerId: player.id,
            },
          },
          update: {
            minutes: playerData.stats.minutes ?? 0,
            points: playerData.stats.points ?? 0,
            rebounds: playerData.stats.rebounds ?? 0,
            assists: playerData.stats.assists ?? 0,
            threes: playerData.stats.threes ?? 0,
          },
          create: {
            gameId: dbGame.id,
            playerId: player.id,
            minutes: playerData.stats.minutes ?? 0,
            points: playerData.stats.points ?? 0,
            rebounds: playerData.stats.rebounds ?? 0,
            assists: playerData.stats.assists ?? 0,
            threes: playerData.stats.threes ?? 0,
          },
        })
      }
    }
  }

  return dbGame.id
}

/**
 * Store player data from LLM
 */
export async function storeLLMPlayerData(playerData: LLMPlayerData): Promise<void> {
  const normalizeTeam = (name: string): string => {
    // Use same normalization as above (simplified)
    return name.toUpperCase().slice(0, 3)
  }

  const team = await prisma.team.findFirst({
    where: {
      OR: [
        { abbr: normalizeTeam(playerData.team) },
        { name: { contains: playerData.team, mode: 'insensitive' } },
      ],
    },
  })

  if (!team) {
    throw new Error(`Team not found: ${playerData.team}`)
  }

  // Find or create player
  let player = await prisma.player.findFirst({
    where: {
      name: playerData.name,
      teamId: team.id,
    },
  })

  if (!player) {
    player = await prisma.player.create({
      data: {
        name: playerData.name,
        teamId: team.id,
      },
    })
  } else if (player.teamId !== team.id) {
    // Update team if changed
    player = await prisma.player.update({
      where: { id: player.id },
      data: { teamId: team.id },
    })
  }

  if (playerData.baselines) {
    for (const baseline of playerData.baselines) {
      await prisma.playerBaseline.upsert({
        where: {
          playerId_market: {
            playerId: player.id,
            market: baseline.market,
          },
        },
        update: {
          mean: baseline.mean,
          stdev: baseline.stdev ?? baseline.mean * 0.3,
          minutes: baseline.minutes ?? 30,
          usageRate: baseline.usageRate ?? 0.2,
        },
        create: {
          playerId: player.id,
          market: baseline.market,
          mean: baseline.mean,
          stdev: baseline.stdev ?? baseline.mean * 0.3,
          minutes: baseline.minutes ?? 30,
          usageRate: baseline.usageRate ?? 0.2,
        },
      })
    }
  }
}

/**
 * Store injury data from LLM
 */
export async function storeLLMInjuryData(injuryData: LLMInjuryData): Promise<void> {
  const normalizeTeam = (name: string): string => {
    return name.toUpperCase().slice(0, 3)
  }

  const team = await prisma.team.findFirst({
    where: {
      OR: [
        { abbr: normalizeTeam(injuryData.team) },
        { name: { contains: injuryData.team, mode: 'insensitive' } },
      ],
    },
  })

  if (!team) {
    throw new Error(`Team not found: ${injuryData.team}`)
  }

  // Find or create player
  let player = await prisma.player.findFirst({
    where: {
      name: injuryData.playerName,
      teamId: team.id,
    },
  })

  if (!player) {
    player = await prisma.player.create({
      data: {
        name: injuryData.playerName,
        teamId: team.id,
      },
    })
  }

  await prisma.injury.upsert({
    where: { playerId: player.id },
    update: {
      teamId: team.id,
      status: injuryData.status,
      note: injuryData.note || '',
      updatedAt: new Date(),
    },
    create: {
      playerId: player.id,
      teamId: team.id,
      status: injuryData.status,
      note: injuryData.note || '',
    },
  })
}

/**
 * Process and store data from LLM response
 */
export async function processLLMDataResponse(
  response: string,
  userMessage: string
): Promise<{ stored: boolean; count: number; message: string }> {
  const jsonData = extractJSONFromResponse(response)

  if (!jsonData) {
    return { stored: false, count: 0, message: 'No structured data found in response' }
  }

  let storedCount = 0
  const messages: string[] = []

  try {
    // Handle games
    if (jsonData.games && Array.isArray(jsonData.games)) {
      for (const game of jsonData.games) {
        await storeLLMGameData(game)
        storedCount++
      }
      messages.push(`Stored ${jsonData.games.length} game(s)`)
    } else if (jsonData.homeTeam && jsonData.awayTeam) {
      // Single game object
      await storeLLMGameData(jsonData as LLMGameData)
      storedCount++
      messages.push('Stored 1 game')
    }

    // Handle players
    if (jsonData.players && Array.isArray(jsonData.players)) {
      for (const player of jsonData.players) {
        await storeLLMPlayerData(player)
        storedCount++
      }
      messages.push(`Stored ${jsonData.players.length} player(s)`)
    } else if (jsonData.name && jsonData.team) {
      // Single player object
      await storeLLMPlayerData(jsonData as LLMPlayerData)
      storedCount++
      messages.push('Stored 1 player')
    }

    // Handle injuries
    if (jsonData.injuries && Array.isArray(jsonData.injuries)) {
      for (const injury of jsonData.injuries) {
        await storeLLMInjuryData(injury)
        storedCount++
      }
      messages.push(`Stored ${jsonData.injuries.length} injury record(s)`)
    } else if (jsonData.playerName && jsonData.status) {
      // Single injury object
      await storeLLMInjuryData(jsonData as LLMInjuryData)
      storedCount++
      messages.push('Stored 1 injury record')
    }

    return {
      stored: storedCount > 0,
      count: storedCount,
      message: messages.join(', '),
    }
  } catch (error) {
    return {
      stored: false,
      count: 0,
      message: `Error storing data: ${error instanceof Error ? error.message : 'Unknown error'}`,
    }
  }
}

