// lib/providers/oddsFeed.ts

import { prisma } from '@/lib/db'
import { storeHistoricalOddsSnapshot } from '@/lib/providers/historicalSync'

const ODDS_API_BASE_URL = process.env.ODDS_API_BASE_URL
const ODDS_API_KEY = process.env.ODDS_API_KEY

function assertEnvConfigured() {
  if (!ODDS_API_BASE_URL || !ODDS_API_KEY) {
    throw new Error('Odds API credentials are not configured.')
  }
}

interface ExternalOddsGame {
  id: string
  sport_key: string
  commence_time: string
  home_team: string
  away_team: string
  bookmakers: ExternalBookmaker[]
}

interface ExternalBookmaker {
  key: string
  title: string
  last_update: string
  markets: ExternalMarket[]
}

interface ExternalMarket {
  key: string
  outcomes: ExternalOutcome[]
}

interface ExternalOutcome {
  name: string
  price: number
  point?: number
  description?: string
  team?: string
}

async function authorizedFetch<T>(path: string): Promise<T> {
  assertEnvConfigured()
  // Add apiKey as query parameter (The Odds API uses query param, not header)
  const separator = path.includes('?') ? '&' : '?'
  const url = `${ODDS_API_BASE_URL}${path}${separator}apiKey=${ODDS_API_KEY}`
  const res = await fetch(url, {
    cache: 'no-store'
  })

  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`Odds API request failed (${res.status}): ${detail}`)
  }

  return (await res.json()) as T
}

export async function syncOddsSnapshots(): Promise<void> {
  // Note: Player prop markets (player_points, player_assists, etc.) may require a different endpoint
  // For now, we'll sync game markets (h2h, spreads, totals) which are supported
  const games = await authorizedFetch<ExternalOddsGame[]>(
    '/v4/sports/basketball_nba/odds?regions=us&markets=h2h,spreads,totals'
  )

  for (const game of games) {
    // The Odds API uses different game IDs than NBA API
    // Match games by date and team names instead
    const gameDate = new Date(game.commence_time)
    const startOfDay = new Date(gameDate.getFullYear(), gameDate.getMonth(), gameDate.getDate())
    const endOfDay = new Date(startOfDay)
    endOfDay.setDate(endOfDay.getDate() + 1)
    
    // Normalize team names for matching
    const normalizeTeamName = (name: string) => name.replace(/[^A-Z]/gi, '').toUpperCase()
    const homeTeamNormalized = normalizeTeamName(game.home_team)
    const awayTeamNormalized = normalizeTeamName(game.away_team)
    
    const dbGame = await prisma.game.findFirst({
      where: {
        date: {
          gte: startOfDay,
          lt: endOfDay
        },
        homeTeam: {
          abbr: homeTeamNormalized
        },
        awayTeam: {
          abbr: awayTeamNormalized
        }
      },
      include: {
        homeTeam: true,
        awayTeam: true
      }
    })
    
    if (!dbGame) {
      continue
    }

    // The Odds API structure: game -> bookmakers -> markets
    for (const bookmaker of game.bookmakers ?? []) {
      for (const market of bookmaker.markets ?? []) {
        if (market.key === 'h2h' || market.key === 'spreads' || market.key === 'totals') {
          await persistGameMarket(dbGame, market, bookmaker.title)
        } else if (market.key.startsWith('player_')) {
          await persistPlayerMarket(dbGame, market, bookmaker.title)
        }
      }
    }
  }
}

