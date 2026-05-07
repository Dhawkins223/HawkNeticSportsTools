from __future__ import annotations

import json
import sqlite3
from typing import Optional

from app.db import get_connection
from app.security import hash_password


class UserRepository:
    @staticmethod
    def create(email: str, password: str, full_name: str, company: str | None, marketing_opt_in: bool) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO users(email, password_hash, full_name, company, marketing_opt_in)
                VALUES(?, ?, ?, ?, ?)
                """,
                (email.lower().strip(), hash_password(password), full_name.strip(), company.strip() if company else None, int(marketing_opt_in)),
            )
            return int(cur.lastrowid)

    @staticmethod
    def get_by_email(email: str) -> Optional[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()

    @staticmethod
    def get_by_id(user_id: int) -> Optional[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()

    @staticmethod
    def set_ai_opt_in(user_id: int, enabled: bool) -> None:
        with get_connection() as conn:
            conn.execute("UPDATE users SET ai_opt_in = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(enabled), user_id))


class LeadRepository:
    @staticmethod
    def create(email: str, full_name: str | None, company: str | None, use_case: str | None, source_page: str, consent_marketing: bool) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                """
                INSERT INTO leads(email, full_name, company, use_case, source_page, consent_marketing)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (email.lower().strip(), full_name, company, use_case, source_page, int(consent_marketing)),
            )
            return int(cur.lastrowid)


class PlanRepository:
    @staticmethod
    def list_active() -> list[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute("SELECT * FROM plans WHERE active = 1 ORDER BY price_cents ASC").fetchall()

    @staticmethod
    def get_by_code(code: str) -> Optional[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute("SELECT * FROM plans WHERE code = ? AND active = 1", (code,)).fetchone()


class SubscriptionRepository:
    @staticmethod
    def get_active_for_user(user_id: int) -> Optional[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute(
                """
                SELECT s.*, p.code AS plan_code, p.name AS plan_name, p.price_cents
                FROM subscriptions s
                JOIN plans p ON p.id = s.plan_id
                WHERE s.user_id = ? AND s.status = 'active'
                ORDER BY s.id DESC
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()

    @staticmethod
    def subscribe_local(user_id: int, plan_id: int, amount_cents: int) -> int:
        with get_connection() as conn:
            conn.execute(
                "UPDATE subscriptions SET status = 'canceled', canceled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
            cur = conn.execute(
                """
                INSERT INTO subscriptions(user_id, plan_id, provider, status, current_period_end)
                VALUES(?, ?, 'local', 'active', datetime('now', '+30 days'))
                """,
                (user_id, plan_id),
            )
            sub_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO payments(user_id, subscription_id, provider, amount_cents, status)
                VALUES(?, ?, 'local', ?, 'paid')
                """,
                (user_id, sub_id, amount_cents),
            )
            return sub_id

    @staticmethod
    def cancel(user_id: int) -> bool:
        with get_connection() as conn:
            cur = conn.execute(
                """
                UPDATE subscriptions
                SET status = 'canceled', cancel_at_period_end = 0, canceled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND status = 'active'
                """,
                (user_id,),
            )
            return cur.rowcount > 0

    @staticmethod
    def subscribe_stripe(user_id: int, plan_id: int, amount_cents: int, external_subscription_id: str | None, external_customer_id: str | None, external_payment_id: str | None) -> int:
        with get_connection() as conn:
            conn.execute(
                "UPDATE subscriptions SET status = 'canceled', canceled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND status = 'active'",
                (user_id,),
            )
            cur = conn.execute(
                """
                INSERT INTO subscriptions(user_id, plan_id, provider, external_subscription_id, external_customer_id, status, current_period_end)
                VALUES(?, ?, 'stripe', ?, ?, 'active', datetime('now', '+30 days'))
                """,
                (user_id, plan_id, external_subscription_id, external_customer_id),
            )
            sub_id = int(cur.lastrowid)
            conn.execute(
                """
                INSERT INTO payments(user_id, subscription_id, provider, amount_cents, status, external_payment_id)
                VALUES(?, ?, 'stripe', ?, 'paid', ?)
                """,
                (user_id, sub_id, amount_cents, external_payment_id),
            )
            return sub_id


class AuditRepository:
    @staticmethod
    def log(user_id: int | None, action: str, entity_type: str, entity_id: str | None, details: str) -> None:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO audit_logs(user_id, action, entity_type, entity_id, details) VALUES(?, ?, ?, ?, ?)",
                (user_id, action, entity_type, entity_id, details),
            )


class FindingsRepository:
    @staticmethod
    def create(user_id: int, title: str, body: str) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO feature_findings(user_id, title, body) VALUES(?, ?, ?)",
                (user_id, title, body),
            )
            return int(cur.lastrowid)

    @staticmethod
    def list_for_user(user_id: int) -> list[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM feature_findings WHERE user_id = ? ORDER BY created_at DESC, id DESC",
                (user_id,),
            ).fetchall()


class ConversationRepository:
    @staticmethod
    def create(user_id: int, title: str, provider: str, model: str | None) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO ai_conversations(user_id, title, provider, model) VALUES(?, ?, ?, ?)",
                (user_id, title, provider, model),
            )
            return int(cur.lastrowid)

    @staticmethod
    def add_message(conversation_id: int, role: str, content: str, token_count: int | None = None) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO ai_messages(conversation_id, role, content, token_count) VALUES(?, ?, ?, ?)",
                (conversation_id, role, content, token_count),
            )
            return int(cur.lastrowid)

    @staticmethod
    def get_messages(conversation_id: int) -> list[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM ai_messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,)
            ).fetchall()

    @staticmethod
    def list_for_user(user_id: int) -> list[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM ai_conversations WHERE user_id = ? ORDER BY id DESC", (user_id,)
            ).fetchall()


