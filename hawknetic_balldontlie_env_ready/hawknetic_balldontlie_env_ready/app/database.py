from __future__ import annotations

import re
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # local test fallback only
    psycopg = None
    dict_row = None

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
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
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
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS password_reset_tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    requested_email TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    expires_at TEXT NOT NULL,
    used_at TEXT,
    requester_ip TEXT,
    user_agent TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL DEFAULT 'New conversation',
    provider TEXT NOT NULL DEFAULT 'openai',
    model TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    token_count INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT,
    details TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS feature_findings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS historical_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT,
    abbreviation TEXT,
    city TEXT,
    name TEXT,
    full_name TEXT NOT NULL,
    conference TEXT,
    division TEXT,
    first_season INTEGER,
    last_season INTEGER,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(external_id)
);

CREATE TABLE IF NOT EXISTS historical_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT,
    first_name TEXT,
    last_name TEXT,
    full_name TEXT NOT NULL,
    position TEXT,
    height TEXT,
    weight TEXT,
    college TEXT,
    country TEXT,
    draft_year INTEGER,
    draft_round INTEGER,
    draft_number INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(external_id)
);

CREATE TABLE IF NOT EXISTS historical_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    external_id TEXT,
    season INTEGER NOT NULL,
    game_date TEXT,
    home_team_id INTEGER,
    away_team_id INTEGER,
    home_score INTEGER,
    away_score INTEGER,
    status TEXT,
    source TEXT NOT NULL DEFAULT 'hawknetic',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(external_id)
);

CREATE TABLE IF NOT EXISTS historical_player_game_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    game_id INTEGER,
    player_id INTEGER,
    team_id INTEGER,
    minutes REAL,
    points INTEGER,
    rebounds INTEGER,
    assists INTEGER,
    steals INTEGER,
    blocks INTEGER,
    turnovers INTEGER,
    made_threes INTEGER,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(game_id, player_id)
);

CREATE TABLE IF NOT EXISTS historical_team_game_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    game_id INTEGER,
    team_id INTEGER,
    opponent_team_id INTEGER,
    points INTEGER,
    rebounds INTEGER,
    assists INTEGER,
    pace REAL,
    offensive_rating REAL,
    defensive_rating REAL,
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(game_id, team_id)
);

CREATE TABLE IF NOT EXISTS historical_season_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id INTEGER NOT NULL,
    games_played INTEGER NOT NULL DEFAULT 0,
    stats_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(season, entity_type, entity_id)
);

CREATE TABLE IF NOT EXISTS historical_player_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    player_id INTEGER NOT NULL,
    rating_name TEXT NOT NULL,
    rating_value REAL NOT NULL,
    model_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(season, player_id, rating_name, model_version)
);

CREATE TABLE IF NOT EXISTS historical_team_ratings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season INTEGER NOT NULL,
    team_id INTEGER NOT NULL,
    rating_name TEXT NOT NULL,
    rating_value REAL NOT NULL,
    model_version TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(season, team_id, rating_name, model_version)
);

CREATE TABLE IF NOT EXISTS bdl_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bdl_team_id INTEGER NOT NULL UNIQUE,
    conference TEXT,
    division TEXT,
    city TEXT,
    name TEXT,
    full_name TEXT,
    abbreviation TEXT,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bdl_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bdl_player_id INTEGER NOT NULL UNIQUE,
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
    bdl_team_id INTEGER,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bdl_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bdl_game_id INTEGER NOT NULL UNIQUE,
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

CREATE TABLE IF NOT EXISTS bdl_player_game_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bdl_stat_id INTEGER UNIQUE,
    bdl_game_id INTEGER,
    bdl_player_id INTEGER,
    bdl_team_id INTEGER,
    stats_json TEXT NOT NULL DEFAULT '{}',
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bdl_team_game_stats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bdl_game_id INTEGER,
    bdl_team_id INTEGER,
    stats_json TEXT NOT NULL DEFAULT '{}',
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(bdl_game_id, bdl_team_id)
);

