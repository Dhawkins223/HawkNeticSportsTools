import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'
import { storeLLMGameData, storeLLMPlayerData, storeLLMInjuryData, extractJSONFromResponse } from '@/lib/llm/dataParser'

export async function POST(request: NextRequest) {
  try {
    const userId = request.cookies.get('user-id')?.value

    if (!userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const formData = await request.formData()
    const file = formData.get('file') as File

    if (!file) {
      return NextResponse.json({ error: 'No file provided' }, { status: 400 })
    }

    // Create import record
    const importRecord = await prisma.dataImport.create({
      data: {
        userId: parseInt(userId),
        fileName: file.name,
        fileType: file.name.split('.').pop() || 'unknown',
        recordCount: 0,
        status: 'processing',
      },
    })

    try {
      const text = await file.text()
      let data: any

      // Try to parse as JSON
      try {
        data = JSON.parse(text)
      } catch (e) {
        // If direct parse fails, try to extract JSON from text (in case it's wrapped)
        data = extractJSONFromResponse(text) || JSON.parse(text)
      }

      let recordCount = 0
      const errors: string[] = []

      // Process imported games
      if (data.games && Array.isArray(data.games)) {
        for (const gameData of data.games) {
          try {
            await storeLLMGameData(gameData)
            recordCount++
          } catch (error) {
            errors.push(`Game error: ${error instanceof Error ? error.message : 'Unknown error'}`)
          }
        }
      } else if (data.homeTeam && data.awayTeam) {
        // Single game object
        try {
          await storeLLMGameData(data)
          recordCount++
        } catch (error) {
          errors.push(`Game error: ${error instanceof Error ? error.message : 'Unknown error'}`)
        }
      }

      // Process imported players
      if (data.players && Array.isArray(data.players)) {
        for (const playerData of data.players) {
          try {
            await storeLLMPlayerData(playerData)
            recordCount++
          } catch (error) {
            errors.push(`Player error: ${error instanceof Error ? error.message : 'Unknown error'}`)
          }
        }
      } else if (data.name && data.team && !data.homeTeam) {
        // Single player object (not a game)
        try {
          await storeLLMPlayerData(data)
          recordCount++
        } catch (error) {
          errors.push(`Player error: ${error instanceof Error ? error.message : 'Unknown error'}`)
        }
      }

      // Process imported injuries
      if (data.injuries && Array.isArray(data.injuries)) {
        for (const injuryData of data.injuries) {
          try {
            await storeLLMInjuryData(injuryData)
            recordCount++
          } catch (error) {
            errors.push(`Injury error: ${error instanceof Error ? error.message : 'Unknown error'}`)
          }
        }
      } else if (data.playerName && data.status && !data.homeTeam && !data.name) {
        // Single injury object
        try {
          await storeLLMInjuryData(data)
          recordCount++
        } catch (error) {
          errors.push(`Injury error: ${error instanceof Error ? error.message : 'Unknown error'}`)
        }
      }

      // Update import record
      await prisma.dataImport.update({
        where: { id: importRecord.id },
        data: {
          status: errors.length > 0 && recordCount === 0 ? 'failed' : 'completed',
          recordCount,
          completedAt: new Date(),
          error: errors.length > 0 ? errors.join('; ') : null,
        },
      })

      return NextResponse.json({
        success: recordCount > 0,
        importId: importRecord.id,
        recordCount,
        errors: errors.length > 0 ? errors : undefined,
      })
    } catch (error) {
      await prisma.dataImport.update({
        where: { id: importRecord.id },
        data: {
          status: 'failed',
          error: error instanceof Error ? error.message : 'Unknown error',
        },
      })

      throw error
    }
  } catch (error) {
    console.error('Import error:', error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal server error' },
      { status: 500 }
    )
  }
}

