# LLM Chat & Historical Data Setup

## Overview

This application now includes:
1. **Historical Data Storage**: Automatically tracks changes to odds, player baselines, injuries, and game results over time
2. **LLM Chat Interface**: AI-powered chat assistant that can answer questions about NBA data using OpenAI
3. **Data Import/Export**: Import and export data in JSON or CSV formats

## Setup Instructions

### 1. OpenAI API Key

To use the LLM chat feature, you need to add your OpenAI API key to your `.env` file:

```env
OPENAI_API_KEY=your_openai_api_key_here
```

**How to get an OpenAI API key:**
1. Go to https://platform.openai.com/
2. Sign up or log in
3. Navigate to API Keys section
4. Create a new API key
5. Copy the key and add it to your `.env` file

**Note:** The chat feature uses `gpt-4o-mini` model which is cost-effective. You'll be charged based on OpenAI's pricing.

### 2. Historical Data

Historical data is automatically stored when:
- Odds are updated (snapshots stored in `HistoricalOddsSnapshot`)
- Player baselines are updated (snapshots stored in `HistoricalBaselineSnapshot`)
- Injuries are updated (snapshots stored in `HistoricalInjurySnapshot`)
- Games are completed (results stored in `GameResult`)

The sync process now includes historical data collection. Run the sync endpoint to start collecting historical data.

### 3. Database Migration

The database schema has been updated with new tables. If you haven't run the migration yet:

```bash
npx prisma migrate dev
npx prisma generate
```

## Features

### LLM Chat (`/chat`)

- Ask questions about NBA games, players, odds, and historical trends
- The AI has access to your database and can provide context-aware answers
- Chat history is saved per user
- Supports multiple concurrent conversations

**Example questions:**
- "What are the upcoming games?"
- "Show me player stats for LeBron James"
- "What are the current betting odds?"
- "Show me historical odds trends for Lakers games"

### Data Import/Export (`/data`)

**Export:**
- Export data in JSON or CSV format
- Choose specific data types (games, players, odds, historical) or export all
- Downloads automatically to your computer

**Import:**
- Import data from JSON files
- Data is validated and processed
- Import history is tracked in the database

### Historical Data Queries

You can query historical data through:
1. The LLM chat interface (ask about trends)
2. Direct database queries
3. API endpoints (coming soon)

## API Endpoints

### Chat
- `POST /api/llm/chat` - Send a message and get AI response
- `GET /api/llm/chats` - Get user's chat history
- `GET /api/llm/chats/[id]` - Get messages for a specific chat

### Data
- `GET /api/data/export?format=json&type=all` - Export data
- `POST /api/data/import` - Import data (multipart/form-data with file)

## Database Models

### Historical Data Models
- `GameResult` - Final scores and game outcomes
- `HistoricalOddsSnapshot` - Historical odds data
- `HistoricalBaselineSnapshot` - Historical player baseline data
- `HistoricalInjurySnapshot` - Historical injury data

### Chat Models
- `Chat` - User chat sessions
- `Message` - Individual messages in chats

### Import/Export
- `DataImport` - Tracks data import operations

## Notes

- Historical snapshots are created automatically during sync operations
- The LLM uses keyword matching to determine which data to fetch for context
- Chat responses are limited to 1000 tokens to control costs
- Historical data grows over time - consider archiving old data periodically

