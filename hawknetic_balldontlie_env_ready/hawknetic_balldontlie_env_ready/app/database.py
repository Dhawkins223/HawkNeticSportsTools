from __future__ import annotations

import re
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
    return re.sub(r"\?", "%s", sql) if _using_postgres() else sql


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
        _seed_plans(conn)
        _seed_access_accounts(conn)
        _seed_historical_coverage_placeholders(conn)


def reset_db() -> None:
    if not _using_postgres() and Path(settings.database_path).exists():
        Path(settings.database_path).unlink()
    init_db()
