import { NextRequest, NextResponse } from 'next/server'

import { syncTodayGames, syncPlayerBaselines, syncInjuries } from '@/lib/providers/nbaFeed'
import { syncOddsSnapshots } from '@/lib/providers/oddsFeed'
import { syncHistoricalGameResults } from '@/lib/providers/historicalSync'

export async function POST(request: NextRequest) {
  const token = request.headers.get('x-admin-token')
  const expected = process.env.ADMIN_TOKEN

  if (!expected || token !== expected) {
    return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
  }

  const results: Record<string, 'success' | 'failed'> = {}
  const errors: Record<string, string> = {}

  try {
    await syncTodayGames()
    results.games = 'success'
  } catch (error) {
    results.games = 'failed'
    errors.games = error instanceof Error ? error.message : 'Unknown error'
    console.error('Failed to sync games:', error)
  }

  // Add delay between sync operations
  await new Promise(resolve => setTimeout(resolve, 1000))

  try {
    await syncOddsSnapshots()
    results.odds = 'success'
  } catch (error) {
    results.odds = 'failed'
    errors.odds = error instanceof Error ? error.message : 'Unknown error'
    console.error('Failed to sync odds:', error)
  }

  await new Promise(resolve => setTimeout(resolve, 1000))

  try {
    await syncInjuries()
    results.injuries = 'success'
  } catch (error) {
    results.injuries = 'failed'
    errors.injuries = error instanceof Error ? error.message : 'Unknown error'
    console.error('Failed to sync injuries:', error)
  }

  await new Promise(resolve => setTimeout(resolve, 1000))

  try {
    await syncPlayerBaselines()
    results.baselines = 'success'
  } catch (error) {
    results.baselines = 'failed'
    errors.baselines = error instanceof Error ? error.message : 'Unknown error'
    console.error('Failed to sync baselines:', error)
  }

  await new Promise(resolve => setTimeout(resolve, 1000))

  try {
    await syncHistoricalGameResults()
    results.historical = 'success'
  } catch (error) {
    results.historical = 'failed'
    errors.historical = error instanceof Error ? error.message : 'Unknown error'
    console.error('Failed to sync historical data:', error)
  }

  const allSuccess = Object.values(results).every(r => r === 'success')
  
  return NextResponse.json({
    ok: allSuccess,
    results,
    ...(Object.keys(errors).length > 0 && { errors })
  }, { status: allSuccess ? 200 : 207 }) // 207 Multi-Status for partial success
}
