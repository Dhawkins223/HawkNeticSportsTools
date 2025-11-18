-- CreateTable
CREATE TABLE "Team" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL,
    "abbr" TEXT NOT NULL
);

-- CreateTable
CREATE TABLE "Player" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "name" TEXT NOT NULL,
    "externalId" TEXT,
    "teamId" INTEGER NOT NULL,
    CONSTRAINT "Player_teamId_fkey" FOREIGN KEY ("teamId") REFERENCES "Team" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Game" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "externalId" TEXT NOT NULL,
    "date" DATETIME NOT NULL,
    "venue" TEXT,
    "status" TEXT NOT NULL,
    "homeTeamId" INTEGER NOT NULL,
    "awayTeamId" INTEGER NOT NULL,
    CONSTRAINT "Game_homeTeamId_fkey" FOREIGN KEY ("homeTeamId") REFERENCES "Team" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "Game_awayTeamId_fkey" FOREIGN KEY ("awayTeamId") REFERENCES "Team" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "GameOdds" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "gameId" INTEGER NOT NULL,
    "bookmaker" TEXT NOT NULL,
    "spreadHome" REAL,
    "spreadAway" REAL,
    "spreadHomeOdds" INTEGER,
    "spreadAwayOdds" INTEGER,
    "total" REAL,
    "overOdds" INTEGER,
    "underOdds" INTEGER,
    "mlHome" INTEGER,
    "mlAway" INTEGER,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "GameOdds_gameId_fkey" FOREIGN KEY ("gameId") REFERENCES "Game" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "PropOdds" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "gameId" INTEGER NOT NULL,
    "playerId" INTEGER NOT NULL,
    "market" TEXT NOT NULL,
    "line" REAL NOT NULL,
    "overOdds" INTEGER NOT NULL,
    "underOdds" INTEGER NOT NULL,
    "source" TEXT NOT NULL,
    "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PropOdds_gameId_fkey" FOREIGN KEY ("gameId") REFERENCES "Game" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "PropOdds_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "Player" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "PlayerGameStats" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "gameId" INTEGER NOT NULL,
    "playerId" INTEGER NOT NULL,
    "minutes" REAL NOT NULL,
    "points" REAL NOT NULL,
    "rebounds" REAL NOT NULL,
    "assists" REAL NOT NULL,
    "threes" REAL NOT NULL,
    "createdAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PlayerGameStats_gameId_fkey" FOREIGN KEY ("gameId") REFERENCES "Game" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "PlayerGameStats_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "Player" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "Injury" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "playerId" INTEGER NOT NULL,
    "teamId" INTEGER NOT NULL,
    "status" TEXT NOT NULL,
    "note" TEXT,
    "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "Injury_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "Player" ("id") ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT "Injury_teamId_fkey" FOREIGN KEY ("teamId") REFERENCES "Team" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateTable
CREATE TABLE "PlayerBaseline" (
    "id" INTEGER NOT NULL PRIMARY KEY AUTOINCREMENT,
    "playerId" INTEGER NOT NULL,
    "market" TEXT NOT NULL,
    "mean" REAL NOT NULL,
    "stdev" REAL NOT NULL,
    "minutes" REAL NOT NULL,
    "usageRate" REAL NOT NULL,
    "updatedAt" DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT "PlayerBaseline_playerId_fkey" FOREIGN KEY ("playerId") REFERENCES "Player" ("id") ON DELETE RESTRICT ON UPDATE CASCADE
);

-- CreateIndex
CREATE UNIQUE INDEX "Team_abbr_key" ON "Team"("abbr");

-- CreateIndex
CREATE UNIQUE INDEX "Player_externalId_key" ON "Player"("externalId");

-- CreateIndex
CREATE UNIQUE INDEX "Game_externalId_key" ON "Game"("externalId");

-- CreateIndex
CREATE INDEX "GameOdds_gameId_bookmaker_createdAt_idx" ON "GameOdds"("gameId", "bookmaker", "createdAt");

-- CreateIndex
CREATE INDEX "PropOdds_playerId_market_idx" ON "PropOdds"("playerId", "market");

-- CreateIndex
CREATE UNIQUE INDEX "PropOdds_gameId_playerId_market_source_key" ON "PropOdds"("gameId", "playerId", "market", "source");

-- CreateIndex
CREATE INDEX "PlayerGameStats_playerId_idx" ON "PlayerGameStats"("playerId");

-- CreateIndex
CREATE UNIQUE INDEX "PlayerGameStats_gameId_playerId_key" ON "PlayerGameStats"("gameId", "playerId");

-- CreateIndex
CREATE INDEX "Injury_teamId_idx" ON "Injury"("teamId");

-- CreateIndex
CREATE UNIQUE INDEX "Injury_playerId_key" ON "Injury"("playerId");

-- CreateIndex
CREATE UNIQUE INDEX "PlayerBaseline_playerId_market_key" ON "PlayerBaseline"("playerId", "market");
