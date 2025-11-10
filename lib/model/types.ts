// lib/model/types.ts

export type StatType =
  | 'points'
  | 'rebounds'
  | 'assists'
  | 'threes'
  | 'pra'

export interface ContextAdjustments {
  paceFactor: number
  blowoutRisk: number
  injuryImpactTeam: Record<string, number>
  matchupDifficulty: Record<string, number>
  restDays: Record<string, number>
  travelPenalty: Record<string, number>
}

export interface PlayerProjection {
  mean: number
  stdev: number
}

export interface SimulationLeg {
  prop_id: number
  playerId: number
  playerName: string
  teamAbbr: string
  stat: StatType
  direction: 'over' | 'under'
  line: number
  odds: number
}

export interface SimulationResult {
  legs: SimulationLeg[]
  p_joint: number
  implied_prob: number
  fair_odds: number
  ev: number
  bookmaker_odds: number
  model_inputs: ContextAdjustments
}
