import { NextRequest, NextResponse } from 'next/server'
import { getChatMessages } from '@/lib/llm/chatService'

export async function GET(
  request: NextRequest,
  { params }: { params: { id: string } }
) {
  try {
    const userId = request.cookies.get('user-id')?.value

    if (!userId) {
      return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })
    }

    const chatId = parseInt(params.id)
    const messages = await getChatMessages(chatId, parseInt(userId))

    return NextResponse.json({ messages })
  } catch (error) {
    console.error('Get chat messages error:', error)
    return NextResponse.json(
      { error: 'Internal server error' },
      { status: 500 }
    )
  }
}