CREATE TABLE IF NOT EXISTS bdl_live_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bdl_game_id INTEGER NOT NULL,
    status TEXT,
    payload_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS bdl_ingestion_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    resource TEXT NOT NULL,
    status TEXT NOT NULL,
    records_read INTEGER NOT NULL DEFAULT 0,
    records_written INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT,
    error_text TEXT,
    request_json TEXT,
    response_excerpt TEXT
);

CREATE TABLE IF NOT EXISTS team_identity_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    historical_team_id INTEGER,
    bdl_team_id INTEGER,
    confidence REAL NOT NULL DEFAULT 0,
    mapping_source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(historical_team_id, bdl_team_id)
);

CREATE TABLE IF NOT EXISTS player_identity_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    historical_player_id INTEGER,
    bdl_player_id INTEGER,
    confidence REAL NOT NULL DEFAULT 0,
    mapping_source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(historical_player_id, bdl_player_id)
);

CREATE TABLE IF NOT EXISTS game_identity_map (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    historical_game_id INTEGER,
    bdl_game_id INTEGER,
    confidence REAL NOT NULL DEFAULT 0,
    mapping_source TEXT NOT NULL DEFAULT 'manual',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(historical_game_id, bdl_game_id)
);

CREATE TABLE IF NOT EXISTS odds (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER,
    sportsbook TEXT,
    market TEXT NOT NULL,
    selection TEXT NOT NULL,
    odds_value INTEGER,
    implied_probability REAL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(game_id, sportsbook, market, selection)
);

