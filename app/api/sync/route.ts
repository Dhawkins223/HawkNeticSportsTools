import { NextRequest, NextResponse } from 'next/server'

import { syncTodayGames, syncPlayerBaselines, syncInjuries } from '@/lib/providers/nbaFeed'
import { syncOddsSnapshots } from '@/lib/providers/oddsFeed'

export async function POST(request: NextRequest) {
  const token = request.headers.get('x-admin-token')
  const expected = process.env.ADMIN_TOKEN

  if (!expected || token !== expected) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  try {
    await syncTodayGames()
    await syncOddsSnapshots()
    await syncInjuries()
    await syncPlayerBaselines()

    return NextResponse.json({ ok: true })
  } catch (error) {
    console.error(error)
    const detail = error instanceof Error ? error.message : 'Sync failed'
    return NextResponse.json({ error: 'Sync failed', detail }, { status: 500 })
  }
}
