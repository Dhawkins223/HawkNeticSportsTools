import { NextRequest, NextResponse } from 'next/server'
import { processChatMessage } from '@/lib/llm/chatService'

export async function POST(request: NextRequest) {
  try {
    const userId = request.cookies.get('user-id')?.value

    if (!userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const { message, chatId } = await request.json()

    if (!message || typeof message !== 'string') {
      return NextResponse.json({ error: 'Message is required' }, { status: 400 })
    }

    const result = await processChatMessage(
      parseInt(userId),
      chatId ? parseInt(chatId) : null,
      message
    )

    return NextResponse.json(result)
  } catch (error) {
    console.error('Chat error:', error)
    return NextResponse.json(
      { error: error instanceof Error ? error.message : 'Internal server error' },
      { status: 500 }
    )
  }
}

