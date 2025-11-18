// lib/llm/chatService.ts

import { prisma } from '@/lib/db'
import { isDataRequest, processLLMDataResponse } from './dataParser'

const OPENAI_API_KEY = process.env.OPENAI_API_KEY
const OPENAI_API_URL = 'https://api.openai.com/v1/chat/completions'
const ANTHROPIC_API_URL = 'https://api.anthropic.com/v1/messages'
const GOOGLE_API_BASE_URL = 'https://generativelanguage.googleapis.com/v1beta'

interface DatabaseContext {
  games?: any[]
  players?: any[]
  teams?: any[]
  odds?: any[]
  stats?: any[]
  historicalData?: any[]
}

/**
 * Query database to get relevant context for LLM
 */
async function getDatabaseContext(query: string): Promise<DatabaseContext> {
  const context: DatabaseContext = {}

  // Simple keyword matching to determine what data to fetch
  const lowerQuery = query.toLowerCase()

  // Extract potential team names, player names, dates, etc.
  if (lowerQuery.includes('game') || lowerQuery.includes('match')) {
    const games = await prisma.game.findMany({
      take: 10,
      orderBy: { date: 'desc' },
      include: {
        homeTeam: true,
        awayTeam: true,
        result: true,
      },
    })
    context.games = games
  }

  if (lowerQuery.includes('player') || lowerQuery.includes('stat')) {
    const players = await prisma.player.findMany({
      take: 20,
      include: {
        team: true,
        stats: {
          take: 5,
          orderBy: { createdAt: 'desc' },
        },
      },
    })
    context.players = players
  }

  if (lowerQuery.includes('team')) {
    const teams = await prisma.team.findMany({
      include: {
        players: {
          take: 5,
        },
      },
    })
    context.teams = teams
  }

  if (lowerQuery.includes('odd') || lowerQuery.includes('bet') || lowerQuery.includes('line')) {
    const odds = await prisma.gameOdds.findMany({
      take: 20,
      orderBy: { createdAt: 'desc' },
      include: {
        game: {
          include: {
            homeTeam: true,
            awayTeam: true,
          },
        },
      },
    })
    context.odds = odds
  }

  if (lowerQuery.includes('historical') || lowerQuery.includes('history') || lowerQuery.includes('trend')) {
    const historicalOdds = await prisma.historicalOddsSnapshot.findMany({
      take: 50,
      orderBy: { snapshotTime: 'desc' },
      include: {
        game: {
          include: {
            homeTeam: true,
            awayTeam: true,
          },
        },
      },
    })
    context.historicalData = historicalOdds
  }

  return context
}

/**
 * Format database context into a readable string for LLM
 */
function formatContextForLLM(context: DatabaseContext): string {
  let formatted = 'Database Context:\n\n'

  if (context.games && context.games.length > 0) {
    formatted += 'Recent Games:\n'
    context.games.slice(0, 5).forEach((game: any) => {
      formatted += `- ${game.awayTeam.name} @ ${game.homeTeam.name} on ${game.date.toLocaleDateString()} (Status: ${game.status})\n`
      if (game.result) {
        formatted += `  Final Score: ${game.awayTeam.name} ${game.result.awayScore} - ${game.result.homeScore} ${game.homeTeam.name}\n`
      }
    })
    formatted += '\n'
  }

  if (context.players && context.players.length > 0) {
    formatted += 'Players:\n'
    context.players.slice(0, 10).forEach((player: any) => {
      formatted += `- ${player.name} (${player.team.abbr})\n`
      if (player.stats && player.stats.length > 0) {
        const latest = player.stats[0]
        formatted += `  Latest: ${latest.points} pts, ${latest.rebounds} reb, ${latest.assists} ast\n`
      }
    })
    formatted += '\n'
  }

  if (context.teams && context.teams.length > 0) {
    formatted += 'Teams:\n'
    context.teams.forEach((team: any) => {
      formatted += `- ${team.name} (${team.abbr}) - ${team.players.length} players\n`
    })
    formatted += '\n'
  }

  if (context.odds && context.odds.length > 0) {
    formatted += 'Recent Odds:\n'
    context.odds.slice(0, 10).forEach((odd: any) => {
      formatted += `- ${odd.game.awayTeam.name} @ ${odd.game.homeTeam.name}: ${odd.bookmaker}\n`
      if (odd.spreadHome) formatted += `  Spread: ${odd.spreadHome} (${odd.spreadHomeOdds})\n`
      if (odd.total) formatted += `  Total: ${odd.total} (O: ${odd.overOdds}, U: ${odd.underOdds})\n`
    })
    formatted += '\n'
  }

  if (context.historicalData && context.historicalData.length > 0) {
    formatted += 'Historical Odds Trends:\n'
    const grouped = new Map<string, any[]>()
    context.historicalData.forEach((snapshot: any) => {
      const key = `${snapshot.game.homeTeam.name} vs ${snapshot.game.awayTeam.name} - ${snapshot.bookmaker}`
      if (!grouped.has(key)) grouped.set(key, [])
      grouped.get(key)!.push(snapshot)
    })
    grouped.forEach((snapshots, key) => {
      formatted += `- ${key}: ${snapshots.length} snapshots\n`
    })
    formatted += '\n'
  }

  return formatted
}

