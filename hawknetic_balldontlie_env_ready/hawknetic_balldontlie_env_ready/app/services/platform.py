from __future__ import annotations

from app.repositories import HistoricalRepository, NbaPlatformRepository, SubscriptionRepository


class PlatformService:
    @staticmethod
    def is_paid_user(subscription: dict | None) -> bool:
        if not subscription:
            return False
        return subscription["plan_code"] != "free"

    @staticmethod
    def dashboard_snapshot() -> dict:
        summary = NbaPlatformRepository.dashboard_summary()
        return {
            "teams": summary["tracked_teams"],
            "players": summary["tracked_players"],
            "games": summary["tracked_games"],
            "recent_games": NbaPlatformRepository.list_games(limit=5),
        }

    @staticmethod
    def list_games(limit: int = 30) -> list[dict]:
        return NbaPlatformRepository.list_games(limit=limit)

    @staticmethod
    def list_teams(limit: int = 30) -> list[dict]:
        teams = HistoricalRepository.list_teams(limit=limit)
        if teams:
            return teams
        from app.database import execute, get_connection
        with get_connection() as conn:
            return [dict(row) for row in execute(conn, "SELECT id, full_name, abbreviation, conference, division FROM bdl_teams ORDER BY full_name ASC LIMIT ?", (limit,)).fetchall()]

    @staticmethod
    def get_team(team_id: int):
        team = NbaPlatformRepository.get_team(team_id)
        if not team:
            return None
        return {"team": team, "recent_games": NbaPlatformRepository.list_games(limit=10)}

    @staticmethod
    def list_players(limit: int = 30) -> list[dict]:
        players = HistoricalRepository.list_players(limit=limit)
        if players:
            return players
        from app.database import execute, get_connection
        with get_connection() as conn:
            return [dict(row) for row in execute(conn, "SELECT p.*, t.abbreviation AS team_abbr FROM bdl_players p LEFT JOIN bdl_teams t ON t.bdl_team_id = p.bdl_team_id ORDER BY p.full_name ASC LIMIT ?", (limit,)).fetchall()]

    @staticmethod
    def get_player(player_id: int):
        return NbaPlatformRepository.get_player(player_id)
