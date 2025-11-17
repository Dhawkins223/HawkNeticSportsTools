import { NextRequest, NextResponse } from 'next/server'
import { importHistoricalData } from '@/lib/providers/historicalImport'

export async function POST(request: NextRequest) {
  try {
    const token = request.headers.get('x-admin-token')
    const expected = process.env.ADMIN_TOKEN

    if (!expected || token !== expected) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const body = await request.json().catch(() => ({}))
    const startYear = body.startYear ?? 2000
    const endYear = body.endYear ?? new Date().getFullYear()

    if (startYear < 2000 || startYear > new Date().getFullYear()) {
      return NextResponse.json(
        { error: 'Start year must be between 2000 and current year' },
        { status: 400 }
      )
    }

    if (endYear < startYear || endYear > new Date().getFullYear()) {
      return NextResponse.json(
        { error: 'End year must be between start year and current year' },
        { status: 400 }
      )
    }

    // Start import in background (this will take a long time)
    const progressMessages: string[] = []
    
    importHistoricalData(
      startYear,
      endYear,
      (message) => {
        progressMessages.push(`${new Date().toISOString()}: ${message}`)
        console.log(message)
      }
    ).catch((error) => {
      console.error('Historical import error:', error)
      progressMessages.push(`ERROR: ${error instanceof Error ? error.message : 'Unknown error'}`)
    })

    return NextResponse.json({
      message: 'Historical import started',
      startYear,
      endYear,
      note: 'This process will take a long time. Check server logs for progress.'
    })
  } catch (error) {
    console.error('Historical import route error:', error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal server error' },
      { status: 500 }
    )
  }
}

