from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from app.database import execute, get_connection
from app.security import generate_reset_token, hash_password, hash_reset_token


def _dict(row: Any) -> dict | None:
    return dict(row) if row is not None else None


def _list(rows: list[Any]) -> list[dict]:
    return [dict(row) for row in rows]


class UserRepository:
    @staticmethod
    def create(email: str, password: str, full_name: str, company: str | None, marketing_opt_in: bool) -> int:
        with get_connection() as conn:
            cur = execute(conn, """
                INSERT INTO users(email, password_hash, full_name, company, marketing_opt_in)
                VALUES(?, ?, ?, ?, ?)
            """, (email.lower().strip(), hash_password(password), full_name.strip(), company.strip() if company else None, int(marketing_opt_in)))
            return int(cur.lastrowid)

    @staticmethod
    def get_by_email(email: str) -> Optional[dict]:
        with get_connection() as conn:
            return _dict(execute(conn, "SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone())

    @staticmethod
    def get_by_id(user_id: int) -> Optional[dict]:
        with get_connection() as conn:
            return _dict(execute(conn, "SELECT * FROM users WHERE id = ?", (user_id,)).fetchone())

    @staticmethod
    def set_ai_opt_in(user_id: int, enabled: bool) -> None:
        with get_connection() as conn:
            execute(conn, "UPDATE users SET ai_opt_in = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (int(enabled), user_id))

    @staticmethod
    def set_password(user_id: int, password: str) -> None:
        with get_connection() as conn:
            execute(conn, "UPDATE users SET password_hash = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?", (hash_password(password), user_id))


class PasswordResetRepository:
    @staticmethod
    def create_for_email(email: str, requester_ip: str | None, user_agent: str | None, ttl_minutes: int = 60) -> dict | None:
        user = UserRepository.get_by_email(email)
        if not user:
            return None
        token = generate_reset_token()
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)).isoformat()
        with get_connection() as conn:
            cur = execute(conn, """
                INSERT INTO password_reset_tokens(user_id, requested_email, token_hash, expires_at, requester_ip, user_agent)
                VALUES(?, ?, ?, ?, ?, ?)
            """, (int(user["id"]), email.lower().strip(), hash_reset_token(token), expires_at, requester_ip, user_agent))
            return {"id": int(cur.lastrowid), "token": token, "user_id": int(user["id"]), "expires_at": expires_at}

    @staticmethod
    def get_valid(token: str) -> Optional[dict]:
        if not token:
            return None
        with get_connection() as conn:
            row = execute(conn, """
                SELECT pr.*, u.email, u.full_name
                FROM password_reset_tokens pr
                JOIN users u ON u.id = pr.user_id
                WHERE pr.token_hash = ?
            """, (hash_reset_token(token),)).fetchone()
        row = _dict(row)
        if not row or row.get("used_at"):
            return None
        expires_at = row.get("expires_at")
        if not isinstance(expires_at, datetime):
            expires_at = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return row if expires_at >= datetime.now(timezone.utc) else None

    @staticmethod
    def reset_password(token: str, password: str) -> bool:
        row = PasswordResetRepository.get_valid(token)
        if not row:
            return False
        UserRepository.set_password(int(row["user_id"]), password)
        with get_connection() as conn:
            execute(conn, "UPDATE password_reset_tokens SET used_at = CURRENT_TIMESTAMP WHERE id = ?", (int(row["id"]),))
        return True


class LeadRepository:
    @staticmethod
    def create(email: str, full_name: str | None, company: str | None, use_case: str | None, source_page: str, consent_marketing: bool) -> int:
        with get_connection() as conn:
            cur = execute(conn, """
                INSERT INTO leads(email, full_name, company, use_case, source_page, consent_marketing)
                VALUES(?, ?, ?, ?, ?, ?)
            """, (email.lower().strip(), full_name, company, use_case, source_page, int(consent_marketing)))
            return int(cur.lastrowid)


class PlanRepository:
    @staticmethod
    def list_active() -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM plans WHERE active = 1 ORDER BY price_cents ASC").fetchall())

    @staticmethod
    def get_by_code(code: str) -> Optional[dict]:
        with get_connection() as conn:
            return _dict(execute(conn, "SELECT * FROM plans WHERE code = ? AND active = 1", (code,)).fetchone())


class SubscriptionRepository:
    @staticmethod
    def get_active_for_user(user_id: int) -> Optional[dict]:
        with get_connection() as conn:
            return _dict(execute(conn, """
                SELECT s.*, p.code AS plan_code, p.name AS plan_name, p.price_cents
                FROM subscriptions s
                JOIN plans p ON p.id = s.plan_id
                WHERE s.user_id = ? AND s.status = 'active'
                ORDER BY s.id DESC
                LIMIT 1
            """, (user_id,)).fetchone())

    @staticmethod
    def subscribe_local(user_id: int, plan_id: int, amount_cents: int) -> int:
        with get_connection() as conn:
            execute(conn, "UPDATE subscriptions SET status = 'canceled', canceled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND status = 'active'", (user_id,))
            cur = execute(conn, "INSERT INTO subscriptions(user_id, plan_id, provider, status, current_period_end) VALUES(?, ?, 'local', 'active', CURRENT_TIMESTAMP)", (user_id, plan_id))
            sub_id = int(cur.lastrowid)
            execute(conn, "INSERT INTO payments(user_id, subscription_id, provider, amount_cents, status) VALUES(?, ?, 'local', ?, 'paid')", (user_id, sub_id, amount_cents))
            return sub_id

    @staticmethod
    def cancel(user_id: int) -> bool:
        with get_connection() as conn:
            cur = execute(conn, """
                UPDATE subscriptions
                SET status = 'canceled', cancel_at_period_end = 0, canceled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP
                WHERE user_id = ? AND status = 'active'
            """, (user_id,))
            return cur.rowcount > 0

    @staticmethod
    def subscribe_stripe(user_id: int, plan_id: int, amount_cents: int, external_subscription_id: str | None, external_customer_id: str | None, external_payment_id: str | None) -> int:
        with get_connection() as conn:
            execute(conn, "UPDATE subscriptions SET status = 'canceled', canceled_at = CURRENT_TIMESTAMP, updated_at = CURRENT_TIMESTAMP WHERE user_id = ? AND status = 'active'", (user_id,))
            cur = execute(conn, """
                INSERT INTO subscriptions(user_id, plan_id, provider, external_subscription_id, external_customer_id, status, current_period_end)
                VALUES(?, ?, 'stripe', ?, ?, 'active', CURRENT_TIMESTAMP)
            """, (user_id, plan_id, external_subscription_id, external_customer_id))
            sub_id = int(cur.lastrowid)
            execute(conn, """
                INSERT INTO payments(user_id, subscription_id, provider, amount_cents, status, external_payment_id)
                VALUES(?, ?, 'stripe', ?, 'paid', ?)
            """, (user_id, sub_id, amount_cents, external_payment_id))
            return sub_id


class AuditRepository:
    @staticmethod
    def log(user_id: int | None, action: str, entity_type: str, entity_id: str | None, details: str) -> None:
        with get_connection() as conn:
            execute(conn, "INSERT INTO audit_logs(user_id, action, entity_type, entity_id, details) VALUES(?, ?, ?, ?, ?)", (user_id, action, entity_type, entity_id, details))


class FindingsRepository:
    @staticmethod
    def create(user_id: int, title: str, body: str) -> int:
        with get_connection() as conn:
            cur = execute(conn, "INSERT INTO feature_findings(user_id, title, body) VALUES(?, ?, ?)", (user_id, title, body))
            return int(cur.lastrowid)

    @staticmethod
    def list_for_user(user_id: int) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM feature_findings WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user_id,)).fetchall())


