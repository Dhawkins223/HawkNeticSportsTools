from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database import execute, get_connection
from app.services.historical_raw import RAW_HEADERS, SEASONS, raw_root, season_dir, safe_key


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def as_int(value: Any) -> int | None:
    try:
        text = str(value or "").replace(",", "").strip()
        return int(float(text)) if text else None
    except ValueError:
        return None


def as_float(value: Any) -> float | None:
    try:
        text = str(value or "").replace(",", "").strip()
        return float(text) if text else None
    except ValueError:
        return None


class HistoricalImporter:
    def import_range(self, start_season: int = 1996, end_season: int = 2026) -> dict[str, Any]:
        results = [self.import_season(season) for season in range(start_season, end_season + 1)]
        return {"ok": True, "start_season": start_season, "end_season": end_season, "results": results}

    def import_season(self, season: int) -> dict[str, Any]:
        d = season_dir(season)
        import_errors: list[dict[str, Any]] = []
        counts = {"teams": 0, "players": 0, "games": 0, "player_game_rows": 0, "team_game_rows": 0, "season_rows": 0, "advanced_rows": 0}
        try:
            with get_connection() as conn:
                counts["teams"] += self._import_teams(conn, read_csv(raw_root() / "teams.csv"))
                counts["players"] += self._import_players(conn, read_csv(raw_root() / "players.csv"))
                counts["games"] += self._import_schedule(conn, season, read_csv(d / "schedule.csv"))
                for filename, entity_type in [("player_season_per_game.csv", "player_per_game"), ("player_season_totals.csv", "player_totals")]:
                    counts["season_rows"] += self._import_player_season(conn, season, read_csv(d / filename), entity_type)
                counts["advanced_rows"] += self._import_player_advanced(conn, season, read_csv(d / "player_advanced.csv"))
                counts["team_game_rows"] += self._import_team_games(conn, season, read_csv(d / "team_game_stats.csv"))
                counts["player_game_rows"] += self._import_player_games(conn, season, read_csv(d / "player_game_stats.csv"))
                coverage = self._write_coverage(conn, season, d, counts)
        except Exception as exc:
            import_errors.append({"season": season, "error_type": type(exc).__name__, "error_message": str(exc), "created_at": datetime.now(timezone.utc).isoformat()})
            raise
        return {"season": season, "counts": counts, "errors": import_errors, "coverage": coverage}

    def _team_id(self, conn: Any, key: str) -> int | None:
        row = execute(conn, "SELECT id FROM historical_teams WHERE team_key = ? OR external_id = ?", (key, key)).fetchone()
        return int(row["id"]) if row else None

    def _player_id(self, conn: Any, key: str) -> int | None:
        row = execute(conn, "SELECT id FROM historical_players WHERE player_key = ? OR external_id = ?", (key, key)).fetchone()
        return int(row["id"]) if row else None

    def _game_id(self, conn: Any, key: str) -> int | None:
        row = execute(conn, "SELECT id FROM historical_games WHERE game_key = ? OR external_id = ?", (key, key)).fetchone()
        return int(row["id"]) if row else None

    def _import_teams(self, conn: Any, rows: list[dict[str, str]]) -> int:
        for row in rows:
            key = row.get("team_key") or safe_key(row.get("full_name", ""))
            execute(conn, """
                INSERT INTO historical_teams(external_id, team_key, abbreviation, city, name, full_name, conference, division, active, source)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_id) DO UPDATE SET full_name=excluded.full_name, abbreviation=excluded.abbreviation, updated_at=CURRENT_TIMESTAMP
            """, (key, key, row.get("abbreviation"), row.get("city"), row.get("full_name"), row.get("full_name"), row.get("conference"), row.get("division"), as_int(row.get("active")) or 1, row.get("source")))
        return len(rows)

    def _import_players(self, conn: Any, rows: list[dict[str, str]]) -> int:
        for row in rows:
            key = row.get("player_key") or safe_key(row.get("full_name", ""))
            execute(conn, """
                INSERT INTO historical_players(external_id, player_key, first_name, last_name, full_name, position, height, weight, college, country, birth_date, first_season, last_season, active, source)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_id) DO UPDATE SET full_name=excluded.full_name, last_season=excluded.last_season, updated_at=CURRENT_TIMESTAMP
            """, (key, key, row.get("first_name"), row.get("last_name"), row.get("full_name"), row.get("position"), row.get("height"), row.get("weight"), "", "", row.get("birth_date"), as_int(row.get("first_season")), as_int(row.get("last_season")), as_int(row.get("active")) or 1, row.get("source")))
        return len(rows)

    def _import_schedule(self, conn: Any, season: int, rows: list[dict[str, str]]) -> int:
        for row in rows:
            key = safe_key(row.get("box_score_url") or f"{season}_{row.get('game_date')}_{row.get('away_team')}_{row.get('home_team')}")
            away_key = safe_key(row.get("away_team", ""))
            home_key = safe_key(row.get("home_team", ""))
            execute(conn, """
                INSERT INTO historical_games(external_id, game_key, season, game_date, away_team_key, home_team_key, away_team_id, home_team_id, away_score, home_score, status, source, source_url, game_type, attendance, arena, notes, overtime)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'final', ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(external_id) DO UPDATE SET away_score=excluded.away_score, home_score=excluded.home_score, updated_at=CURRENT_TIMESTAMP
            """, (key, key, season, row.get("game_date"), away_key, home_key, self._team_id(conn, away_key), self._team_id(conn, home_key), as_int(row.get("away_score")), as_int(row.get("home_score")), row.get("source"), row.get("box_score_url"), row.get("game_type"), as_int(row.get("attendance")), row.get("arena"), row.get("notes"), row.get("overtime")))
        return len(rows)

    def _import_player_season(self, conn: Any, season: int, rows: list[dict[str, str]], entity_type: str) -> int:
        for row in rows:
            key = row.get("player_key") or safe_key(row.get("full_name", ""))
            player_id = self._player_id(conn, key) or 0
            stats = {k: v for k, v in row.items() if k not in {"season", "player_key", "team_key", "source"}}
            execute(conn, """
                INSERT INTO historical_season_stats(season, entity_type, entity_id, player_key, team_key, games_played, stats_json, source)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(season, entity_type, entity_id) DO UPDATE SET stats_json=excluded.stats_json, updated_at=CURRENT_TIMESTAMP
            """, (season, entity_type, player_id, key, row.get("team_key"), as_int(row.get("games_played")) or 0, json.dumps(stats, separators=(",", ":")), row.get("source")))
        return len(rows)

    def _import_player_advanced(self, conn: Any, season: int, rows: list[dict[str, str]]) -> int:
        for row in rows:
            key = row.get("player_key") or safe_key(row.get("full_name", ""))
            player_id = self._player_id(conn, key) or 0
            execute(conn, """
                INSERT INTO historical_player_ratings(season, player_id, player_key, team_key, rating_name, rating_value, model_version, player_efficiency_rating, true_shooting_pct, usage_rate, source)
                VALUES(?, ?, ?, ?, 'basketball_reference_advanced', ?, 'raw', ?, ?, ?, ?)
                ON CONFLICT(season, player_id, rating_name, model_version) DO UPDATE SET rating_value=excluded.rating_value, updated_at=CURRENT_TIMESTAMP
            """, (season, player_id, key, row.get("team_key"), as_float(row.get("player_efficiency_rating")) or 0, as_float(row.get("player_efficiency_rating")), as_float(row.get("true_shooting_pct")), as_float(row.get("usage_rate")), row.get("source")))
        return len(rows)

    def _import_team_games(self, conn: Any, season: int, rows: list[dict[str, str]]) -> int:
        for row in rows:
            game_id = self._game_id(conn, row.get("game_key", "")) or 0
            team_id = self._team_id(conn, row.get("team_key", "")) or 0
            execute(conn, """
                INSERT INTO historical_team_game_stats(season, game_id, game_key, game_date, team_id, team_key, opponent_team_key, home_away, minutes, points, rebounds, assists, steals, blocks, turnovers, personal_fouls, source)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, team_id) DO UPDATE SET points=excluded.points, updated_at=CURRENT_TIMESTAMP
            """, (season, game_id, row.get("game_key"), row.get("game_date"), team_id, row.get("team_key"), row.get("opponent_team_key"), row.get("home_away"), as_float(row.get("minutes")), as_int(row.get("points")), as_int(row.get("rebounds")), as_int(row.get("assists")), as_int(row.get("steals")), as_int(row.get("blocks")), as_int(row.get("turnovers")), as_int(row.get("personal_fouls")), row.get("source")))
        return len(rows)

    def _import_player_games(self, conn: Any, season: int, rows: list[dict[str, str]]) -> int:
        for row in rows:
            game_id = self._game_id(conn, row.get("game_key", "")) or 0
            player_id = self._player_id(conn, row.get("player_key", "")) or 0
            team_id = self._team_id(conn, row.get("team_key", "")) or 0
            execute(conn, """
                INSERT INTO historical_player_game_stats(season, game_id, game_key, game_date, player_id, player_key, team_id, team_key, opponent_team_key, home_away, starter, minutes, points, rebounds, assists, steals, blocks, turnovers, personal_fouls, source)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(game_id, player_id) DO UPDATE SET points=excluded.points, updated_at=CURRENT_TIMESTAMP
            """, (season, game_id, row.get("game_key"), row.get("game_date"), player_id, row.get("player_key"), team_id, row.get("team_key"), row.get("opponent_team_key"), row.get("home_away"), 1 if row.get("starter") == "true" else 0, as_float(row.get("minutes")), as_int(row.get("points")), as_int(row.get("rebounds")), as_int(row.get("assists")), as_int(row.get("steals")), as_int(row.get("blocks")), as_int(row.get("turnovers")), as_int(row.get("personal_fouls")), row.get("source")))
        return len(rows)

    def _write_coverage(self, conn: Any, season: int, d: Path, counts: dict[str, int]) -> dict[str, Any]:
        raw_coverage = {}
        coverage_path = d / "coverage_report.json"
        if coverage_path.exists():
            raw_coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        status = "complete" if counts["games"] and counts["player_game_rows"] and counts["team_game_rows"] else "incomplete"
        coverage = {**raw_coverage, "season": season, "games_scraped": raw_coverage.get("games_scraped", counts["games"]), "player_game_rows": counts["player_game_rows"], "team_game_rows": counts["team_game_rows"], "status": status, "last_import_at": datetime.now(timezone.utc).isoformat()}
        execute(conn, """
            INSERT INTO data_quality_reports(report_type, season, status, expected_records, actual_records, details_json, games_scraped, box_scores_scraped, players_scraped, teams_scraped, player_game_rows, team_game_rows, missing_box_scores, failed_urls, coverage_percent, checked_at, last_scrape_at, last_import_at)
            VALUES('historical_season_coverage', ?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(report_type, season) DO UPDATE SET status=excluded.status, actual_records=excluded.actual_records, details_json=excluded.details_json, player_game_rows=excluded.player_game_rows, team_game_rows=excluded.team_game_rows, coverage_percent=excluded.coverage_percent, updated_at=CURRENT_TIMESTAMP, last_import_at=excluded.last_import_at
        """, (season, status, counts["games"], json.dumps(coverage, separators=(",", ":")), coverage.get("games_scraped", 0), coverage.get("box_scores_scraped", 0), coverage.get("players_scraped", counts["players"]), coverage.get("teams_scraped", counts["teams"]), counts["player_game_rows"], counts["team_game_rows"], coverage.get("missing_box_scores", 0), coverage.get("failed_urls", 0), coverage.get("coverage_percent", 0), coverage.get("checked_at"), coverage.get("checked_at"), coverage["last_import_at"]))
        return coverage