CREATE TABLE IF NOT EXISTS props (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER,
    player_id INTEGER,
    market TEXT NOT NULL,
    line REAL,
    over_odds INTEGER,
    under_odds INTEGER,
    model_probability REAL,
    expected_value REAL,
    confidence_tier TEXT,
    source TEXT NOT NULL DEFAULT 'model',
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS simulations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    game_id INTEGER,
    simulation_type TEXT NOT NULL DEFAULT 'game',
    runs INTEGER NOT NULL DEFAULT 1000,
    home_win_probability REAL,
    away_win_probability REAL,
    confidence REAL,
    result_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS simulation_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    simulation_id INTEGER NOT NULL,
    player_id INTEGER,
    projection_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parlays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    name TEXT NOT NULL DEFAULT 'Untitled Parlay',
    estimated_odds INTEGER,
    win_probability REAL,
    loss_probability REAL,
    expected_value REAL,
    risk_tier TEXT,
    confidence_tier TEXT,
    correlation_warning TEXT,
    trap_leg_warning TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS parlay_legs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    parlay_id INTEGER NOT NULL,
    prop_id INTEGER,
    leg_order INTEGER NOT NULL DEFAULT 0,
    label TEXT NOT NULL,
    odds_value INTEGER,
    probability REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS data_quality_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_type TEXT NOT NULL,
    season INTEGER,
    status TEXT NOT NULL,
    expected_records INTEGER NOT NULL DEFAULT 0,
    actual_records INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(report_type, season)
);
"""

PLAN_SEEDS = [
    ("free", "Free", 0, 5, 1, "Core dashboard access and starter HawkNetic reports"),
    ("starter", "Starter", 999, 20, 1, "Clean daily card, limited AI explanations, account dashboard"),
    ("pro", "Pro", 1999, 200, 3, "Live board tracking, AI findings breakdowns, subscription export"),
    ("elite", "Elite", 4999, 9999, 10, "Full research layer, team seats, premium HawkNetic workflows"),
]
FREE_ACCESS_ACCOUNT = {"email": "free@hawknetic.local", "password": "free-access", "full_name": "Free Access User", "company": "HawkNetic"}
TIMESTAMP_COLUMNS = (
    "created_at", "updated_at", "current_period_start", "current_period_end", "canceled_at",
    "expires_at", "used_at", "started_at", "completed_at", "fetched_at",
)


def _using_postgres() -> bool:
    return bool(settings.database_url)


def _adapt_sql(sql: str) -> str:
    if not _using_postgres():
        return sql
    sql = sql.replace("%", "%%")
    sql = sql.replace("?", "%s")
    return sql


def _postgres_schema_sql() -> str:
    schema = SCHEMA_SQL.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    schema = re.sub(r"^\s*PRAGMA\s+foreign_keys\s*=\s*ON;\s*", "", schema, flags=re.IGNORECASE | re.MULTILINE)
    for column in TIMESTAMP_COLUMNS:
        schema = re.sub(rf"\b{column}\s+TEXT\b", f"{column} TIMESTAMPTZ", schema)
    return schema


def _schema_sql() -> str:
    return _postgres_schema_sql() if _using_postgres() else SCHEMA_SQL


@contextmanager
def get_connection() -> Iterator[Any]:
    if not _using_postgres() and not settings.allow_sqlite_fallback:
        raise RuntimeError("DATABASE_URL is required. HawkNetic production uses Railway PostgreSQL only.")
    if _using_postgres():
        if psycopg is None:
            raise RuntimeError("psycopg is required when DATABASE_URL is set.")
        conn = psycopg.connect(settings.database_url, row_factory=dict_row)
    else:
        conn = sqlite3.connect(settings.database_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


class ExecuteResult:
    def __init__(self, cursor: Any, lastrowid: int | None = None) -> None:
        self._cursor = cursor
        self.lastrowid = lastrowid

    def __getattr__(self, name: str) -> Any:
        return getattr(self._cursor, name)


def _postgres_insert_needs_returning(sql: str) -> bool:
    normalized = sql.lstrip().upper()
    return normalized.startswith("INSERT INTO") and "ON CONFLICT" not in normalized and "RETURNING" not in normalized


def execute(conn: Any, sql: str, params: tuple | list = ()):
    adapted = _adapt_sql(sql)
    if _using_postgres() and _postgres_insert_needs_returning(adapted):
        cur = conn.execute(f"{adapted.strip()} RETURNING id", params)
        row = cur.fetchone()
        return ExecuteResult(cur, int(row["id"]) if row else None)
    return conn.execute(adapted, params)


def database_status() -> dict[str, Any]:
    try:
        with get_connection() as conn:
            execute(conn, "SELECT 1")
            if _using_postgres():
                table_count = execute(conn, "SELECT COUNT(*) AS count_value FROM information_schema.tables WHERE table_schema = 'public'").fetchone()["count_value"]
            else:
                table_count = execute(conn, "SELECT COUNT(*) AS count_value FROM sqlite_master WHERE type = 'table'").fetchone()["count_value"]
        return {"ok": True, "engine": "postgresql" if _using_postgres() else "sqlite-test-fallback", "railway_postgres": _using_postgres(), "table_count": int(table_count), "error": None}
    except Exception as exc:
        return {"ok": False, "engine": "postgresql" if _using_postgres() else "sqlite-test-fallback", "railway_postgres": _using_postgres(), "table_count": 0, "error": str(exc)}


SCHEMA_COLUMN_UPGRADES: dict[str, dict[str, str]] = {
    "historical_teams": {"team_key": "TEXT", "source": "TEXT", "conference": "TEXT", "division": "TEXT"},
    "historical_players": {"player_key": "TEXT", "birth_date": "TEXT", "first_season": "INTEGER", "last_season": "INTEGER", "active": "INTEGER", "source": "TEXT"},
    "historical_games": {"game_key": "TEXT", "away_team_key": "TEXT", "home_team_key": "TEXT", "away_score": "INTEGER", "source_url": "TEXT", "game_type": "TEXT", "attendance": "INTEGER", "arena": "TEXT", "notes": "TEXT", "overtime": "TEXT"},
    "historical_player_game_stats": {"game_key": "TEXT", "game_date": "TEXT", "player_key": "TEXT", "team_key": "TEXT", "opponent_team_key": "TEXT", "home_away": "TEXT", "starter": "INTEGER", "field_goals": "INTEGER", "field_goal_attempts": "INTEGER", "field_goal_pct": "REAL", "three_pointers": "INTEGER", "three_point_attempts": "INTEGER", "three_point_pct": "REAL", "free_throws": "INTEGER", "free_throw_attempts": "INTEGER", "free_throw_pct": "REAL", "offensive_rebounds": "INTEGER", "defensive_rebounds": "INTEGER", "personal_fouls": "INTEGER", "plus_minus": "REAL", "source": "TEXT"},
    "historical_team_game_stats": {"game_key": "TEXT", "game_date": "TEXT", "team_key": "TEXT", "opponent_team_key": "TEXT", "home_away": "TEXT", "minutes": "REAL", "field_goals": "INTEGER", "field_goal_attempts": "INTEGER", "field_goal_pct": "REAL", "three_pointers": "INTEGER", "three_point_attempts": "INTEGER", "three_point_pct": "REAL", "free_throws": "INTEGER", "free_throw_attempts": "INTEGER", "free_throw_pct": "REAL", "offensive_rebounds": "INTEGER", "defensive_rebounds": "INTEGER", "turnovers": "INTEGER", "personal_fouls": "INTEGER", "plus_minus": "REAL", "source": "TEXT"},
    "historical_season_stats": {"player_key": "TEXT", "team_key": "TEXT", "age": "INTEGER", "games_started": "INTEGER", "minutes": "REAL", "minutes_per_game": "REAL", "field_goals": "INTEGER", "field_goals_per_game": "REAL", "field_goal_attempts": "INTEGER", "field_goal_attempts_per_game": "REAL", "field_goal_pct": "REAL", "three_pointers": "INTEGER", "three_pointers_per_game": "REAL", "three_point_attempts": "INTEGER", "three_point_attempts_per_game": "REAL", "three_point_pct": "REAL", "two_pointers": "INTEGER", "two_pointers_per_game": "REAL", "two_point_attempts": "INTEGER", "two_point_attempts_per_game": "REAL", "two_point_pct": "REAL", "effective_fg_pct": "REAL", "free_throws": "INTEGER", "free_throws_per_game": "REAL", "free_throw_attempts": "INTEGER", "free_throw_attempts_per_game": "REAL", "free_throw_pct": "REAL", "offensive_rebounds": "INTEGER", "offensive_rebounds_per_game": "REAL", "defensive_rebounds": "INTEGER", "defensive_rebounds_per_game": "REAL", "rebounds": "INTEGER", "rebounds_per_game": "REAL", "assists": "INTEGER", "assists_per_game": "REAL", "steals": "INTEGER", "steals_per_game": "REAL", "blocks": "INTEGER", "blocks_per_game": "REAL", "turnovers": "INTEGER", "turnovers_per_game": "REAL", "personal_fouls": "INTEGER", "personal_fouls_per_game": "REAL", "points": "INTEGER", "points_per_game": "REAL", "source": "TEXT"},
    "historical_player_ratings": {"player_key": "TEXT", "team_key": "TEXT", "age": "INTEGER", "games_played": "INTEGER", "minutes": "REAL", "player_efficiency_rating": "REAL", "true_shooting_pct": "REAL", "three_point_attempt_rate": "REAL", "free_throw_attempt_rate": "REAL", "offensive_rebound_pct": "REAL", "defensive_rebound_pct": "REAL", "total_rebound_pct": "REAL", "assist_pct": "REAL", "steal_pct": "REAL", "block_pct": "REAL", "turnover_pct": "REAL", "usage_rate": "REAL", "offensive_win_shares": "REAL", "defensive_win_shares": "REAL", "win_shares": "REAL", "win_shares_per_48": "REAL", "offensive_box_plus_minus": "REAL", "defensive_box_plus_minus": "REAL", "box_plus_minus": "REAL", "value_over_replacement_player": "REAL", "source": "TEXT"},
    "data_quality_reports": {"games_scraped": "INTEGER", "box_scores_scraped": "INTEGER", "players_scraped": "INTEGER", "teams_scraped": "INTEGER", "player_game_rows": "INTEGER", "team_game_rows": "INTEGER", "missing_box_scores": "INTEGER", "failed_urls": "INTEGER", "coverage_percent": "REAL", "checked_at": "TEXT", "last_scrape_at": "TEXT", "last_import_at": "TEXT"},
}


def _column_exists(conn: Any, table: str, column: str) -> bool:
    if _using_postgres():
        row = conn.execute("SELECT 1 FROM information_schema.columns WHERE table_name = %s AND column_name = %s", (table, column)).fetchone()
        return row is not None
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(row["name"] == column for row in rows)


def _ensure_schema_upgrades(conn: Any) -> None:
    for table, columns in SCHEMA_COLUMN_UPGRADES.items():
        for column, column_type in columns.items():
            if not _column_exists(conn, table, column):
                execute(conn, f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")


SCHEMA_UNIQUE_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("plans_code_uidx", "plans", "code"),
    ("users_email_uidx", "users", "email"),
    ("data_quality_reports_report_type_season_uidx", "data_quality_reports", "report_type, season"),
    ("historical_teams_external_id_uidx", "historical_teams", "external_id"),
    ("historical_players_external_id_uidx", "historical_players", "external_id"),
    ("historical_games_external_id_uidx", "historical_games", "external_id"),
    ("bdl_teams_bdl_team_id_uidx", "bdl_teams", "bdl_team_id"),
    ("bdl_players_bdl_player_id_uidx", "bdl_players", "bdl_player_id"),
    ("bdl_games_bdl_game_id_uidx", "bdl_games", "bdl_game_id"),
)


def _dedupe_for_unique_indexes(conn: Any) -> None:
    if _using_postgres():
        execute(conn, """
            DELETE FROM data_quality_reports a
            USING data_quality_reports b
            WHERE a.ctid < b.ctid
              AND a.report_type = b.report_type
              AND COALESCE(a.season, -1) = COALESCE(b.season, -1)
        """)
    else:
        execute(conn, """
            DELETE FROM data_quality_reports
            WHERE rowid NOT IN (
                SELECT MAX(rowid)
                FROM data_quality_reports
                GROUP BY report_type, season
            )
        """)


def _ensure_unique_indexes(conn: Any) -> None:
    _dedupe_for_unique_indexes(conn)
    for index_name, table_name, columns in SCHEMA_UNIQUE_INDEXES:
        execute(conn, f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table_name}({columns})")


SCHEMA_PERF_INDEXES: tuple[tuple[str, str, str], ...] = (
    ("historical_games_season_idx", "historical_games", "season"),
    ("historical_games_game_date_idx", "historical_games", "game_date"),
    ("historical_player_game_stats_game_id_idx", "historical_player_game_stats", "game_id"),
    ("historical_player_game_stats_player_id_idx", "historical_player_game_stats", "player_id"),
    ("historical_team_game_stats_game_id_idx", "historical_team_game_stats", "game_id"),
    ("historical_team_game_stats_team_id_idx", "historical_team_game_stats", "team_id"),
    ("bdl_games_bdl_game_id_idx", "bdl_games", "bdl_game_id"),
    ("bdl_players_bdl_player_id_idx", "bdl_players", "bdl_player_id"),
    ("bdl_teams_bdl_team_id_idx", "bdl_teams", "bdl_team_id"),
    ("odds_game_id_idx", "odds", "game_id"),
    ("props_game_id_idx", "props", "game_id"),
    ("props_player_id_idx", "props", "player_id"),
    ("simulations_game_id_idx", "simulations", "game_id"),
    ("parlay_legs_parlay_id_idx", "parlay_legs", "parlay_id"),
    ("bdl_ingestion_logs_started_at_idx", "bdl_ingestion_logs", "started_at"),
)


def _ensure_perf_indexes(conn: Any) -> None:
    for index_name, table_name, columns in SCHEMA_PERF_INDEXES:
        execute(conn, f"CREATE INDEX IF NOT EXISTS {index_name} ON {table_name}({columns})")


def _seed_plans(conn: Any) -> None:
    for seed in PLAN_SEEDS:
        execute(conn, """
            INSERT INTO plans(code,name,price_cents,monthly_reports,seats,feature_summary,active)
            VALUES(?,?,?,?,?,?,1)
            ON CONFLICT(code) DO UPDATE SET
                name=excluded.name,
                price_cents=excluded.price_cents,
                monthly_reports=excluded.monthly_reports,
                seats=excluded.seats,
                feature_summary=excluded.feature_summary,
                active=excluded.active
        """, seed)


def _ensure_user(conn: Any, email: str, password: str, full_name: str, company: str, role: str = "customer", ai_opt_in: int = 1) -> int:
    normalized_email = email.lower().strip()
    existing = execute(conn, "SELECT id FROM users WHERE email = ?", (normalized_email,)).fetchone()
    if existing:
        user_id = int(existing["id"])
        execute(conn, "UPDATE users SET full_name = ?, company = ?, role = ?, ai_opt_in = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (full_name, company, role, ai_opt_in, user_id))
        return user_id
    cur = execute(conn, "INSERT INTO users(email,password_hash,full_name,company,role,marketing_opt_in,ai_opt_in) VALUES(?,?,?,?,?,0,?)", (normalized_email, hash_password(password), full_name, company, role, ai_opt_in))
    return int(cur.lastrowid)


def _seed_access_accounts(conn: Any) -> None:
    _ensure_user(conn, FREE_ACCESS_ACCOUNT["email"], FREE_ACCESS_ACCOUNT["password"], FREE_ACCESS_ACCOUNT["full_name"], FREE_ACCESS_ACCOUNT["company"])
    if not settings.beta_master_enabled:
        return
    user_id = _ensure_user(conn, settings.beta_master_email, settings.beta_master_password, "Beta Master Access", "HawkNetic Beta", role="admin", ai_opt_in=1)
    plan = execute(conn, "SELECT id, price_cents FROM plans WHERE code = ? AND active = 1", ((settings.beta_master_plan_code or "elite").lower().strip(),)).fetchone()
    if not plan:
        plan = execute(conn, "SELECT id, price_cents FROM plans WHERE code = 'elite' AND active = 1").fetchone()
    if not plan:
        return
    plan_id = int(plan["id"])
    active = execute(conn, "SELECT id FROM subscriptions WHERE user_id = ? AND plan_id = ? AND status = 'active'", (user_id, plan_id)).fetchone()
    if active:
        return
    execute(conn, "UPDATE subscriptions SET status = 'canceled', canceled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND status = 'active'", (user_id,))
    period_end = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
    cur = execute(conn, "INSERT INTO subscriptions(user_id, plan_id, provider, status, current_period_end) VALUES(?, ?, 'beta_seed', 'active', ?)", (user_id, plan_id, period_end))
    execute(conn, "INSERT INTO payments(user_id, subscription_id, provider, amount_cents, status) VALUES(?, ?, 'beta_seed', ?, 'paid')", (user_id, int(cur.lastrowid), int(plan["price_cents"])))


def _seed_historical_coverage_placeholders(conn: Any) -> None:
    for season in range(1996, 2027):
        game_count = execute(conn, "SELECT COUNT(*) AS c FROM historical_games WHERE season = ?", (season,)).fetchone()["c"]
        player_stat_count = execute(conn, "SELECT COUNT(*) AS c FROM historical_player_game_stats WHERE season = ?", (season,)).fetchone()["c"]
        status = "complete" if int(game_count) >= 1 and int(player_stat_count) >= 1 else "incomplete"
        execute(conn, """
            INSERT INTO data_quality_reports(report_type, season, status, expected_records, actual_records, details_json)
            VALUES('historical_season_coverage', ?, ?, 1, ?, ?)
            ON CONFLICT(report_type, season) DO UPDATE SET
                status=excluded.status,
                actual_records=excluded.actual_records,
                details_json=excluded.details_json,
                updated_at=CURRENT_TIMESTAMP
        """, (season, status, int(game_count), f'{{"games":{int(game_count)},"player_game_stats":{int(player_stat_count)}}}'))


def init_db() -> None:
    with get_connection() as conn:
        for stmt in [s.strip() for s in _schema_sql().split(";") if s.strip()]:
            execute(conn, stmt)
        _ensure_schema_upgrades(conn)
        _ensure_unique_indexes(conn)
        _ensure_perf_indexes(conn)
        _seed_plans(conn)
        _seed_access_accounts(conn)
        _seed_historical_coverage_placeholders(conn)


EXPECTED_TABLES: tuple[str, ...] = (
    "users", "leads", "plans", "subscriptions", "payments", "password_reset_tokens", "ai_conversations", "ai_messages",
    "audit_logs", "feature_findings", "historical_teams", "historical_players", "historical_games", "historical_player_game_stats",
    "historical_team_game_stats", "historical_season_stats", "historical_player_ratings", "historical_team_ratings", "bdl_teams",
    "bdl_players", "bdl_games", "bdl_player_game_stats", "bdl_team_game_stats", "bdl_live_games", "bdl_ingestion_logs",
    "team_identity_map", "player_identity_map", "game_identity_map", "odds", "props", "simulations", "simulation_players",
    "parlays", "parlay_legs", "data_quality_reports",
)


def table_exists(conn: Any, table_name: str) -> bool:
    if _using_postgres():
        row = execute(conn, "SELECT 1 AS ok FROM information_schema.tables WHERE table_schema = 'public' AND table_name = ?", (table_name,)).fetchone()
        return row is not None
    row = execute(conn, "SELECT 1 AS ok FROM sqlite_master WHERE type = 'table' AND name = ?", (table_name,)).fetchone()
    return row is not None


def database_readiness() -> dict[str, Any]:
    key_tables = (
        "historical_teams", "historical_players", "historical_games", "historical_player_game_stats", "historical_team_game_stats",
        "bdl_teams", "bdl_players", "bdl_games", "bdl_ingestion_logs", "odds", "props", "simulations", "parlays", "parlay_legs", "data_quality_reports",
    )
    with get_connection() as conn:
        if _using_postgres():
            table_rows = execute(conn, "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'").fetchall()
        else:
            table_rows = execute(conn, "SELECT name AS table_name FROM sqlite_master WHERE type = 'table'").fetchall()
        existing = {str(row["table_name"]) for row in table_rows}
        missing = [table for table in EXPECTED_TABLES if table not in existing]
        row_counts: dict[str, int | None] = {}
        for table in key_tables:
            if table in existing:
                row_counts[table] = int(execute(conn, f"SELECT COUNT(*) AS c FROM {table}").fetchone()["c"])
            else:
                row_counts[table] = None
    return {
        "engine": "postgresql" if _using_postgres() else "sqlite-test-fallback",
        "database_url_present": bool(settings.database_url),
        "table_count": len(existing),
        "missing_expected_tables": missing,
        "row_counts": row_counts,
    }


def reset_db() -> None:
    if not _using_postgres() and Path(settings.database_path).exists():
        Path(settings.database_path).unlink()
    init_db()