class ConversationRepository:
    @staticmethod
    def create(user_id: int, title: str, provider: str, model: str | None) -> int:
        with get_connection() as conn:
            cur = execute(conn, "INSERT INTO ai_conversations(user_id, title, provider, model) VALUES(?, ?, ?, ?)", (user_id, title, provider, model))
            return int(cur.lastrowid)

    @staticmethod
    def add_message(conversation_id: int, role: str, content: str, token_count: int | None = None) -> int:
        with get_connection() as conn:
            cur = execute(conn, "INSERT INTO ai_messages(conversation_id, role, content, token_count) VALUES(?, ?, ?, ?)", (conversation_id, role, content, token_count))
            return int(cur.lastrowid)

    @staticmethod
    def get_messages(conversation_id: int) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM ai_messages WHERE conversation_id = ? ORDER BY id ASC", (conversation_id,)).fetchall())

    @staticmethod
    def list_for_user(user_id: int) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM ai_conversations WHERE user_id = ? ORDER BY id DESC", (user_id,)).fetchall())


class BdlRepository:
    @staticmethod
    def start_log(resource: str, request: dict | None = None) -> int:
        with get_connection() as conn:
            cur = execute(conn, "INSERT INTO bdl_ingestion_logs(resource, status, request_json) VALUES(?, 'running', ?)", (resource, json.dumps(request or {}, separators=(",", ":"))))
            return int(cur.lastrowid)

    @staticmethod
    def finish_log(log_id: int, status: str, records_read: int = 0, records_written: int = 0, error_text: str | None = None, response_excerpt: str | None = None) -> None:
        with get_connection() as conn:
            execute(conn, """
                UPDATE bdl_ingestion_logs
                SET status = ?, records_read = ?, records_written = ?, error_text = ?, response_excerpt = ?, completed_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (status, records_read, records_written, error_text, response_excerpt, log_id))

    @staticmethod
    def logs(limit: int = 50) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM bdl_ingestion_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall())

    @staticmethod
    def status() -> dict:
        latest = BdlRepository.logs(limit=10)
        return {"configured_logs": bool(latest), "latest": latest, "counts": BdlRepository.counts()}

    @staticmethod
    def counts() -> dict[str, int]:
        with get_connection() as conn:
            return {
                "teams": int(execute(conn, "SELECT COUNT(*) AS c FROM bdl_teams").fetchone()["c"]),
                "players": int(execute(conn, "SELECT COUNT(*) AS c FROM bdl_players").fetchone()["c"]),
                "games": int(execute(conn, "SELECT COUNT(*) AS c FROM bdl_games").fetchone()["c"]),
                "player_game_stats": int(execute(conn, "SELECT COUNT(*) AS c FROM bdl_player_game_stats").fetchone()["c"]),
                "team_game_stats": int(execute(conn, "SELECT COUNT(*) AS c FROM bdl_team_game_stats").fetchone()["c"]),
                "live_games": int(execute(conn, "SELECT COUNT(*) AS c FROM bdl_live_games").fetchone()["c"]),
            }

    @staticmethod
    def upsert_teams(items: list[dict]) -> int:
        with get_connection() as conn:
            for item in items:
                execute(conn, """
                    INSERT INTO bdl_teams(bdl_team_id, conference, division, city, name, full_name, abbreviation, raw_json)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bdl_team_id) DO UPDATE SET
                        conference=excluded.conference, division=excluded.division, city=excluded.city,
                        name=excluded.name, full_name=excluded.full_name, abbreviation=excluded.abbreviation,
                        raw_json=excluded.raw_json, fetched_at=CURRENT_TIMESTAMP
                """, (item.get("id"), item.get("conference"), item.get("division"), item.get("city"), item.get("name"), item.get("full_name"), item.get("abbreviation"), json.dumps(item, separators=(",", ":"))))
        return len(items)

    @staticmethod
    def upsert_players(items: list[dict]) -> int:
        with get_connection() as conn:
            for item in items:
                team = item.get("team") or {}
                full_name = " ".join(part for part in [item.get("first_name"), item.get("last_name")] if part)
                execute(conn, """
                    INSERT INTO bdl_players(
                        bdl_player_id, first_name, last_name, full_name, position, height, weight, jersey_number,
                        college, country, draft_year, draft_round, draft_number, bdl_team_id, raw_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bdl_player_id) DO UPDATE SET
                        first_name=excluded.first_name, last_name=excluded.last_name, full_name=excluded.full_name,
                        position=excluded.position, height=excluded.height, weight=excluded.weight,
                        jersey_number=excluded.jersey_number, college=excluded.college, country=excluded.country,
                        draft_year=excluded.draft_year, draft_round=excluded.draft_round, draft_number=excluded.draft_number,
                        bdl_team_id=excluded.bdl_team_id, raw_json=excluded.raw_json, fetched_at=CURRENT_TIMESTAMP
                """, (item.get("id"), item.get("first_name"), item.get("last_name"), full_name, item.get("position"), item.get("height"), item.get("weight"), item.get("jersey_number"), item.get("college"), item.get("country"), item.get("draft_year"), item.get("draft_round"), item.get("draft_number"), team.get("id") or item.get("team_id"), json.dumps(item, separators=(",", ":"))))
        return len(items)

    @staticmethod
    def upsert_games(items: list[dict]) -> int:
        with get_connection() as conn:
            for item in items:
                home_team = item.get("home_team") or {}
                visitor_team = item.get("visitor_team") or {}
                execute(conn, """
                    INSERT INTO bdl_games(
                        bdl_game_id, game_date, season, status, period, time_text, postseason, postponed,
                        home_team_score, visitor_team_score, home_team_id, visitor_team_id, datetime_utc, raw_json
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(bdl_game_id) DO UPDATE SET
                        game_date=excluded.game_date, season=excluded.season, status=excluded.status,
                        period=excluded.period, time_text=excluded.time_text, postseason=excluded.postseason,
                        postponed=excluded.postponed, home_team_score=excluded.home_team_score,
                        visitor_team_score=excluded.visitor_team_score, home_team_id=excluded.home_team_id,
                        visitor_team_id=excluded.visitor_team_id, datetime_utc=excluded.datetime_utc,
                        raw_json=excluded.raw_json, fetched_at=CURRENT_TIMESTAMP
                """, (item.get("id"), item.get("date"), item.get("season"), item.get("status"), item.get("period"), item.get("time"), int(bool(item.get("postseason"))), int(bool(item.get("postponed"))), item.get("home_team_score"), item.get("visitor_team_score"), item.get("home_team_id") or home_team.get("id"), item.get("visitor_team_id") or visitor_team.get("id"), item.get("datetime"), json.dumps(item, separators=(",", ":"))))
        return len(items)

    @staticmethod
    def count(table_name: str) -> int:
        table_map = {
            "raw_balldontlie_teams": "bdl_teams", "raw_balldontlie_players": "bdl_players", "raw_balldontlie_games": "bdl_games",
            "bdl_teams": "bdl_teams", "bdl_players": "bdl_players", "bdl_games": "bdl_games",
        }
        table = table_map.get(table_name, table_name)
        with get_connection() as conn:
            return int(execute(conn, f"SELECT COUNT(*) AS count_value FROM {table}").fetchone()["count_value"])


class RawBallDontLieRepository(BdlRepository):
    pass


class CanonicalRepository:
    @staticmethod
    def normalize_teams_from_raw() -> int:
        return MappingRepository.auto_map_teams()

    @staticmethod
    def normalize_players_from_raw() -> int:
        return MappingRepository.auto_map_players()

    @staticmethod
    def normalize_games_from_raw() -> int:
        return MappingRepository.auto_map_games()

    @staticmethod
    def count(table_name: str) -> int:
        mapping = {"canonical_teams": "historical_teams", "canonical_players": "historical_players", "canonical_games": "historical_games"}
        table = mapping.get(table_name, table_name)
        with get_connection() as conn:
            return int(execute(conn, f"SELECT COUNT(*) AS count_value FROM {table}").fetchone()["count_value"])


class MappingRepository:
    @staticmethod
    def auto_map_teams() -> int:
        with get_connection() as conn:
            rows = execute(conn, """
                SELECT h.id AS historical_team_id, b.bdl_team_id
                FROM historical_teams h
                JOIN bdl_teams b ON lower(h.abbreviation) = lower(b.abbreviation) OR lower(h.full_name) = lower(b.full_name)
            """).fetchall()
            for row in rows:
                execute(conn, """
                    INSERT INTO team_identity_map(historical_team_id, bdl_team_id, confidence, mapping_source)
                    VALUES(?, ?, 0.9, 'auto_name_match')
                    ON CONFLICT(historical_team_id, bdl_team_id) DO UPDATE SET confidence=excluded.confidence, updated_at=CURRENT_TIMESTAMP
                """, (row["historical_team_id"], row["bdl_team_id"]))
            return len(rows)

    @staticmethod
    def auto_map_players() -> int:
        with get_connection() as conn:
            rows = execute(conn, """
                SELECT h.id AS historical_player_id, b.bdl_player_id
                FROM historical_players h
                JOIN bdl_players b ON lower(h.full_name) = lower(b.full_name)
            """).fetchall()
            for row in rows:
                execute(conn, """
                    INSERT INTO player_identity_map(historical_player_id, bdl_player_id, confidence, mapping_source)
                    VALUES(?, ?, 0.75, 'auto_name_match')
                    ON CONFLICT(historical_player_id, bdl_player_id) DO UPDATE SET confidence=excluded.confidence, updated_at=CURRENT_TIMESTAMP
                """, (row["historical_player_id"], row["bdl_player_id"]))
            return len(rows)

    @staticmethod
    def auto_map_games() -> int:
        return 0

    @staticmethod
    def counts() -> dict[str, int]:
        with get_connection() as conn:
            return {
                "teams": int(execute(conn, "SELECT COUNT(*) AS c FROM team_identity_map").fetchone()["c"]),
                "players": int(execute(conn, "SELECT COUNT(*) AS c FROM player_identity_map").fetchone()["c"]),
                "games": int(execute(conn, "SELECT COUNT(*) AS c FROM game_identity_map").fetchone()["c"]),
            }


class HistoricalRepository:
    @staticmethod
    def coverage() -> dict:
        with get_connection() as conn:
            rows = _list(execute(conn, """
                SELECT *
                FROM data_quality_reports
                WHERE report_type = 'historical_season_coverage' AND season BETWEEN 1996 AND 2026
                ORDER BY season ASC
            """).fetchall())
            totals = {
                "games": int(execute(conn, "SELECT COUNT(*) AS c FROM historical_games").fetchone()["c"]),
                "player_game_rows": int(execute(conn, "SELECT COUNT(*) AS c FROM historical_player_game_stats").fetchone()["c"]),
                "team_game_rows": int(execute(conn, "SELECT COUNT(*) AS c FROM historical_team_game_stats").fetchone()["c"]),
            }
        complete = [row for row in rows if row["status"] == "complete"]
        scraped = [int(row["season"]) for row in rows if int(row.get("games_scraped") or 0) > 0 or int(row.get("actual_records") or 0) > 0]
        missing = [season for season in range(1996, 2027) if season not in {int(row["season"]) for row in complete}]
        return {
            "start_season": 1996,
            "end_season": 2026,
            "total_seasons": 31,
            "complete_seasons": len(complete),
            "incomplete_seasons": 31 - len(complete),
            "oldest_scraped_season": min(scraped) if scraped else None,
            "newest_scraped_season": max(scraped) if scraped else None,
            "missing_seasons": missing,
            "total_games_stored": totals["games"],
            "total_player_game_stat_rows": totals["player_game_rows"],
            "total_team_game_stat_rows": totals["team_game_rows"],
            "missing_box_scores": sum(int(row.get("missing_box_scores") or 0) for row in rows),
            "failed_urls": sum(int(row.get("failed_urls") or 0) for row in rows),
            "last_scrape_time": max((str(row.get("last_scrape_at") or row.get("checked_at") or "") for row in rows), default="") or None,
            "last_import_time": max((str(row.get("last_import_at") or "") for row in rows), default="") or None,
            "seasons": rows,
        }

    @staticmethod
    def rebuild() -> dict:
        with get_connection() as conn:
            for season in range(1996, 2027):
                game_count = execute(conn, "SELECT COUNT(*) AS c FROM historical_games WHERE season = ?", (season,)).fetchone()["c"]
                stat_count = execute(conn, "SELECT COUNT(*) AS c FROM historical_player_game_stats WHERE season = ?", (season,)).fetchone()["c"]
                status = "complete" if int(game_count) and int(stat_count) else "incomplete"
                execute(conn, """
                    INSERT INTO data_quality_reports(report_type, season, status, expected_records, actual_records, details_json)
                    VALUES('historical_season_coverage', ?, ?, 1, ?, ?)
                    ON CONFLICT(report_type, season) DO UPDATE SET status=excluded.status, actual_records=excluded.actual_records, details_json=excluded.details_json, updated_at=CURRENT_TIMESTAMP
                """, (season, status, int(game_count), json.dumps({"games": int(game_count), "player_game_stats": int(stat_count), "message": "Backfill source not configured; season marked incomplete until historical loader writes records."})))
        return HistoricalRepository.coverage()

    @staticmethod
    def season(season: int) -> dict:
        with get_connection() as conn:
            games = _list(execute(conn, "SELECT * FROM historical_games WHERE season = ? ORDER BY game_date ASC LIMIT 200", (season,)).fetchall())
            report = _dict(execute(conn, "SELECT * FROM data_quality_reports WHERE report_type = 'historical_season_coverage' AND season = ?", (season,)).fetchone())
        return {"season": season, "coverage": report, "games": games}

    @staticmethod
    def list_teams(limit: int = 100) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM historical_teams ORDER BY full_name ASC LIMIT ?", (limit,)).fetchall())

    @staticmethod
    def list_players(limit: int = 100) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM historical_players ORDER BY full_name ASC LIMIT ?", (limit,)).fetchall())

    @staticmethod
    def list_games(limit: int = 100) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, """
                SELECT g.*, ht.full_name AS home_team_name, at.full_name AS visitor_team_name,
                       ht.abbreviation AS home_team_abbr, at.abbreviation AS visitor_team_abbr
                FROM historical_games g
                LEFT JOIN historical_teams ht ON ht.id = g.home_team_id
                LEFT JOIN historical_teams at ON at.id = g.away_team_id
                ORDER BY COALESCE(g.game_date, CAST(g.created_at AS TEXT)) DESC LIMIT ?
            """, (limit,)).fetchall())


    @staticmethod
    def cavs_practice_games(limit: int = 25) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, """
                SELECT g.*, ht.full_name AS home_team_name, at.full_name AS visitor_team_name,
                       ht.abbreviation AS home_team_abbr, at.abbreviation AS visitor_team_abbr
                FROM historical_games g
                LEFT JOIN historical_teams ht ON ht.id = g.home_team_id
                LEFT JOIN historical_teams at ON at.id = g.away_team_id
                WHERE lower(COALESCE(ht.full_name, g.home_team_key, '')) LIKE '%cav%'
                   OR lower(COALESCE(at.full_name, g.away_team_key, '')) LIKE '%cav%'
                   OR lower(COALESCE(g.home_team_key, '')) IN ('cle', 'cleveland_cavaliers', 'cleveland_cavaliers_star')
                   OR lower(COALESCE(g.away_team_key, '')) IN ('cle', 'cleveland_cavaliers', 'cleveland_cavaliers_star')
                ORDER BY COALESCE(g.game_date, CAST(g.created_at AS TEXT)) DESC
                LIMIT ?
            """, (limit,)).fetchall())

    @staticmethod
    def cavs_practice_summary() -> dict:
        games = HistoricalRepository.cavs_practice_games(limit=50)
        completed = [game for game in games if game.get("home_score") is not None or game.get("away_score") is not None or game.get("home_team_score") is not None]
        wins = 0
        losses = 0
        for game in completed:
            home_name = (game.get("home_team_name") or game.get("home_team_key") or "").lower()
            is_home = "cav" in home_name or home_name in {"cle", "cleveland_cavaliers"}
            home_score = game.get("home_score") or game.get("home_team_score") or 0
            away_score = game.get("away_score") or game.get("visitor_team_score") or 0
            cavs_score = home_score if is_home else away_score
            opp_score = away_score if is_home else home_score
            if cavs_score > opp_score:
                wins += 1
            elif cavs_score < opp_score:
                losses += 1
        confidence = round((wins / max(1, wins + losses)) * 100, 1) if completed else 0
        return {"games_available": len(games), "completed_games": len(completed), "recent_wins": wins, "recent_losses": losses, "practice_confidence": confidence, "games": games[:25]}

    @staticmethod
    def get_team(team_id: int) -> Optional[dict]:
        with get_connection() as conn:
            return _dict(execute(conn, "SELECT * FROM historical_teams WHERE id = ?", (team_id,)).fetchone())

    @staticmethod
    def get_player(player_id: int) -> Optional[dict]:
        with get_connection() as conn:
            return _dict(execute(conn, "SELECT * FROM historical_players WHERE id = ?", (player_id,)).fetchone())

    @staticmethod
    def get_game(game_id: int) -> Optional[dict]:
        with get_connection() as conn:
            return _dict(execute(conn, "SELECT * FROM historical_games WHERE id = ?", (game_id,)).fetchone())


class ModelingRepository:
    @staticmethod
    def props(limit: int = 100) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM props ORDER BY expected_value DESC, updated_at DESC LIMIT ?", (limit,)).fetchall())

    @staticmethod
    def odds(limit: int = 100) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM odds ORDER BY fetched_at DESC LIMIT ?", (limit,)).fetchall())

    @staticmethod
    def simulations(limit: int = 50) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, "SELECT * FROM simulations ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall())

    @staticmethod
    def run_simulation(game_id: int | None = None, runs: int = 1000) -> dict:
        result = {"message": "Simulation engine placeholder: PyTorch model output table is ready, but no model artifact is configured yet.", "game_id": game_id, "runs": runs}
        with get_connection() as conn:
            cur = execute(conn, """
                INSERT INTO simulations(game_id, simulation_type, runs, confidence, result_json)
                VALUES(?, 'game', ?, 0, ?)
            """, (game_id, runs, json.dumps(result, separators=(",", ":"))))
            result["id"] = int(cur.lastrowid)
            return result

    @staticmethod
    def parlays(user_id: int | None = None) -> list[dict]:
        with get_connection() as conn:
            if user_id:
                return _list(execute(conn, "SELECT * FROM parlays WHERE user_id = ? ORDER BY updated_at DESC", (user_id,)).fetchall())
            return _list(execute(conn, "SELECT * FROM parlays ORDER BY updated_at DESC LIMIT 50").fetchall())

    @staticmethod
    def build_parlay(user_id: int | None, legs: list[dict], name: str = "Generated Parlay") -> dict:
        probabilities = [float(leg.get("probability") or 0.5) for leg in legs] or [0.5]
        win_probability = 1.0
        for probability in probabilities:
            win_probability *= max(0.01, min(probability, 0.99))
        loss_probability = 1 - win_probability
        risk_tier = "high" if len(legs) >= 4 or win_probability < 0.2 else "medium" if len(legs) >= 2 else "low"
        estimated_odds = int(round((1 / win_probability - 1) * 100)) if win_probability > 0 else None
        with get_connection() as conn:
            cur = execute(conn, """
                INSERT INTO parlays(user_id, name, estimated_odds, win_probability, loss_probability, expected_value, risk_tier, confidence_tier, correlation_warning, trap_leg_warning)
                VALUES(?, ?, ?, ?, ?, 0, ?, ?, ?, ?)
            """, (user_id, name, estimated_odds, win_probability, loss_probability, risk_tier, "medium", "Review same-game/team correlation before placing.", "No trap-leg model configured yet."))
            parlay_id = int(cur.lastrowid)
            for index, leg in enumerate(legs):
                execute(conn, "INSERT INTO parlay_legs(parlay_id, prop_id, leg_order, label, odds_value, probability) VALUES(?, ?, ?, ?, ?, ?)", (parlay_id, leg.get("prop_id"), index, leg.get("label", "Custom leg"), leg.get("odds_value"), leg.get("probability")))
        return {"id": parlay_id, "estimated_odds": estimated_odds, "win_probability": win_probability, "loss_probability": loss_probability, "expected_value": 0, "risk_tier": risk_tier, "correlation_warning": "Review same-game/team correlation before placing.", "trap_leg_warning": "No trap-leg model configured yet.", "legs": legs}

    @staticmethod
    def reorder_parlay(parlay_id: int, leg_ids: list[int]) -> dict:
        with get_connection() as conn:
            for order, leg_id in enumerate(leg_ids):
                execute(conn, "UPDATE parlay_legs SET leg_order = ? WHERE id = ? AND parlay_id = ?", (order, leg_id, parlay_id))
            execute(conn, "UPDATE parlays SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (parlay_id,))
        return {"ok": True, "parlay_id": parlay_id, "leg_ids": leg_ids}


class NbaPlatformRepository:
    @staticmethod
    def dashboard_summary() -> dict[str, int]:
        with get_connection() as conn:
            return {
                "tracked_games": int(execute(conn, "SELECT COUNT(*) c FROM historical_games").fetchone()["c"]),
                "tracked_teams": int(execute(conn, "SELECT COUNT(*) c FROM historical_teams").fetchone()["c"]),
                "tracked_players": int(execute(conn, "SELECT COUNT(*) c FROM historical_players").fetchone()["c"]),
            }

    @staticmethod
    def storage_summary() -> dict[str, dict[str, int]]:
        return {"historical": NbaPlatformRepository.dashboard_summary(), "bdl": BdlRepository.counts(), "mappings": MappingRepository.counts()}

    @staticmethod
    def provider_health() -> list[dict]:
        return BdlRepository.logs(limit=10)

    @staticmethod
    def list_games(limit: int = 50) -> list[dict]:
        games = HistoricalRepository.list_games(limit=limit)
        if games:
            return games
        with get_connection() as conn:
            return _list(execute(conn, """
                SELECT g.id, g.bdl_game_id AS source_game_id, g.game_date, g.season, g.status, g.period, g.time_text,
                       g.postseason, g.postponed, g.home_team_score, g.visitor_team_score, g.datetime_utc,
                       ht.full_name AS home_team_name, ht.abbreviation AS home_team_abbr,
                       vt.full_name AS visitor_team_name, vt.abbreviation AS visitor_team_abbr
                FROM bdl_games g
                LEFT JOIN bdl_teams ht ON ht.bdl_team_id = g.home_team_id
                LEFT JOIN bdl_teams vt ON vt.bdl_team_id = g.visitor_team_id
                ORDER BY COALESCE(g.datetime_utc, g.game_date, CAST(g.fetched_at AS TEXT)) DESC
                LIMIT ?
            """, (limit,)).fetchall())

    @staticmethod
    def get_game(game_id: int) -> Optional[dict]:
        game = HistoricalRepository.get_game(game_id)
        if game:
            return game
        with get_connection() as conn:
            return _dict(execute(conn, "SELECT * FROM bdl_games WHERE id = ?", (game_id,)).fetchone())

    @staticmethod
    def get_player(player_id: int) -> Optional[dict]:
        player = HistoricalRepository.get_player(player_id)
        if player:
            return player
        with get_connection() as conn:
            return _dict(execute(conn, "SELECT *, bdl_team_id AS team_id FROM bdl_players WHERE id = ?", (player_id,)).fetchone())


    @staticmethod
    def cavs_practice_games(limit: int = 25) -> list[dict]:
        with get_connection() as conn:
            return _list(execute(conn, """
                SELECT g.*, ht.full_name AS home_team_name, at.full_name AS visitor_team_name,
                       ht.abbreviation AS home_team_abbr, at.abbreviation AS visitor_team_abbr
                FROM historical_games g
                LEFT JOIN historical_teams ht ON ht.id = g.home_team_id
                LEFT JOIN historical_teams at ON at.id = g.away_team_id
                WHERE lower(COALESCE(ht.full_name, g.home_team_key, '')) LIKE '%cav%'
                   OR lower(COALESCE(at.full_name, g.away_team_key, '')) LIKE '%cav%'
                   OR lower(COALESCE(g.home_team_key, '')) IN ('cle', 'cleveland_cavaliers', 'cleveland_cavaliers_star')
                   OR lower(COALESCE(g.away_team_key, '')) IN ('cle', 'cleveland_cavaliers', 'cleveland_cavaliers_star')
                ORDER BY COALESCE(g.game_date, CAST(g.created_at AS TEXT)) DESC
                LIMIT ?
            """, (limit,)).fetchall())

    @staticmethod
    def cavs_practice_summary() -> dict:
        games = HistoricalRepository.cavs_practice_games(limit=50)
        completed = [game for game in games if game.get("home_score") is not None or game.get("away_score") is not None or game.get("home_team_score") is not None]
        wins = 0
        losses = 0
        for game in completed:
            home_name = (game.get("home_team_name") or game.get("home_team_key") or "").lower()
            is_home = "cav" in home_name or home_name in {"cle", "cleveland_cavaliers"}
            home_score = game.get("home_score") or game.get("home_team_score") or 0
            away_score = game.get("away_score") or game.get("visitor_team_score") or 0
            cavs_score = home_score if is_home else away_score
            opp_score = away_score if is_home else home_score
            if cavs_score > opp_score:
                wins += 1
            elif cavs_score < opp_score:
                losses += 1
        confidence = round((wins / max(1, wins + losses)) * 100, 1) if completed else 0
        return {"games_available": len(games), "completed_games": len(completed), "recent_wins": wins, "recent_losses": losses, "practice_confidence": confidence, "games": games[:25]}

    @staticmethod
    def get_team(team_id: int) -> Optional[dict]:
        team = HistoricalRepository.get_team(team_id)
        if team:
            return team
        with get_connection() as conn:
            return _dict(execute(conn, "SELECT *, bdl_team_id AS source_team_id FROM bdl_teams WHERE id = ?", (team_id,)).fetchone())

    @staticmethod
    def list_team_players(team_id: int, limit: int = 25) -> list[dict]:
        with get_connection() as conn:
            rows = execute(conn, "SELECT * FROM historical_players ORDER BY full_name ASC LIMIT ?", (limit,)).fetchall()
            if rows:
                return _list(rows)
            return _list(execute(conn, "SELECT * FROM bdl_players ORDER BY full_name ASC LIMIT ?", (limit,)).fetchall())
