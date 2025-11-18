# Data Flow Documentation

## Overview

All sections of the application retrieve data from the database, which is updated by external APIs through the sync process.

## Data Flow Architecture

```
External APIs → Sync Process → Database → API Routes → Frontend Pages
```

### 1. External APIs (Data Sources)
- **NBA API (balldontlie.io)**: Games, player stats, injuries, baselines
- **The Odds API**: Betting odds, spreads, totals, moneyline

### 2. Sync Process (`/api/sync`)
The sync endpoint (`app/api/sync/route.ts`) orchestrates data updates from external APIs:

- **Games**: `syncTodayGames()` - Fetches today's NBA games
- **Odds**: `syncOddsSnapshots()` - Fetches current betting odds
- **Injuries**: `syncInjuries()` - Fetches player injury reports
- **Baselines**: `syncPlayerBaselines()` - Calculates player performance baselines
- **Historical Data**: `syncHistoricalGameResults()` - Stores completed game results

**Historical Data Storage:**
- Automatically stores snapshots when data is updated:
  - `storeHistoricalOddsSnapshot()` - When odds change
  - `storeHistoricalBaselineSnapshot()` - When baselines update
  - `storeHistoricalInjurySnapshot()` - When injuries change
  - `storeGameResult()` - When games complete

### 3. Database (Prisma + SQLite)
All data is stored in the database using Prisma ORM:

**Core Models:**
- `Game` - NBA games with teams, dates, status
- `Team` - NBA teams
- `Player` - NBA players with team associations
- `GameOdds` - Current betting odds
- `PropOdds` - Player prop betting lines
- `PlayerGameStats` - Historical game statistics
- `PlayerBaseline` - Player performance baselines
- `Injury` - Current injury status

**Historical Models:**
- `GameResult` - Final game scores and outcomes
- `HistoricalOddsSnapshot` - Historical odds changes
- `HistoricalBaselineSnapshot` - Historical baseline changes
- `HistoricalInjurySnapshot` - Historical injury records

### 4. API Routes (Database Queries)
All API routes query the database using Prisma:

#### `/api/nba/games`
- **Route**: `app/api/nba/games/route.ts`
- **Query**: Fetches games from database with teams, odds, and calculates market edges
- **Used by**: Games page, Props page, Tickets page

#### `/api/nba/games/[id]`
- **Route**: `app/api/nba/games/[id]/route.ts`
- **Query**: Fetches detailed game data including props, player ratings, injuries
- **Used by**: Game detail page, Props page

#### `/api/nba/teams/[id]`
- **Route**: `app/api/nba/teams/[id]/route.ts`
- **Query**: Fetches team details with players and stats
- **Used by**: Team detail views

#### `/api/nba/sgp/simulate`
- **Route**: `app/api/nba/sgp/simulate/route.ts`
- **Query**: Uses database data to run SGP simulations
- **Used by**: SGP composer

#### `/api/stats`
- **Route**: `app/api/stats/route.ts`
- **Query**: Returns database statistics (counts, recent games, last sync)
- **Used by**: About/Transparency page

#### `/api/data/export`
- **Route**: `app/api/data/export/route.ts`
- **Query**: Exports database data in JSON or CSV format
- **Used by**: Data page

#### `/api/data/import`
- **Route**: `app/api/data/import/route.ts`
- **Query**: Imports data into database
- **Used by**: Data page

#### `/api/llm/chat`
- **Route**: `app/api/llm/chat/route.ts`
- **Query**: Queries database for context based on user questions
- **Used by**: Chat page

### 5. Frontend Pages (API Consumers)
All pages fetch data from API routes (which query the database):

#### Games Page (`/games`)
- **API**: `getGames()` → `/api/nba/games`
- **API**: `getGameDetail()` → `/api/nba/games/[id]`
- **Data**: Game summaries, odds, market edges

#### Props Page (`/props`)
- **API**: `getGames()` → `/api/nba/games`
- **API**: `getGameDetail()` → `/api/nba/games/[id]`
- **Data**: Player props, odds, baselines

#### Tickets Page (`/tickets`)
- **API**: `getGames()` → `/api/nba/games`
- **Data**: Top EV markets across all games

#### Chat Page (`/chat`)
- **API**: `/api/llm/chat`
- **Data**: Database context for LLM queries

#### Data Page (`/data`)
- **API**: `/api/data/export` - Exports database data
- **API**: `/api/data/import` - Imports data to database

#### About/Transparency Page (`/about-model`)
- **API**: `/api/stats` - Shows database statistics
- **Data**: Live counts of games, players, odds, injuries, etc.

## Data Update Flow

1. **Manual Sync**: Admin calls `/api/sync` with `x-admin-token` header
2. **Sync Process**:
   - Fetches data from external APIs
   - Updates database using Prisma
   - Stores historical snapshots automatically
3. **Frontend Refresh**: Pages automatically refetch data via TanStack Query
4. **Real-time Updates**: Data is always fresh from the database

## Key Points

✅ **All sections use database data** - No hardcoded or mock data
✅ **Database updated by APIs** - External APIs → Sync → Database
✅ **Historical tracking** - All changes are stored as snapshots
✅ **API-first architecture** - Frontend → API Routes → Database
✅ **Automatic snapshots** - Historical data stored on every update

## Running a Sync

To update the database with latest data:

```bash
curl -X POST http://localhost:3000/api/sync \
  -H "x-admin-token: YOUR_ADMIN_TOKEN"
```

The sync process will:
1. Fetch games from NBA API
2. Fetch odds from The Odds API
3. Fetch injuries from NBA API
4. Calculate and store player baselines
5. Store historical snapshots automatically
6. Update game results for completed games

## Database Schema

See `prisma/schema.prisma` for the complete database schema including:
- Core data models (Games, Teams, Players, Odds, etc.)
- Historical data models (Snapshots, Results)
- Chat models (Chats, Messages)
- User models (Users, DataImports)