/**
 * Call LLM API based on provider
 */
async function callLLM(
  provider: string,
  apiKey: string,
  model: string,
  messages: Array<{ role: string; content: string }>
): Promise<string> {
  const systemMessage = `You are a helpful assistant for an NBA betting analytics dashboard. 
You help users understand NBA game data, player statistics, betting odds, and historical trends.
You have access to a database with games, players, teams, odds, and historical data.

IMPORTANT: When users ask you to add, create, or provide data (games, players, odds, stats, injuries, baselines), 
you MUST respond with valid JSON in the following format:

For games:
{
  "homeTeam": "Los Angeles Lakers",
  "awayTeam": "Golden State Warriors",
  "date": "2024-11-20T19:00:00Z",
  "venue": "Crypto.com Arena",
  "status": "scheduled",
  "odds": {
    "bookmaker": "DraftKings",
    "spreadHome": -4.5,
    "spreadAway": 4.5,
    "total": 225.5,
    "overOdds": -110,
    "underOdds": -110,
    "mlHome": -180,
    "mlAway": 150
  },
  "players": [
    {
      "name": "LeBron James",
      "team": "Lakers",
      "stats": {
        "points": 25,
        "rebounds": 8,
        "assists": 7,
        "threes": 2,
        "minutes": 35
      }
    }
  ]
}

For players with baselines:
{
  "name": "Stephen Curry",
  "team": "Warriors",
  "baselines": [
    {
      "market": "points",
      "mean": 27.3,
      "stdev": 5.8,
      "minutes": 34.5,
      "usageRate": 0.31
    }
  ]
}

For injuries:
{
  "playerName": "Anthony Davis",
  "team": "Lakers",
  "status": "Questionable",
  "note": "Knee soreness"
}

Wrap your JSON response in \`\`\`json code blocks. Be concise, accurate, and helpful. If you don't know something, say so.`

  switch (provider.toLowerCase()) {
    case 'openai':
      return callOpenAI(apiKey, model, messages, systemMessage)
    case 'anthropic':
      return callAnthropic(apiKey, model, messages, systemMessage)
    case 'google':
      return callGoogle(apiKey, model, messages, systemMessage)
    default:
      throw new Error(`Unsupported LLM provider: ${provider}`)
  }
}

/**
 * Call OpenAI API
 */
async function callOpenAI(
  apiKey: string,
  model: string,
  messages: Array<{ role: string; content: string }>,
  systemMessage: string
): Promise<string> {
  const response = await fetch(OPENAI_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${apiKey}`,
    },
    body: JSON.stringify({
      model: model || 'gpt-4o-mini',
      messages: [
        {
          role: 'system',
          content: systemMessage,
        },
        ...messages,
      ],
      temperature: 0.7,
      max_tokens: 1000,
    }),
  })

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`OpenAI API error: ${error}`)
  }

  const data = await response.json()
  return data.choices[0]?.message?.content || 'No response generated'
}

/**
 * Call Anthropic (Claude) API
 */
async function callAnthropic(
  apiKey: string,
  model: string,
  messages: Array<{ role: string; content: string }>,
  systemMessage: string
): Promise<string> {
  // Convert messages format for Anthropic
  const anthropicMessages = messages.map((msg) => ({
    role: msg.role === 'assistant' ? 'assistant' : 'user',
    content: msg.content,
  }))

  const response = await fetch(ANTHROPIC_API_URL, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'x-api-key': apiKey,
      'anthropic-version': '2023-06-01',
    },
    body: JSON.stringify({
      model: model || 'claude-3-haiku-20240307',
      max_tokens: 1000,
      system: systemMessage,
      messages: anthropicMessages,
    }),
  })

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Anthropic API error: ${error}`)
  }

  const data = await response.json()
  return data.content[0]?.text || 'No response generated'
}

/**
 * Call Google (Gemini) API
 */
