from __future__ import annotations

import sqlite3

from app.database import execute, get_connection


class PlatformService:
    @staticmethod
    def is_paid_user(subscription: sqlite3.Row | None) -> bool:
        if not subscription:
            return False
        return subscription["plan_code"] != "free"

    @staticmethod
    def dashboard_snapshot() -> dict:
        with get_connection() as conn:
            return {
                "teams": execute(conn, "SELECT COUNT(*) c FROM canonical_teams").fetchone()["c"],
                "players": execute(conn, "SELECT COUNT(*) c FROM canonical_players").fetchone()["c"],
                "games": execute(conn, "SELECT COUNT(*) c FROM canonical_games").fetchone()["c"],
                "recent_games": execute(conn, 
                    """
                    SELECT g.*, ht.abbreviation AS home_abbr, vt.abbreviation AS visitor_abbr
                    FROM canonical_games g
                    LEFT JOIN canonical_teams ht ON ht.id=g.home_canonical_team_id
                    LEFT JOIN canonical_teams vt ON vt.id=g.visitor_canonical_team_id
                    ORDER BY COALESCE(g.datetime_utc, g.game_date) DESC LIMIT 5
                    """
                ).fetchall(),
            }

    @staticmethod
    def list_games(limit: int = 30) -> list[sqlite3.Row]:
        with get_connection() as conn:
            return execute(conn, 
                """
                SELECT g.*, ht.full_name AS home_team_name, ht.abbreviation AS home_abbr,
                       vt.full_name AS visitor_team_name, vt.abbreviation AS visitor_abbr
                FROM canonical_games g
                LEFT JOIN canonical_teams ht ON ht.id=g.home_canonical_team_id
                LEFT JOIN canonical_teams vt ON vt.id=g.visitor_canonical_team_id
                ORDER BY COALESCE(g.datetime_utc, g.game_date) DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()

    @staticmethod
    def list_teams(limit: int = 30) -> list[sqlite3.Row]:
        with get_connection() as conn:
            return execute(conn, "SELECT * FROM canonical_teams ORDER BY full_name ASC LIMIT ?", (limit,)).fetchall()

    @staticmethod
    def get_team(team_id: int):
        with get_connection() as conn:
            team = execute(conn, "SELECT * FROM canonical_teams WHERE id=?", (team_id,)).fetchone()
            if not team:
                return None
            recent_games = execute(conn, 
                """
                SELECT g.*, ht.abbreviation home_abbr, vt.abbreviation visitor_abbr
                FROM canonical_games g
                LEFT JOIN canonical_teams ht ON ht.id=g.home_canonical_team_id
                LEFT JOIN canonical_teams vt ON vt.id=g.visitor_canonical_team_id
                WHERE g.home_canonical_team_id=? OR g.visitor_canonical_team_id=?
                ORDER BY COALESCE(g.datetime_utc, g.game_date) DESC LIMIT 10
                """,
                (team_id, team_id),
            ).fetchall()
            return {"team": team, "recent_games": recent_games}

    @staticmethod
    def list_players(limit: int = 30) -> list[sqlite3.Row]:
        with get_connection() as conn:
            return execute(conn, 
                """SELECT p.*, t.abbreviation team_abbr FROM canonical_players p
                LEFT JOIN canonical_teams t ON t.id=p.canonical_team_id
                ORDER BY p.full_name ASC LIMIT ?""",
                (limit,),
            ).fetchall()

    @staticmethod
    def get_player(player_id: int):
        with get_connection() as conn:
            return execute(conn, 
                """SELECT p.*, t.full_name team_name, t.abbreviation team_abbr
                FROM canonical_players p LEFT JOIN canonical_teams t ON t.id=p.canonical_team_id
                WHERE p.id=?""",
                (player_id,),
            ).fetchone()
