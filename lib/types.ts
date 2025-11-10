export type SafetyLevel = 'safe' | 'neutral' | 'risky'

export interface MarketEdgeResult {
  trueProb: number
  fairOdds: number
  marketProb: number
  marketOdds: number
  evPct: number
  safety: SafetyLevel
}

export interface MarketSummary {
  type: 'moneyline' | 'spread' | 'total'
  label: string
  line: number | null
  odds: number
  edge: MarketEdgeResult
}

export interface PlayerRatingView {
  playerId: number
  playerName: string
  baseOverall: number
  matchupOverall: number
  offense: number
  defense: number
  playmaking: number
  usage: number
  fatigue: number
  volatility: number
}

export interface TeamSummary {
  id: number
  name: string
  abbr: string
  ratings: PlayerRatingView[]
}

export interface GameSummary {
  id: number
  externalId: string
  startTime: string
  venue: string | null
  status: string
  home: TeamSummary
  away: TeamSummary
  markets: MarketSummary[]
  latestOdds: {
    spreadHome: number | null
    spreadAway: number | null
    total: number | null
    mlHome: number | null
    mlAway: number | null
  }
}

export interface OddsHistoryPoint {
  id: number
  createdAt: string
  spreadHome: number | null
  spreadAway: number | null
  total: number | null
  mlHome: number | null
  mlAway: number | null
}

export interface PropEdge {
  id: number
  market: string
  line: number
  overOdds: number
  underOdds: number
  player: {
    id: number
    name: string
    team: string
  }
  projection: {
    mean: number
    stdev: number
  }
  over: MarketEdgeResult
  under: MarketEdgeResult
}

export interface GameDetail extends GameSummary {
  oddsHistory: OddsHistoryPoint[]
  props: PropEdge[]
}

export interface TeamDetail {
  id: number
  name: string
  abbr: string
  nextGame: {
    id: number
    opponentId: number
    date: string
    venue: string | null
    isHome: boolean
  }
  ratings: PlayerRatingView[]
}

export interface SgpLegInput {
  gameId: number
  playerId: number
  market: string
  line: number
  direction: 'over' | 'under'
  odds: number
}

export interface SgpSimulationResponse {
  jointProb: number
  fairOdds: number
  evPct: number
  kellyFraction: number
  legs: Array<{ id: string; baseHitProb: number }>
}
