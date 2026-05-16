from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:
    import psycopg
    from psycopg.rows import dict_row
except ModuleNotFoundError:  # local sqlite-only runs
    psycopg = None
    dict_row = None

from app.config import settings
from app.security import hash_password

SQLITE_SCHEMA_SQL = """
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

CREATE TABLE IF NOT EXISTS raw_balldontlie_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_team_id INTEGER NOT NULL UNIQUE,
    conference TEXT, division TEXT, city TEXT, name TEXT, full_name TEXT, abbreviation TEXT,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS raw_balldontlie_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_player_id INTEGER NOT NULL UNIQUE,
    first_name TEXT,last_name TEXT,position TEXT,height TEXT,weight TEXT,jersey_number TEXT,college TEXT,country TEXT,
    draft_year INTEGER,draft_round INTEGER,draft_number INTEGER,provider_team_id INTEGER,
    raw_json TEXT NOT NULL,
    fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS raw_balldontlie_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_game_id INTEGER NOT NULL UNIQUE,
    game_date TEXT,season INTEGER,status TEXT,period INTEGER,time_text TEXT,postseason INTEGER NOT NULL DEFAULT 0,
    postponed INTEGER NOT NULL DEFAULT 0,home_team_score INTEGER,visitor_team_score INTEGER,home_team_id INTEGER,
    visitor_team_id INTEGER,datetime_utc TEXT,raw_json TEXT NOT NULL,fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS canonical_teams (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_provider TEXT NOT NULL, source_team_id INTEGER NOT NULL,
    conference TEXT, division TEXT, city TEXT, name TEXT, full_name TEXT, abbreviation TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_provider, source_team_id)
);
CREATE TABLE IF NOT EXISTS canonical_players (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_provider TEXT NOT NULL, source_player_id INTEGER NOT NULL,
    first_name TEXT,last_name TEXT,full_name TEXT,position TEXT,height TEXT,weight TEXT,jersey_number TEXT,college TEXT,country TEXT,
    draft_year INTEGER,draft_round INTEGER,draft_number INTEGER,canonical_team_id INTEGER,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_provider, source_player_id)
);
CREATE TABLE IF NOT EXISTS canonical_games (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_provider TEXT NOT NULL, source_game_id INTEGER NOT NULL,
    game_date TEXT,season INTEGER,status TEXT,period INTEGER,time_text TEXT,postseason INTEGER NOT NULL DEFAULT 0,
    postponed INTEGER NOT NULL DEFAULT 0,home_team_score INTEGER,visitor_team_score INTEGER,
    home_canonical_team_id INTEGER, visitor_canonical_team_id INTEGER, datetime_utc TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(source_provider, source_game_id)
);
"""

POSTGRES_TIMESTAMP_COLUMNS = (
    "created_at",
    "updated_at",
    "current_period_start",
    "current_period_end",
    "canceled_at",
    "used_at",
    "expires_at",
    "started_at",
    "completed_at",
    "fetched_at",
)


def _postgres_schema_sql() -> str:
    """Translate the local SQLite bootstrap schema into PostgreSQL-compatible DDL."""
    schema = SQLITE_SCHEMA_SQL.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")
    schema = re.sub(r"^\s*PRAGMA\s+foreign_keys\s*=\s*ON;\s*", "", schema, flags=re.IGNORECASE | re.MULTILINE)
    for column in POSTGRES_TIMESTAMP_COLUMNS:
        schema = re.sub(rf"\b{column}\s+TEXT\b", f"{column} TIMESTAMPTZ", schema)
    return schema


POSTGRES_SCHEMA_SQL = _postgres_schema_sql()

PLAN_SEEDS = [
    ("free", "Free", 0, 5, 1, "Core dashboard access and starter HawkNetic reports"),
    ("starter", "Starter", 999, 20, 1, "Clean daily card, limited AI explanations, account dashboard"),
    ("pro", "Pro", 1999, 200, 3, "Live board tracking, AI findings breakdowns, subscription export"),
    ("elite", "Elite", 4999, 9999, 10, "Full research layer, team seats, premium HawkNetic workflows"),
]

FREE_ACCESS_ACCOUNT = {"email": "free@hawknetic.local", "password": "free-access", "full_name": "Free Access User", "company": "HawkNetic"}


def _using_postgres() -> bool:
    return bool(settings.database_url)


def _adapt_sql(sql: str) -> str:
    return re.sub(r"\?", "%s", sql) if _using_postgres() else sql


def _schema_sql() -> str:
    return POSTGRES_SCHEMA_SQL if _using_postgres() else SQLITE_SCHEMA_SQL


