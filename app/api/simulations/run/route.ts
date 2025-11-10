// app/api/simulations/run/route.ts

import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'
import { buildContextForGame } from '@/lib/model/context'
import { runParlaySimulation } from '@/lib/model/simulation'
import { SimulationLeg } from '@/lib/model/types'

export async function POST(req: NextRequest) {
  try {
    const body = await req.json()
    const { game_id, legs, odds } = body as {
      game_id: number
      legs: Array<Partial<SimulationLeg>>
      odds: number
    }

    if (!game_id || !Array.isArray(legs) || typeof odds !== 'number') {
      return NextResponse.json(
        { error: 'game_id, legs, and odds are required' },
        { status: 400 }
      )
    }

    const fullLegs: SimulationLeg[] = []

    for (const leg of legs) {
      if (typeof leg.prop_id !== 'number') continue

      const prop = await prisma.propOdds.findUnique({
        where: { id: leg.prop_id },
        include: {
          player: { include: { team: true } },
        },
      })

      if (!prop) continue

      const direction: SimulationLeg['direction'] = leg.direction === 'under' ? 'under' : 'over'

      fullLegs.push({
        prop_id: prop.id,
        playerId: prop.playerId,
        playerName: prop.player.name,
        teamAbbr: prop.player.team.abbr,
        stat: prop.market as SimulationLeg['stat'],
        direction,
        line: leg.line ?? prop.line,
        odds: leg.odds ?? prop.overOdds,
      })
    }

    if (!fullLegs.length) {
      return NextResponse.json({ error: 'No valid legs found' }, { status: 400 })
    }

    const ctx = await buildContextForGame(game_id)
    const result = await runParlaySimulation(game_id, fullLegs, odds, ctx)

    return NextResponse.json(result)
  } catch (error) {
    console.error(error)
    return NextResponse.json({ error: 'Simulation failed' }, { status: 500 })
  }
}
