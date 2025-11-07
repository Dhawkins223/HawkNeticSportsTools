import gamesMock from "../__mocks__/games.json" assert { type: "json" };
import propsMock from "../__mocks__/props.json" assert { type: "json" };
import simulationMock from "../__mocks__/simulation.json" assert { type: "json" };
import type { Game, Prop, SimulationResponse, Ticket } from "./types";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
const USE_MOCK = !API_BASE_URL;

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(`Failed to fetch ${path}: ${res.status}`);
  }
  return (await res.json()) as T;
}

export async function getGames(): Promise<Game[]> {
  if (USE_MOCK) {
    return gamesMock.games as Game[];
  }
  return fetchJson<Game[]>("/games");
}

export async function getGameById(id: string): Promise<Game | undefined> {
  if (USE_MOCK) {
    return (gamesMock.games as Game[]).find((game) => game.id === id);
  }
  return fetchJson<Game>(`/games/${id}`);
}

export async function getProps(gameId?: string): Promise<Prop[]> {
  if (USE_MOCK) {
    const props = propsMock.props as Prop[];
    return gameId ? props.filter((prop) => prop.id.startsWith(gameId)) : props;
  }
  const url = gameId ? `/props?gameId=${encodeURIComponent(gameId)}` : "/props";
  return fetchJson<Prop[]>(url);
}

export async function getTickets(): Promise<Ticket[]> {
  if (USE_MOCK) {
    return gamesMock.tickets as Ticket[];
  }
  return fetchJson<Ticket[]>("/tickets");
}

export async function runSimulation(legs: { id: string; odds: number }[]): Promise<SimulationResponse> {
  if (USE_MOCK) {
    return simulationMock as SimulationResponse;
  }
  const res = await fetch(`${API_BASE_URL}/simulations/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json"
    },
    body: JSON.stringify({ legs })
  });
  if (!res.ok) {
    throw new Error(`Failed to simulate ticket: ${res.status}`);
  }
  return (await res.json()) as SimulationResponse;
}

export const isMockMode = USE_MOCK;
