"""Schema additions for HawkNetic v2: live-data layer + projection inputs.

Idempotent. Run once at startup after `init_db()`. Adds tables that the
math-correct simulation engine and the live-data architecture need:

- player_skill          baseline per-player rates (mean, std, minutes, usage)
- team_metrics          baseline team off/def rating + pace
- live_games            fresh game state (status, score, period, clock)
- live_player_status    active/out/questionable/probable + minutes_restriction
- live_injuries         injury report rows
- live_odds             current odds snapshot per market
- live_line_movement    odds/line history per market
- live_data_snapshots   raw provider payloads (audit trail)
- predictions_outcomes  records every algorithm run for calibration / Brier
"""
from __future__ import annotations

from typing import Any

from app.database import execute


SCHEMA_V2_SQL = """
CREATE TABLE IF NOT EXISTS player_skill (
    player_id INTEGER PRIMARY KEY,
    minutes_mean REAL NOT NULL DEFAULT 0,
    minutes_std REAL NOT NULL DEFAULT 0,
    points_per_min_mean REAL NOT NULL DEFAULT 0,
    points_per_min_std REAL NOT NULL DEFAULT 0,
    rebounds_per_min_mean REAL NOT NULL DEFAULT 0,
    rebounds_per_min_std REAL NOT NULL DEFAULT 0,
    assists_per_min_mean REAL NOT NULL DEFAULT 0,
    assists_per_min_std REAL NOT NULL DEFAULT 0,
    threes_per_min_mean REAL NOT NULL DEFAULT 0,
    threes_per_min_std REAL NOT NULL DEFAULT 0,
    usage_rate REAL NOT NULL DEFAULT 0.20,
    availability REAL NOT NULL DEFAULT 0.95,
    sample_size INTEGER NOT NULL DEFAULT 0,
    last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS team_metrics (
    team_id INTEGER PRIMARY KEY,
    pace REAL NOT NULL DEFAULT 100,
    offensive_rating REAL NOT NULL DEFAULT 110,
    defensive_rating REAL NOT NULL DEFAULT 110,
    home_advantage REAL NOT NULL DEFAULT 2.5,
    last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_games (
    game_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'scheduled',
    period INTEGER,
    clock TEXT,
    home_score INTEGER,
    away_score INTEGER,
    home_team_id INTEGER,
    away_team_id INTEGER,
    tipoff_at TEXT,
    source TEXT NOT NULL DEFAULT 'manual',
    last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_player_status (
    player_id INTEGER NOT NULL,
    game_id INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    minutes_played REAL DEFAULT 0,
    minutes_restriction REAL,
    fouls INTEGER DEFAULT 0,
    points INTEGER DEFAULT 0,
    rebounds INTEGER DEFAULT 0,
    assists INTEGER DEFAULT 0,
    threes INTEGER DEFAULT 0,
    starter INTEGER DEFAULT 1,
    source TEXT NOT NULL DEFAULT 'manual',
    last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (player_id, game_id)
);

CREATE TABLE IF NOT EXISTS live_injuries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id INTEGER NOT NULL,
    designation TEXT NOT NULL,
    note TEXT,
    reported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    source TEXT NOT NULL DEFAULT 'manual'
);

CREATE TABLE IF NOT EXISTS live_odds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    american_odds INTEGER NOT NULL,
    sportsbook TEXT NOT NULL DEFAULT 'consensus',
    last_updated TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS live_line_movement (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER NOT NULL,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    line REAL,
    american_odds INTEGER NOT NULL,
    captured_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sportsbook TEXT NOT NULL DEFAULT 'consensus'
);

CREATE TABLE IF NOT EXISTS live_data_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS predictions_outcomes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slip_id TEXT NOT NULL,
    leg_id TEXT,
    predicted_probability REAL NOT NULL,
    bucket TEXT,
    actual_outcome INTEGER,
    market_type TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    settled_at TEXT
);
"""


def apply_v2_schema(conn: Any) -> None:
    for statement in [s.strip() for s in SCHEMA_V2_SQL.split(";") if s.strip()]:
        execute(conn, statement)