async function persistGameMarket(
  game: { id: number; homeTeam: { abbr: string }; awayTeam: { abbr: string } },
  market: ExternalMarket,
  bookmaker: string
) {
  const outcomes = market.outcomes ?? []

  // Match outcomes by team name/abbreviation (The Odds API uses team names in outcome.name)
  const spreadHome = market.key === 'spreads' 
    ? outcomes.find((o) => normalizeTeam(o.name) === game.homeTeam.abbr)
    : null
  const spreadAway = market.key === 'spreads'
    ? outcomes.find((o) => normalizeTeam(o.name) === game.awayTeam.abbr)
    : null
  const overOutcome = market.key === 'totals'
    ? outcomes.find((o) => o.name.toLowerCase().includes('over'))
    : null
  const underOutcome = market.key === 'totals'
    ? outcomes.find((o) => o.name.toLowerCase().includes('under'))
    : null
  const homeMl = market.key === 'h2h'
    ? outcomes.find((o) => normalizeTeam(o.name) === game.homeTeam.abbr)
    : null
  const awayMl = market.key === 'h2h'
    ? outcomes.find((o) => normalizeTeam(o.name) === game.awayTeam.abbr)
    : null

  await prisma.gameOdds.create({
    data: {
      gameId: game.id,
      bookmaker,
      spreadHome: spreadHome?.point ?? null,
      spreadAway: spreadAway?.point ?? null,
      spreadHomeOdds: spreadHome?.price ?? null,
      spreadAwayOdds: spreadAway?.price ?? null,
      total: overOutcome?.point ?? underOutcome?.point ?? null,
      overOdds: overOutcome?.price ?? null,
      underOdds: underOutcome?.price ?? null,
      mlHome: homeMl?.price ?? null,
      mlAway: awayMl?.price ?? null
    }
  })

  // Store historical snapshot
  await storeHistoricalOddsSnapshot(game.id)
}

async function persistPlayerMarket(
  game: { id: number; homeTeamId: number; awayTeamId: number },
  market: ExternalMarket,
  bookmaker: string
) {
  const normalizedMarket = mapMarketKey(market.key)

  const grouped = new Map<number, { line: number; overOdds?: number | null; underOdds?: number | null }>()

  for (const outcome of market.outcomes ?? []) {
    // The Odds API uses 'description' field for player names in player prop markets
    const playerName = outcome.description || outcome.name
    if (!playerName) {
      continue
    }

    const teamId = await resolveTeamId(outcome.team, game)
    if (!teamId) continue

    const player = await prisma.player.upsert({
      where: { name: playerName },
      update: { teamId },
      create: { name: playerName, teamId }
    })

    const existing = grouped.get(player.id) ?? { line: outcome.point ?? 0 }
    existing.line = outcome.point ?? existing.line

    if (outcome.name.toLowerCase().includes('over')) {
      existing.overOdds = outcome.price
    } else if (outcome.name.toLowerCase().includes('under')) {
      existing.underOdds = outcome.price
    } else {
      existing.overOdds = outcome.price
      existing.underOdds = outcome.price
    }

    grouped.set(player.id, existing)
  }

  for (const [playerId, entry] of grouped.entries()) {
    await prisma.propOdds.upsert({
      where: {
        game_player_market_source: {
          gameId: game.id,
          playerId,
          market: normalizedMarket,
          source: bookmaker
        }
      },
      update: {
        line: entry.line,
        overOdds: entry.overOdds ?? entry.underOdds ?? 0,
        underOdds: entry.underOdds ?? entry.overOdds ?? 0,
        updatedAt: new Date()
      },
      create: {
        gameId: game.id,
        playerId,
        market: normalizedMarket,
        line: entry.line,
        overOdds: entry.overOdds ?? entry.underOdds ?? 0,
        underOdds: entry.underOdds ?? entry.overOdds ?? 0,
        source: bookmaker
      }
    })
  }
}

function normalizeTeam(value: string): string {
  return value.replace(/[^A-Z]/gi, '').toUpperCase()
}

function mapMarketKey(key: string): string {
  if (key.includes('points')) return 'points'
  if (key.includes('assists')) return 'assists'
  if (key.includes('rebounds')) return 'rebounds'
  if (key.includes('threes')) return 'threes'
  if (key.includes('pra')) return 'pra'
  return key
}

async function resolveTeamId(teamKey: string | undefined, game: { homeTeamId: number; awayTeamId: number }): Promise<number | null> {
  if (teamKey) {
    const normalized = teamKey.replace(/[^A-Z]/gi, '').toUpperCase()
    const team = await prisma.team.findFirst({ where: { abbr: normalized } })
    if (team) {
      return team.id
    }
  }
  return game.homeTeamId ?? game.awayTeamId ?? null
}
