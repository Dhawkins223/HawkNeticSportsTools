// app/api/refresh/route.ts

import { NextRequest, NextResponse } from 'next/server'
import { syncUpcomingGamesAndOdds } from '@/lib/providers/oddsProvider'
import { syncRecentPlayerStats } from '@/lib/providers/statsProvider'
import { syncInjuries } from '@/lib/providers/injuriesProvider'

export async function POST(_req: NextRequest) {
  try {
    await syncUpcomingGamesAndOdds()
    await syncRecentPlayerStats()
    await syncInjuries()
    return NextResponse.json({ ok: true })
  } catch (error) {
    console.error(error)
    return NextResponse.json({ error: 'Refresh failed' }, { status: 500 })
  }
}
