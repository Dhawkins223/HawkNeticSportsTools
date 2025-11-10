// lib/providers/oddsFeed.ts

import { prisma } from '@/lib/db'

const ODDS_API_BASE_URL = process.env.ODDS_API_BASE_URL
const ODDS_API_KEY = process.env.ODDS_API_KEY

function assertEnvConfigured() {
  if (!ODDS_API_BASE_URL || !ODDS_API_KEY) {
    throw new Error('Odds API credentials are not configured.')
  }
}

interface ExternalOddsGame {
  id: string
  commence_time: string
  markets: ExternalMarket[]
  home_team: string
  away_team: string
}

interface ExternalMarket {
  key: string
  bookmaker: string
  line?: number
  outcomes?: ExternalOutcome[]
}

interface ExternalOutcome {
  name: string
  price: number
  point?: number
  player?: string
  team?: string
}

async function authorizedFetch<T>(path: string): Promise<T> {
  assertEnvConfigured()
  const url = `${ODDS_API_BASE_URL}${path}`
  const res = await fetch(url, {
    headers: {
      'X-API-KEY': ODDS_API_KEY!
    },
    cache: 'no-store'
  })

  if (!res.ok) {
    const detail = await res.text()
    throw new Error(`Odds API request failed (${res.status}): ${detail}`)
  }

  return (await res.json()) as T
}

export async function syncOddsSnapshots(): Promise<void> {
  const games = await authorizedFetch<ExternalOddsGame[]>(
    '/nba/games?markets=h2h,spreads,totals,player_points,player_assists,player_rebounds,player_threes'
  )

  for (const game of games) {
    const dbGame = await prisma.game.findUnique({
      where: { externalId: game.id },
      include: {
        homeTeam: true,
        awayTeam: true
      }
    })
    if (!dbGame) {
      continue
    }

    for (const market of game.markets ?? []) {
      if (market.key === 'h2h' || market.key === 'spreads' || market.key === 'totals') {
        await persistGameMarket(dbGame.id, market)
      } else if (market.key.startsWith('player_')) {
        await persistPlayerMarket(dbGame, market)
      }
    }
  }
}

async function persistGameMarket(gameId: number, market: ExternalMarket) {
  const bookmaker = market.bookmaker || 'Unknown'
  const outcomes = market.outcomes ?? []

  const spreadHome = outcomes.find((o) => o.team === 'home' || o.name.toLowerCase().includes('home'))
  const spreadAway = outcomes.find((o) => o.team === 'away' || o.name.toLowerCase().includes('away'))
  const overOutcome = outcomes.find((o) => o.name.toLowerCase().includes('over'))
  const underOutcome = outcomes.find((o) => o.name.toLowerCase().includes('under'))
  const homeMl = outcomes.find((o) => o.team === 'home' || o.name.toLowerCase().includes('home'))
  const awayMl = outcomes.find((o) => o.team === 'away' || o.name.toLowerCase().includes('away'))

  await prisma.gameOdds.create({
    data: {
      gameId,
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
}

async function persistPlayerMarket(
  game: { id: number; homeTeamId: number; awayTeamId: number },
  market: ExternalMarket
) {
  const bookmaker = market.bookmaker || 'Unknown'
  const normalizedMarket = mapMarketKey(market.key)

  const grouped = new Map<number, { line: number; overOdds?: number | null; underOdds?: number | null }>()

  for (const outcome of market.outcomes ?? []) {
    if (!outcome.player) {
      continue
    }

    const teamId = await resolveTeamId(outcome.team, game)
    if (!teamId) continue

    const player = await prisma.player.upsert({
      where: { name: outcome.player },
      update: { teamId },
      create: { name: outcome.player, teamId }
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