async function callGoogle(
  apiKey: string,
  model: string,
  messages: Array<{ role: string; content: string }>,
  systemMessage: string
): Promise<string> {
  // Convert messages format for Google
  const googleMessages = messages.map((msg) => ({
    role: msg.role === 'assistant' ? 'model' : 'user',
    parts: [{ text: msg.content }],
  }))

  const modelName = model || 'gemini-pro'
  const response = await fetch(
    `${GOOGLE_API_BASE_URL}/models/${modelName}:generateContent?key=${apiKey}`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        contents: googleMessages,
        systemInstruction: {
          parts: [{ text: systemMessage }],
        },
        generationConfig: {
          temperature: 0.7,
          maxOutputTokens: 1000,
        },
      }),
    }
  )

  if (!response.ok) {
    const error = await response.text()
    throw new Error(`Google API error: ${error}`)
  }

  const data = await response.json()
  return data.candidates[0]?.content?.parts[0]?.text || 'No response generated'
}

/**
 * Process a user message and generate a response
 */
export async function processChatMessage(
  userId: number,
  chatId: number | null,
  userMessage: string
): Promise<{ chatId: number; response: string }> {
  // Get or create chat
  let chat
  if (chatId) {
    chat = await prisma.chat.findUnique({
      where: { id: chatId },
      include: { messages: { orderBy: { createdAt: 'asc' } } },
    })
  }

  if (!chat) {
    // Create new chat with title from first message
    const title = userMessage.slice(0, 50) + (userMessage.length > 50 ? '...' : '')
    chat = await prisma.chat.create({
      data: {
        userId,
        title,
        messages: {
          create: {
            role: 'user',
            content: userMessage,
          },
        },
      },
      include: { messages: true },
    })
  } else {
    // Add user message to existing chat
    await prisma.message.create({
      data: {
        chatId: chat.id,
        role: 'user',
        content: userMessage,
      },
    })
  }

  // Get database context based on query
  const context = await getDatabaseContext(userMessage)
  const contextString = formatContextForLLM(context)

  // Build message history for LLM
  const messages = chat.messages.map((msg) => ({
    role: msg.role,
    content: msg.content,
  }))

  // Add context to the latest user message
  const enhancedUserMessage = contextString + '\n\nUser Question: ' + userMessage

  // Get user's LLM settings
  const user = await prisma.user.findUnique({
    where: { id: userId },
    select: {
      llmProvider: true,
      llmApiKey: true,
      llmModel: true,
    },
  })

  // Determine which API key and provider to use
  const provider = user?.llmProvider || 'openai'
  const apiKey = user?.llmApiKey || OPENAI_API_KEY || ''
  const model = user?.llmModel || (provider === 'openai' ? 'gpt-4o-mini' : provider === 'anthropic' ? 'claude-3-haiku-20240307' : 'gemini-pro')

  if (!apiKey) {
    throw new Error('LLM API key is not configured. Please set your API key in settings.')
  }

  // Check if this is a data request
  const isDataReq = isDataRequest(userMessage)

  // Generate response using user's provider or default
  const assistantResponse = await callLLM(
    provider,
    apiKey,
    model,
    [
      ...messages.slice(0, -1), // All previous messages
      { role: 'user', content: enhancedUserMessage }, // Enhanced latest message
    ]
  )

  // If this was a data request, try to extract and store data
  let dataStorageResult = null
  if (isDataReq) {
    try {
      dataStorageResult = await processLLMDataResponse(assistantResponse, userMessage)
    } catch (error) {
      console.error('Error processing LLM data:', error)
    }
  }

  // Enhance response with data storage confirmation
  let finalResponse = assistantResponse
  if (dataStorageResult?.stored) {
    finalResponse += `\n\n✅ **Data Stored**: ${dataStorageResult.message}`
  } else if (isDataReq && !dataStorageResult?.stored) {
    finalResponse += `\n\n⚠️ **Note**: Could not automatically store data. Please provide data in JSON format or use the Data Import page.`
  }

  // Save assistant response
  await prisma.message.create({
    data: {
      chatId: chat.id,
      role: 'assistant',
      content: finalResponse,
      metadata: dataStorageResult ? JSON.stringify(dataStorageResult) : null,
    },
  })

  return {
    chatId: chat.id,
    response: finalResponse,
    dataStored: dataStorageResult?.stored || false,
    dataCount: dataStorageResult?.count || 0,
  }
}

/**
 * Get user's chat history
 */
export async function getUserChats(userId: number) {
  return prisma.chat.findMany({
    where: { userId },
    orderBy: { updatedAt: 'desc' },
    include: {
      messages: {
        orderBy: { createdAt: 'asc' },
        take: 1, // Just get first message for preview
      },
    },
  })
}

/**
 * Get chat messages
 */
export async function getChatMessages(chatId: number, userId: number) {
  const chat = await prisma.chat.findFirst({
    where: { id: chatId, userId },
    include: {
      messages: {
        orderBy: { createdAt: 'asc' },
      },
    },
  })

  return chat?.messages || []
}