class ProviderSyncRepository:
    @staticmethod
    def start(provider: str, resource: str) -> int:
        with get_connection() as conn:
            cur = conn.execute(
                "INSERT INTO provider_sync_runs(provider, resource, status) VALUES(?, ?, 'running')",
                (provider, resource),
            )
            return int(cur.lastrowid)

    @staticmethod
    def finish(sync_run_id: int, status: str, records_written: int = 0, error_text: str | None = None) -> None:
        with get_connection() as conn:
            conn.execute(
                """
                UPDATE provider_sync_runs
                SET status = ?, records_written = ?, error_text = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, records_written, error_text, sync_run_id),
            )


class RawBallDontLieRepository:
    @staticmethod
    def upsert_teams(items: list[dict]) -> int:
        with get_connection() as conn:
            for item in items:
                conn.execute(
                    """
                    INSERT INTO raw_balldontlie_teams(
                        provider_team_id, conference, division, city, name, full_name, abbreviation, raw_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider_team_id) DO UPDATE SET
                        conference=excluded.conference,
                        division=excluded.division,
                        city=excluded.city,
                        name=excluded.name,
                        full_name=excluded.full_name,
                        abbreviation=excluded.abbreviation,
                        raw_json=excluded.raw_json,
                        fetched_at=CURRENT_TIMESTAMP
                    """,
                    (
                        item.get("id"),
                        item.get("conference"),
                        item.get("division"),
                        item.get("city"),
                        item.get("name"),
                        item.get("full_name"),
                        item.get("abbreviation"),
                        json.dumps(item, separators=(",", ":")),
                    ),
                )
        return len(items)

    @staticmethod
    def upsert_players(items: list[dict]) -> int:
        with get_connection() as conn:
            for item in items:
                team = item.get("team") or {}
                conn.execute(
                    """
                    INSERT INTO raw_balldontlie_players(
                        provider_player_id, first_name, last_name, position, height, weight, jersey_number,
                        college, country, draft_year, draft_round, draft_number, provider_team_id, raw_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider_player_id) DO UPDATE SET
                        first_name=excluded.first_name,
                        last_name=excluded.last_name,
                        position=excluded.position,
                        height=excluded.height,
                        weight=excluded.weight,
                        jersey_number=excluded.jersey_number,
                        college=excluded.college,
                        country=excluded.country,
                        draft_year=excluded.draft_year,
                        draft_round=excluded.draft_round,
                        draft_number=excluded.draft_number,
                        provider_team_id=excluded.provider_team_id,
                        raw_json=excluded.raw_json,
                        fetched_at=CURRENT_TIMESTAMP
                    """,
                    (
                        item.get("id"),
                        item.get("first_name"),
                        item.get("last_name"),
                        item.get("position"),
                        item.get("height"),
                        item.get("weight"),
                        item.get("jersey_number"),
                        item.get("college"),
                        item.get("country"),
                        item.get("draft_year"),
                        item.get("draft_round"),
                        item.get("draft_number"),
                        team.get("id") or item.get("team_id"),
                        json.dumps(item, separators=(",", ":")),
                    ),
                )
        return len(items)

    @staticmethod
    def upsert_games(items: list[dict]) -> int:
        with get_connection() as conn:
            for item in items:
                home_team = item.get("home_team") or {}
                visitor_team = item.get("visitor_team") or {}
                conn.execute(
                    """
                    INSERT INTO raw_balldontlie_games(
                        provider_game_id, game_date, season, status, period, time_text, postseason, postponed,
                        home_team_score, visitor_team_score, home_team_id, visitor_team_id, datetime_utc, raw_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(provider_game_id) DO UPDATE SET
                        game_date=excluded.game_date,
                        season=excluded.season,
                        status=excluded.status,
                        period=excluded.period,
                        time_text=excluded.time_text,
                        postseason=excluded.postseason,
                        postponed=excluded.postponed,
                        home_team_score=excluded.home_team_score,
                        visitor_team_score=excluded.visitor_team_score,
                        home_team_id=excluded.home_team_id,
                        visitor_team_id=excluded.visitor_team_id,
                        datetime_utc=excluded.datetime_utc,
                        raw_json=excluded.raw_json,
                        fetched_at=CURRENT_TIMESTAMP
                    """,
                    (
                        item.get("id"),
                        item.get("date"),
                        item.get("season"),
                        item.get("status"),
                        item.get("period"),
                        item.get("time"),
                        int(bool(item.get("postseason"))),
                        int(bool(item.get("postponed"))),
                        item.get("home_team_score"),
                        item.get("visitor_team_score"),
                        item.get("home_team_id") or home_team.get("id"),
                        item.get("visitor_team_id") or visitor_team.get("id"),
                        item.get("datetime"),
                        json.dumps(item, separators=(",", ":")),
                    ),
                )
        return len(items)

    @staticmethod
    def count(table_name: str) -> int:
        with get_connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS count_value FROM {table_name}").fetchone()
            return int(row["count_value"])


class CanonicalRepository:
    SOURCE_PROVIDER = "balldontlie"

    @staticmethod
    def normalize_teams_from_raw() -> int:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_balldontlie_teams ORDER BY provider_team_id ASC"
            ).fetchall()
            for row in rows:
                conn.execute(
                    """
                    INSERT INTO canonical_teams(
                        source_provider, source_team_id, conference, division, city, name, full_name, abbreviation
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_provider, source_team_id) DO UPDATE SET
                        conference=excluded.conference,
                        division=excluded.division,
                        city=excluded.city,
                        name=excluded.name,
                        full_name=excluded.full_name,
                        abbreviation=excluded.abbreviation,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        CanonicalRepository.SOURCE_PROVIDER,
                        row["provider_team_id"],
                        row["conference"],
                        row["division"],
                        row["city"],
                        row["name"],
                        row["full_name"],
                        row["abbreviation"],
                    ),
                )
            return len(rows)

    @staticmethod
    def normalize_players_from_raw() -> int:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_balldontlie_players ORDER BY provider_player_id ASC"
            ).fetchall()
            for row in rows:
                team_row = None
                if row["provider_team_id"] is not None:
                    team_row = conn.execute(
                        "SELECT id FROM canonical_teams WHERE source_provider = ? AND source_team_id = ?",
                        (CanonicalRepository.SOURCE_PROVIDER, row["provider_team_id"]),
                    ).fetchone()
                full_name = " ".join(part for part in [row["first_name"], row["last_name"]] if part)
                conn.execute(
                    """
                    INSERT INTO canonical_players(
                        source_provider, source_player_id, first_name, last_name, full_name, position, height, weight,
                        jersey_number, college, country, draft_year, draft_round, draft_number, canonical_team_id
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_provider, source_player_id) DO UPDATE SET
                        first_name=excluded.first_name,
                        last_name=excluded.last_name,
                        full_name=excluded.full_name,
                        position=excluded.position,
                        height=excluded.height,
                        weight=excluded.weight,
                        jersey_number=excluded.jersey_number,
                        college=excluded.college,
                        country=excluded.country,
                        draft_year=excluded.draft_year,
                        draft_round=excluded.draft_round,
                        draft_number=excluded.draft_number,
                        canonical_team_id=excluded.canonical_team_id,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        CanonicalRepository.SOURCE_PROVIDER,
                        row["provider_player_id"],
                        row["first_name"],
                        row["last_name"],
                        full_name,
                        row["position"],
                        row["height"],
                        row["weight"],
                        row["jersey_number"],
                        row["college"],
                        row["country"],
                        row["draft_year"],
                        row["draft_round"],
                        row["draft_number"],
                        int(team_row["id"]) if team_row else None,
                    ),
                )
            return len(rows)

    @staticmethod
    def normalize_games_from_raw() -> int:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_balldontlie_games ORDER BY provider_game_id ASC"
            ).fetchall()
            for row in rows:
                home_team = conn.execute(
                    "SELECT id FROM canonical_teams WHERE source_provider = ? AND source_team_id = ?",
                    (CanonicalRepository.SOURCE_PROVIDER, row["home_team_id"]),
                ).fetchone()
                visitor_team = conn.execute(
                    "SELECT id FROM canonical_teams WHERE source_provider = ? AND source_team_id = ?",
                    (CanonicalRepository.SOURCE_PROVIDER, row["visitor_team_id"]),
                ).fetchone()
                conn.execute(
                    """
                    INSERT INTO canonical_games(
                        source_provider, source_game_id, game_date, season, status, period, time_text, postseason,
                        postponed, home_team_score, visitor_team_score, home_canonical_team_id,
                        visitor_canonical_team_id, datetime_utc
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source_provider, source_game_id) DO UPDATE SET
                        game_date=excluded.game_date,
                        season=excluded.season,
                        status=excluded.status,
                        period=excluded.period,
                        time_text=excluded.time_text,
                        postseason=excluded.postseason,
                        postponed=excluded.postponed,
                        home_team_score=excluded.home_team_score,
                        visitor_team_score=excluded.visitor_team_score,
                        home_canonical_team_id=excluded.home_canonical_team_id,
                        visitor_canonical_team_id=excluded.visitor_canonical_team_id,
                        datetime_utc=excluded.datetime_utc,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        CanonicalRepository.SOURCE_PROVIDER,
                        row["provider_game_id"],
                        row["game_date"],
                        row["season"],
                        row["status"],
                        row["period"],
                        row["time_text"],
                        row["postseason"],
                        row["postponed"],
                        row["home_team_score"],
                        row["visitor_team_score"],
                        int(home_team["id"]) if home_team else None,
                        int(visitor_team["id"]) if visitor_team else None,
                        row["datetime_utc"],
                    ),
                )
            return len(rows)

    @staticmethod
    def count(table_name: str) -> int:
        with get_connection() as conn:
            row = conn.execute(f"SELECT COUNT(*) AS count_value FROM {table_name}").fetchone()
            return int(row["count_value"])


