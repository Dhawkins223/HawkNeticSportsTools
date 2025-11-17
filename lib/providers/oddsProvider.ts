// lib/providers/oddsProvider.ts

import { prisma } from '../db'

const ODDS_API_KEY = process.env.ODDS_API_KEY
const ODDS_API_BASE_URL = process.env.ODDS_API_BASE_URL

if (!ODDS_API_KEY || !ODDS_API_BASE_URL) {
  console.warn('ODDS_API_KEY or ODDS_API_BASE_URL missing; odds sync will be skipped.')
}

interface ProviderMarketOutcome {
  name: string
  description?: string
  point: number
  price: number
  team?: string
}

interface ProviderMarket {
  key: string
  outcomes: ProviderMarketOutcome[]
}

interface ProviderBookmaker {
  key: string
  title: string
  markets: ProviderMarket[]
}

interface ProviderGame {
  id: string
  commence_time: string
  home_team: string
  away_team: string
  bookmakers: ProviderBookmaker[]
}

export async function syncUpcomingGamesAndOdds(): Promise<void> {
  if (!ODDS_API_KEY || !ODDS_API_BASE_URL) {
    return
  }

  const res = await fetch(
    `${ODDS_API_BASE_URL}/v4/sports/basketball_nba/odds?apiKey=${ODDS_API_KEY}&regions=us&markets=h2h,spreads,totals,player_points,player_assists,player_rebounds,player_threes`,
    { cache: 'no-store' }
  )

  if (!res.ok) {
    console.error('Failed to fetch odds', await res.text())
    return
  }

  const data = (await res.json()) as ProviderGame[]

  for (const game of data) {
    const homeTeam = await upsertTeam(game.home_team)
    const awayTeam = await upsertTeam(game.away_team)

    const dbGame = await prisma.game.upsert({
      where: { externalId: game.id },
      update: {
        date: new Date(game.commence_time),
        homeTeamId: homeTeam.id,
        awayTeamId: awayTeam.id,
        status: 'scheduled',
      },
      create: {
        externalId: game.id,
        date: new Date(game.commence_time),
        homeTeamId: homeTeam.id,
        awayTeamId: awayTeam.id,
        venue: '',
        status: 'scheduled',
      },
    })

    for (const book of game.bookmakers ?? []) {
      const markets = book.markets ?? []
      const spread = markets.find((m) => m.key === 'spreads')
      const total = markets.find((m) => m.key === 'totals')
      const moneyline = markets.find((m) => m.key === 'h2h')

      await prisma.gameOdds.create({
        data: {
          gameId: dbGame.id,
          bookmaker: book.title,
          spreadHome: spread
            ? spread.outcomes.find((o) => normalizeTeam(o.name) === homeTeam.abbr)?.point ?? null
            : null,
          spreadAway: spread
            ? spread.outcomes.find((o) => normalizeTeam(o.name) === awayTeam.abbr)?.point ?? null
            : null,
          total: total ? total.outcomes[0]?.point ?? null : null,
          mlHome: moneyline
            ? moneyline.outcomes.find((o) => normalizeTeam(o.name) === homeTeam.abbr)?.price ?? null
            : null,
          mlAway: moneyline
            ? moneyline.outcomes.find((o) => normalizeTeam(o.name) === awayTeam.abbr)?.price ?? null
            : null,
        },
      })

      const propMarkets = markets.filter((m) => m.key.startsWith('player_'))

      for (const market of propMarkets) {
        for (const outcome of market.outcomes ?? []) {
          const playerName = outcome.description || outcome.name
          if (!playerName) continue
          const normalizedMarket = mapMarketKey(market.key)

          const playerTeam = await resolvePlayerTeam(
            playerName,
            outcome.team,
            homeTeam.id,
            awayTeam.id
          )

          const player = await prisma.player.upsert({
            where: { name: playerName },
            update: { teamId: playerTeam },
            create: {
              name: playerName,
              teamId: playerTeam,
            },
          })

          await prisma.propOdds.upsert({
            where: {
              game_player_market_source: {
                gameId: dbGame.id,
                playerId: player.id,
                market: normalizedMarket,
                source: book.title,
              },
            },
            update: {
              line: outcome.point,
              overOdds: outcome.price,
              underOdds: outcome.price,
              updatedAt: new Date(),
            },
            create: {
              gameId: dbGame.id,
              playerId: player.id,
              market: normalizedMarket,
              line: outcome.point,
              overOdds: outcome.price,
              underOdds: outcome.price,
              source: book.title,
            },
          })
        }
      }
    }
  }
}

async function upsertTeam(abbrOrName: string) {
  const abbr = normalizeTeam(abbrOrName)
  return prisma.team.upsert({
    where: { abbr },
    update: {},
    create: {
      abbr,
      name: abbrOrName,
    },
  })
}

async function resolvePlayerTeam(
  playerName: string,
  teamHint: string | undefined,
  homeTeamId: number,
  awayTeamId: number
): Promise<number> {
  if (teamHint) {
    const existing = await prisma.team.findFirst({
      where: { abbr: normalizeTeam(teamHint) },
    })
    if (existing) {
      return existing.id
    }
  }

  const existingPlayer = await prisma.player.findFirst({
    where: { name: playerName },
  })
  if (existingPlayer) {
    return existingPlayer.teamId
  }

  return homeTeamId
}

function mapMarketKey(key: string): string {
  if (key.includes('points')) return 'points'
  if (key.includes('assists')) return 'assists'
  if (key.includes('rebounds')) return 'rebounds'
  if (key.includes('threes')) return 'threes'
  if (key.includes('pra')) return 'pra'
  return key
}

function normalizeTeam(value: string): string {
  return value.replace(/[^A-Z]/gi, '').toUpperCase()
}