@contextmanager
def get_connection() -> Iterator[Any]:
    if settings.environment == "production" and not settings.database_url:
        raise RuntimeError("DATABASE_URL is required in production.")
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


def _seed_plans(conn: Any) -> None:
    for seed in PLAN_SEEDS:
        execute(
            conn,
            """
            INSERT INTO plans(code,name,price_cents,monthly_reports,seats,feature_summary,active)
            VALUES(?,?,?,?,?,?,1)
            ON CONFLICT(code) DO UPDATE SET
                name=excluded.name,
                price_cents=excluded.price_cents,
                monthly_reports=excluded.monthly_reports,
                seats=excluded.seats,
                feature_summary=excluded.feature_summary,
                active=excluded.active
            """,
            seed,
        )


def _ensure_user(
    conn: Any,
    email: str,
    password: str,
    full_name: str,
    company: str,
    role: str = "customer",
    ai_opt_in: int = 1,
) -> int:
    normalized_email = email.lower().strip()
    existing = execute(conn, "SELECT id FROM users WHERE email = ?", (normalized_email,)).fetchone()
    password_hash = hash_password(password)
    if existing:
        user_id = int(existing["id"])
        execute(
            conn,
            """
            UPDATE users
            SET password_hash = ?, full_name = ?, company = ?, role = ?, ai_opt_in = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """,
            (password_hash, full_name, company, role, ai_opt_in, user_id),
        )
        return user_id
    cur = execute(
        conn,
        """
        INSERT INTO users(email,password_hash,full_name,company,role,marketing_opt_in,ai_opt_in)
        VALUES(?,?,?,?,?,0,?)
        """,
        (normalized_email, password_hash, full_name, company, role, ai_opt_in),
    )
    return int(cur.lastrowid)


def _seed_free_account(conn: Any) -> None:
    _ensure_user(
        conn,
        email=FREE_ACCESS_ACCOUNT["email"],
        password=FREE_ACCESS_ACCOUNT["password"],
        full_name=FREE_ACCESS_ACCOUNT["full_name"],
        company=FREE_ACCESS_ACCOUNT["company"],
        role="customer",
        ai_opt_in=1,
    )


def _seed_beta_master_account(conn: Any) -> None:
    if not settings.beta_master_enabled:
        return
    if not settings.beta_master_email or not settings.beta_master_password:
        return
    user_id = _ensure_user(
        conn,
        email=settings.beta_master_email,
        password=settings.beta_master_password,
        full_name="Beta Master Access",
        company="HawkNetic Beta",
        role="admin",
        ai_opt_in=1,
    )
    plan_code = (settings.beta_master_plan_code or "elite").lower().strip()
    plan = execute(conn, "SELECT id, price_cents FROM plans WHERE code = ? AND active = 1", (plan_code,)).fetchone()
    if not plan:
        plan = execute(conn, "SELECT id, price_cents FROM plans WHERE code = 'elite' AND active = 1").fetchone()
    if not plan:
        return
    plan_id = int(plan["id"])
    execute(
        conn,
        """
        UPDATE subscriptions
        SET status = 'canceled', canceled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
        WHERE user_id = ? AND status = 'active' AND plan_id <> ?
        """,
        (user_id, plan_id),
    )
    active = execute(
        conn,
        "SELECT id FROM subscriptions WHERE user_id = ? AND plan_id = ? AND status = 'active'",
        (user_id, plan_id),
    ).fetchone()
    if active:
        return
    period_end = (datetime.now(timezone.utc) + timedelta(days=3650)).isoformat()
    cur = execute(
        conn,
        """
        INSERT INTO subscriptions(user_id, plan_id, provider, status, current_period_end)
        VALUES(?, ?, 'beta_seed', 'active', ?)
        """,
        (user_id, plan_id, period_end),
    )
    execute(
        conn,
        """
        INSERT INTO payments(user_id, subscription_id, provider, amount_cents, status)
        VALUES(?, ?, 'beta_seed', ?, 'paid')
        """,
        (user_id, int(cur.lastrowid), int(plan["price_cents"])),
    )


def init_db() -> None:
    with get_connection() as conn:
        for stmt in [s.strip() for s in _schema_sql().split(";") if s.strip()]:
            execute(conn, stmt)
        _seed_plans(conn)
        _seed_free_account(conn)
        _seed_beta_master_account(conn)

def reset_db() -> None:
    if not _using_postgres() and Path(settings.database_path).exists():
        Path(settings.database_path).unlink()
    init_db()