class NbaPlatformRepository:
    @staticmethod
    def dashboard_summary() -> dict[str, int]:
        return {
            "tracked_games": CanonicalRepository.count("canonical_games"),
            "tracked_teams": CanonicalRepository.count("canonical_teams"),
            "tracked_players": CanonicalRepository.count("canonical_players"),
        }

    @staticmethod
    def provider_health() -> list[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute(
                """
                SELECT provider, resource, status, records_written, completed_at, error_text
                FROM provider_sync_runs
                ORDER BY id DESC
                LIMIT 10
                """
            ).fetchall()

    @staticmethod
    def list_games(limit: int = 50) -> list[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute(
                """
                SELECT g.*, ht.full_name AS home_team_name, ht.abbreviation AS home_team_abbr,
                       vt.full_name AS visitor_team_name, vt.abbreviation AS visitor_team_abbr
                FROM canonical_games g
                LEFT JOIN canonical_teams ht ON ht.id = g.home_canonical_team_id
                LEFT JOIN canonical_teams vt ON vt.id = g.visitor_canonical_team_id
                ORDER BY COALESCE(g.datetime_utc, g.game_date) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

    @staticmethod
    def get_game(game_id: int) -> Optional[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute(
                """
                SELECT g.*, ht.full_name AS home_team_name, ht.abbreviation AS home_team_abbr,
                       ht.id AS home_team_id, vt.full_name AS visitor_team_name,
                       vt.abbreviation AS visitor_team_abbr, vt.id AS visitor_team_id
                FROM canonical_games g
                LEFT JOIN canonical_teams ht ON ht.id = g.home_canonical_team_id
                LEFT JOIN canonical_teams vt ON vt.id = g.visitor_canonical_team_id
                WHERE g.id = ?
                """,
                (game_id,),
            ).fetchone()

    @staticmethod
    def get_player(player_id: int) -> Optional[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute(
                """
                SELECT p.*, t.full_name AS team_name, t.abbreviation AS team_abbr, t.id AS team_id
                FROM canonical_players p
                LEFT JOIN canonical_teams t ON t.id = p.canonical_team_id
                WHERE p.id = ?
                """,
                (player_id,),
            ).fetchone()

    @staticmethod
    def get_team(team_id: int) -> Optional[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute("SELECT * FROM canonical_teams WHERE id = ?", (team_id,)).fetchone()

    @staticmethod
    def list_team_players(team_id: int, limit: int = 25) -> list[sqlite3.Row]:
        with get_connection() as conn:
            return conn.execute(
                "SELECT * FROM canonical_players WHERE canonical_team_id = ? ORDER BY full_name ASC LIMIT ?",
                (team_id, limit),
            ).fetchall()
