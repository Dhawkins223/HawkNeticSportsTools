from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from app.config import settings
from app.security import hash_password


SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    full_name TEXT NOT NULL,
    company TEXT,
    role TEXT NOT NULL DEFAULT 'customer',
    marketing_opt_in INTEGER NOT NULL DEFAULT 0,
    ai_opt_in INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL,
    full_name TEXT,
    company TEXT,
    use_case TEXT,
    source_page TEXT NOT NULL DEFAULT '/',
    consent_marketing INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS plans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    price_cents INTEGER NOT NULL,
    monthly_reports INTEGER NOT NULL,
    seats INTEGER NOT NULL,
    feature_summary TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    plan_id INTEGER NOT NULL,
    provider TEXT NOT NULL DEFAULT 'local',
    external_subscription_id TEXT,
    external_customer_id TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    current_period_start TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    current_period_end TEXT,
    cancel_at_period_end INTEGER NOT NULL DEFAULT 0,
    canceled_at TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(plan_id) REFERENCES plans(id)
);

CREATE TABLE IF NOT EXISTS payments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    subscription_id INTEGER,
    provider TEXT NOT NULL DEFAULT 'local',
    amount_cents INTEGER NOT NULL,
    currency TEXT NOT NULL DEFAULT 'USD',
    status TEXT NOT NULL DEFAULT 'paid',
    external_payment_id TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(subscription_id) REFERENCES subscriptions(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT 'New conversation',
    provider TEXT NOT NULL DEFAULT 'openai',
    model TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(conversation_id) REFERENCES ai_conversations(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS feature_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS provider_sync_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider TEXT NOT NULL,
    resource TEXT NOT NULL,
    status TEXT NOT NULL,
    records_written INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    error_text TEXT
);

-- RAW BALLDONTLIE AREA. These tables preserve provider structure and payloads.
CREATE TABLE IF NOT EXISTS raw_balldontlie_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_team_id INTEGER NOT NULL UNIQUE,
    conference TEXT,
    division TEXT,
    city TEXT,
    name TEXT,
    full_name TEXT,
    abbreviation TEXT,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS raw_balldontlie_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_player_id INTEGER NOT NULL UNIQUE,
    first_name TEXT,
    last_name TEXT,
    position TEXT,
    height TEXT,
    weight TEXT,
    jersey_number TEXT,
    college TEXT,
    country TEXT,
    draft_year INTEGER,
    draft_round INTEGER,
    draft_number INTEGER,
    provider_team_id INTEGER,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS raw_balldontlie_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_game_id INTEGER NOT NULL UNIQUE,
    game_date TEXT,
    season INTEGER,
    status TEXT,
    period INTEGER,
    time_text TEXT,
    postseason INTEGER NOT NULL DEFAULT 0,
    postponed INTEGER NOT NULL DEFAULT 0,
    home_team_score INTEGER,
    visitor_team_score INTEGER,
    home_team_id INTEGER,
    visitor_team_id INTEGER,
    datetime_utc TEXT,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- CANONICAL HAWKNETIC AREA. The algorithm reads from these tables, not provider shape.
CREATE TABLE IF NOT EXISTS canonical_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_provider TEXT NOT NULL,
    source_team_id INTEGER NOT NULL,
    conference TEXT,
    division TEXT,
    city TEXT,
    name TEXT,
    full_name TEXT,
    abbreviation TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_provider, source_team_id)
);

CREATE TABLE IF NOT EXISTS canonical_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_provider TEXT NOT NULL,
    source_player_id INTEGER NOT NULL,
    first_name TEXT,
    last_name TEXT,
    full_name TEXT,
    position TEXT,
    height TEXT,
    weight TEXT,
    jersey_number TEXT,
    college TEXT,
    country TEXT,
    draft_year INTEGER,
    draft_round INTEGER,
    draft_number INTEGER,
    canonical_team_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(canonical_team_id) REFERENCES canonical_teams(id) ON DELETE SET NULL,
    UNIQUE(source_provider, source_player_id)
);

CREATE TABLE IF NOT EXISTS canonical_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_provider TEXT NOT NULL,
    source_game_id INTEGER NOT NULL,
    game_date TEXT,
    season INTEGER,
    status TEXT,
    period INTEGER,
    time_text TEXT,
    postseason INTEGER NOT NULL DEFAULT 0,
    postponed INTEGER NOT NULL DEFAULT 0,
    home_team_score INTEGER,
    visitor_team_score INTEGER,
    home_canonical_team_id INTEGER,
    visitor_canonical_team_id INTEGER,
    datetime_utc TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY(home_canonical_team_id) REFERENCES canonical_teams(id) ON DELETE SET NULL,
    FOREIGN KEY(visitor_canonical_team_id) REFERENCES canonical_teams(id) ON DELETE SET NULL,
    UNIQUE(source_provider, source_game_id)
);

CREATE INDEX IF NOT EXISTS idx_raw_bdl_players_team ON raw_balldontlie_players(provider_team_id);
CREATE INDEX IF NOT EXISTS idx_raw_bdl_games_date ON raw_balldontlie_games(game_date);
CREATE INDEX IF NOT EXISTS idx_canonical_players_team ON canonical_players(canonical_team_id);
CREATE INDEX IF NOT EXISTS idx_canonical_games_date ON canonical_games(game_date);
"""


PLAN_SEEDS = [
    ("starter", "Starter", 999, 20, 1, "Clean daily card, limited AI explanations, account dashboard"),
    ("pro", "Pro", 1999, 200, 3, "Live board tracking, AI findings breakdowns, subscription export"),
    ("elite", "Elite", 4999, 9999, 10, "Full research layer, team seats, premium HawkNetic workflows"),
]

FREE_ACCESS_ACCOUNT = {
    "email": "free@hawknetic.local",
    "password": "free-access",
    "full_name": "Free Access User",
    "company": "HawkNetic",
}


def database_exists() -> bool:
    return Path(settings.database_path).exists()


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(settings.database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        yield connection
        connection.commit()
    finally:
        connection.close()


def init_db() -> None:
    with get_connection() as conn:
        conn.executescript(SCHEMA_SQL)
        conn.executemany(
            """
            INSERT INTO plans(code, name, price_cents, monthly_reports, seats, feature_summary)
            VALUES(?, ?, ?, ?, ?, ?)
            ON CONFLICT(code) DO UPDATE SET
                name=excluded.name,
                price_cents=excluded.price_cents,
                monthly_reports=excluded.monthly_reports,
                seats=excluded.seats,
                feature_summary=excluded.feature_summary,
                active=1
            """,
            PLAN_SEEDS,
        )
        conn.execute(
            """
            INSERT INTO users(email, password_hash, full_name, company, role, marketing_opt_in, ai_opt_in)
            VALUES(?, ?, ?, ?, 'customer', 0, 1)
            ON CONFLICT(email) DO UPDATE SET
                password_hash=excluded.password_hash,
                full_name=excluded.full_name,
                company=excluded.company,
                role=excluded.role,
                ai_opt_in=excluded.ai_opt_in,
                updated_at=CURRENT_TIMESTAMP
            """,
            (
                FREE_ACCESS_ACCOUNT["email"],
                hash_password(FREE_ACCESS_ACCOUNT["password"]),
                FREE_ACCESS_ACCOUNT["full_name"],
                FREE_ACCESS_ACCOUNT["company"],
            ),
        )


def reset_db() -> None:
    path = Path(settings.database_path)
    if path.exists():
        path.unlink()
    init_db()
