export type Team = {
  id: string;
  name: string;
  abbreviation: string;
  logoUrl?: string;
  record: string;
};

export type GameOdds = {
  moneylineHome: number;
  moneylineAway: number;
  spread: number;
  spreadHome: number;
  spreadAway: number;
  total: number;
  over: number;
  under: number;
};

export type Game = {
  id: string;
  date: string;
  status: string;
  homeTeam: Team;
  awayTeam: Team;
  odds: GameOdds;
  model: {
    pace: number;
    injuryReport: string[];
    travelFatigue: Record<string, number>;
    blowoutRisk: number;
  };
};

export type Prop = {
  id: string;
  player: string;
  team: string;
  market: string;
  line: number;
  overOdds: number;
  underOdds: number;
  modelMean: number;
  modelStdDev: number;
};

export type SimulationLeg = {
  id: string;
  description: string;
  odds: number;
};

export type SimulationResponse = {
  ticketId: string;
  legs: SimulationLeg[];
  joint: {
    p_joint: number;
    ev: number;
  };
};

export type Ticket = {
  id: string;
  gameId: string;
  title: string;
  legs: SimulationLeg[];
  stake: number;
  odds: number;
  expectedValue: number;
};
