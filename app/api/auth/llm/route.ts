import { NextRequest, NextResponse } from 'next/server'
import { prisma } from '@/lib/db'

export async function GET(request: NextRequest) {
  try {
    const userId = request.cookies.get('user-id')?.value

    if (!userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const user = await prisma.user.findUnique({
      where: { id: parseInt(userId) },
      select: {
        llmProvider: true,
        llmModel: true,
        llmApiKey: true, // Check if exists, but don't return the actual key
      },
    })

    if (!user) {
      return NextResponse.json({ error: 'User not found' }, { status: 404 })
    }

    return NextResponse.json({
      provider: user.llmProvider,
      model: user.llmModel,
      hasApiKey: !!user.llmApiKey, // Indicate if API key is set without exposing it
    })
  } catch (error) {
    console.error('Get LLM settings error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

export async function PUT(request: NextRequest) {
  try {
    const userId = request.cookies.get('user-id')?.value

    if (!userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const { provider, apiKey, model } = await request.json()

    // Validate provider if provided
    const validProviders = ['openai', 'anthropic', 'google']
    if (provider !== undefined && provider !== null && provider !== '' && !validProviders.includes(provider.toLowerCase())) {
      return NextResponse.json(
        { error: `Invalid provider. Must be one of: ${validProviders.join(', ')}` },
        { status: 400 }
      )
    }

    // Validate model if provided
    if (model && typeof model !== 'string') {
      return NextResponse.json(
        { error: 'Model must be a string' },
        { status: 400 }
      )
    }

    // Update user's LLM settings
    const updateData: any = {}
    if (provider !== undefined) {
      updateData.llmProvider = provider || null
    }
    if (apiKey !== undefined) {
      // In production, you should encrypt this before storing
      updateData.llmApiKey = apiKey || null
    }
    if (model !== undefined) {
      updateData.llmModel = model || null
    }

    const user = await prisma.user.update({
      where: { id: parseInt(userId) },
      data: updateData,
      select: {
        llmProvider: true,
        llmModel: true,
      },
    })

    return NextResponse.json({
      success: true,
      provider: user.llmProvider,
      model: user.llmModel,
    })
  } catch (error) {
    console.error('Update LLM settings error:', error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal server error' },
      { status: 500 }
    )
  }
}

