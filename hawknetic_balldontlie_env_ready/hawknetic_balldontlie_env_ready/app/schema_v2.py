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
- slip_results          history of every saved-slip Monte Carlo run
- usage_limits          per-user/per-day usage counters for plan gating
- rate_limits           per-bucket counters (auth/algorithm)
- payment_transactions  Stripe Checkout sessions + status

Dialect-aware: works against both SQLite (local) and Railway PostgreSQL (prod).
"""
from __future__ import annotations

from typing import Any

from app.database import _column_exists, _using_postgres, execute


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

CREATE TABLE IF NOT EXISTS slip_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slip_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    sport TEXT,
    result_json TEXT NOT NULL,
    classification TEXT,
    recommended_action TEXT,
    parlay_probability REAL,
    parlay_ev REAL,
    confidence_score REAL,
    simulation_runs INTEGER,
    blocked INTEGER NOT NULL DEFAULT 0,
    blocking_reasons TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS usage_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    date TEXT NOT NULL,
    slip_runs_used INTEGER NOT NULL DEFAULT 0,
    max_slip_runs INTEGER NOT NULL DEFAULT 3,
    plan TEXT NOT NULL DEFAULT 'free',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(user_id, date)
);

CREATE TABLE IF NOT EXISTS rate_limits (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bucket TEXT NOT NULL,
    counter INTEGER NOT NULL DEFAULT 0,
    window_start TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bucket)
);

CREATE TABLE IF NOT EXISTS payment_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    user_email TEXT,
    session_id TEXT NOT NULL UNIQUE,
    amount REAL,
    currency TEXT NOT NULL DEFAULT 'usd',
    plan_name TEXT,
    payment_status TEXT NOT NULL DEFAULT 'pending',
    metadata TEXT,
    stripe_subscription_id TEXT,
    stripe_invoice_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


def _adapt_v2_ddl(statement: str) -> str:
    """SQLite DDL → PostgreSQL DDL. Idempotent for SQLite."""
    if not _using_postgres():
        return statement
    return statement.replace(
        "INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY"
    )


def apply_v2_schema(conn: Any) -> None:
    for statement in [s.strip() for s in SCHEMA_V2_SQL.split(";") if s.strip()]:
        execute(conn, _adapt_v2_ddl(statement))
    # Add missing columns to existing tables (idempotent — dialect-aware).
    _ensure_user_billing_columns(conn)


def _add_column_if_missing(conn: Any, table: str, column: str, definition: str) -> None:
    if _column_exists(conn, table, column):
        return
    execute(conn, f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_user_billing_columns(conn: Any) -> None:
    user_additions = [
        ("plan", "TEXT NOT NULL DEFAULT 'free'"),
        ("subscription_status", "TEXT"),
        ("stripe_customer_id", "TEXT"),
        ("stripe_subscription_id", "TEXT"),
    ]
    for col, defn in user_additions:
        _add_column_if_missing(conn, "users", col, defn)
    sub_additions = [
        ("stripe_customer_id", "TEXT"),
        ("stripe_subscription_id", "TEXT"),
        ("plan_name", "TEXT"),
    ]
    for col, defn in sub_additions:
        _add_column_if_missing(conn, "subscriptions", col, defn)
    leg_additions = [
        ("market_type", "TEXT"),
        ("line", "REAL"),
        ("game_id", "TEXT"),
        ("player_id", "TEXT"),
        ("team_id", "TEXT"),
        ("notes", "TEXT"),
    ]
    for col, defn in leg_additions:
        _add_column_if_missing(conn, "parlay_legs", col, defn)
    pay_additions = [
        ("stripe_invoice_id", "TEXT"),
        ("amount", "REAL"),
        ("paid_at", "TEXT"),
    ]
    for col, defn in pay_additions:
        _add_column_if_missing(conn, "payments", col, defn)
    parlay_additions = [
        ("sport", "TEXT"),
    ]
    for col, defn in parlay_additions:
        _add_column_if_missing(conn, "parlays", col, defn)
