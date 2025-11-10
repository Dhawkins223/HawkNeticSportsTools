// lib/providers/injuriesProvider.ts

import { prisma } from '../db'

const INJURY_API_BASE = process.env.INJURY_API_BASE
const INJURY_API_KEY = process.env.INJURY_API_KEY

if (!INJURY_API_BASE || !INJURY_API_KEY) {
  console.warn('INJURY_API_BASE or INJURY_API_KEY missing; injury sync will be skipped.')
}

interface ProviderInjuryRow {
  player_name: string
  team_abbr: string
  team_name: string
  status: string
  note?: string
}

export async function syncInjuries(): Promise<void> {
  if (!INJURY_API_BASE || !INJURY_API_KEY) {
    return
  }

  const res = await fetch(
    `${INJURY_API_BASE}/nba/injuries?key=${INJURY_API_KEY}`,
    { cache: 'no-store' }
  )

  if (!res.ok) {
    console.error('Failed to fetch injuries', await res.text())
    return
  }

  const rows = (await res.json()) as ProviderInjuryRow[]

  for (const row of rows) {
    const team = await prisma.team.upsert({
      where: { abbr: row.team_abbr },
      update: { name: row.team_name },
      create: {
        abbr: row.team_abbr,
        name: row.team_name,
      },
    })

    const player = await prisma.player.upsert({
      where: { name: row.player_name },
      update: { teamId: team.id },
      create: {
        name: row.player_name,
        teamId: team.id,
      },
    })

    await prisma.injury.upsert({
      where: { playerId: player.id },
      update: {
        status: row.status,
        note: row.note ?? '',
        updatedAt: new Date(),
        teamId: team.id,
      },
      create: {
        playerId: player.id,
        teamId: team.id,
        status: row.status,
        note: row.note ?? '',
      },
    })
  }
}
