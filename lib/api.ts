import type {
  GameDetail,
  GameSummary,
  PropEdge,
  SgpLegInput,
  SgpSimulationResponse,
  TeamDetail
} from './types'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_BASE_URL?.trim() || ''

async function fetchJson<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {})
    }
  })

  if (!res.ok) {
    const message = await res.text()
    throw new Error(message || `Request failed with status ${res.status}`)
  }

  return (await res.json()) as T
}

export async function getGames(): Promise<GameSummary[]> {
  return fetchJson<GameSummary[]>('/api/nba/games')
}

export async function getGameDetail(id: number): Promise<GameDetail> {
  return fetchJson<GameDetail>(`/api/nba/games/${id}`)
}

export async function getProps(gameId: number): Promise<PropEdge[]> {
  const game = await getGameDetail(gameId)
  return game.props
}

export async function getTeamDetail(identifier: string | number): Promise<TeamDetail> {
  return fetchJson<TeamDetail>(`/api/nba/teams/${identifier}`)
}

export async function runSimulation(legs: SgpLegInput[], offeredOdds: number): Promise<SgpSimulationResponse> {
  return fetchJson<SgpSimulationResponse>('/api/nba/sgp/simulate', {
    method: 'POST',
    body: JSON.stringify({ legs, offeredOdds })
  })
}

export async function triggerSync(adminToken: string) {
  return fetchJson('/api/sync', {
    method: 'POST',
    headers: {
      'x-admin-token': adminToken
    }
  })
}
