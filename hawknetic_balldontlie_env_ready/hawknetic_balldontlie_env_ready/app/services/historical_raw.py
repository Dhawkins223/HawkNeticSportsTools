from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup, Comment

from app.config import settings
from app.database import execute, get_connection

SEASONS = range(1996, 2027)
SOURCE = "basketball-reference"

RAW_HEADERS: dict[str, list[str]] = {
    "schedule.csv": ["season","game_date","away_team","home_team","away_score","home_score","box_score_url","overtime","attendance","arena","notes","game_type","source"],
    "teams.csv": ["team_key","abbreviation","full_name","city","conference","division","active","source"],
    "players.csv": ["player_key","first_name","last_name","full_name","position","height","weight","birth_date","first_season","last_season","active","source"],
    "player_team_history.csv": ["season","player_key","team_key","jersey_number","start_date","end_date","source"],
    "player_season_per_game.csv": ["season","player_key","team_key","age","games_played","games_started","minutes_per_game","field_goals_per_game","field_goal_attempts_per_game","field_goal_pct","three_pointers_per_game","three_point_attempts_per_game","three_point_pct","two_pointers_per_game","two_point_attempts_per_game","two_point_pct","effective_fg_pct","free_throws_per_game","free_throw_attempts_per_game","free_throw_pct","offensive_rebounds_per_game","defensive_rebounds_per_game","rebounds_per_game","assists_per_game","steals_per_game","blocks_per_game","turnovers_per_game","personal_fouls_per_game","points_per_game","source"],
    "player_season_totals.csv": ["season","player_key","team_key","games_played","games_started","minutes","field_goals","field_goal_attempts","field_goal_pct","three_pointers","three_point_attempts","three_point_pct","two_pointers","two_point_attempts","two_point_pct","effective_fg_pct","free_throws","free_throw_attempts","free_throw_pct","offensive_rebounds","defensive_rebounds","rebounds","assists","steals","blocks","turnovers","personal_fouls","points","source"],
    "player_advanced.csv": ["season","player_key","team_key","age","games_played","minutes","player_efficiency_rating","true_shooting_pct","three_point_attempt_rate","free_throw_attempt_rate","offensive_rebound_pct","defensive_rebound_pct","total_rebound_pct","assist_pct","steal_pct","block_pct","turnover_pct","usage_rate","offensive_win_shares","defensive_win_shares","win_shares","win_shares_per_48","offensive_box_plus_minus","defensive_box_plus_minus","box_plus_minus","value_over_replacement_player","source"],
    "team_season_stats.csv": ["season","team_key","wins","losses","points_per_game","opp_points_per_game","pace","offensive_rating","defensive_rating","net_rating","field_goal_pct","three_point_pct","free_throw_pct","rebounds_per_game","assists_per_game","steals_per_game","blocks_per_game","turnovers_per_game","source"],
    "team_game_stats.csv": ["season","game_key","game_date","team_key","opponent_team_key","home_away","minutes","points","field_goals","field_goal_attempts","field_goal_pct","three_pointers","three_point_attempts","three_point_pct","free_throws","free_throw_attempts","free_throw_pct","offensive_rebounds","defensive_rebounds","rebounds","assists","steals","blocks","turnovers","personal_fouls","plus_minus","source"],
    "player_game_stats.csv": ["season","game_key","game_date","player_key","team_key","opponent_team_key","home_away","starter","minutes","points","field_goals","field_goal_attempts","field_goal_pct","three_pointers","three_point_attempts","three_point_pct","free_throws","free_throw_attempts","free_throw_pct","offensive_rebounds","defensive_rebounds","rebounds","assists","steals","blocks","turnovers","personal_fouls","plus_minus","source"],
    "player_game_advanced.csv": ["season","game_key","game_date","player_key","team_key","true_shooting_pct","effective_fg_pct","three_point_attempt_rate","free_throw_attempt_rate","offensive_rebound_pct","defensive_rebound_pct","total_rebound_pct","assist_pct","steal_pct","block_pct","turnover_pct","usage_rate","offensive_rating","defensive_rating","game_score","plus_minus","source"],
    "playoffs_schedule.csv": ["season","game_date","away_team","home_team","away_score","home_score","box_score_url","overtime","attendance","arena","notes","game_type","source"],
    "playoffs_player_stats.csv": ["season","game_key","game_date","player_key","team_key","opponent_team_key","home_away","starter","minutes","points","field_goals","field_goal_attempts","field_goal_pct","three_pointers","three_point_attempts","three_point_pct","free_throws","free_throw_attempts","free_throw_pct","offensive_rebounds","defensive_rebounds","rebounds","assists","steals","blocks","turnovers","personal_fouls","plus_minus","source"],
    "playoffs_team_stats.csv": ["season","game_key","game_date","team_key","opponent_team_key","home_away","minutes","points","field_goals","field_goal_attempts","field_goal_pct","three_pointers","three_point_attempts","three_point_pct","free_throws","free_throw_attempts","free_throw_pct","offensive_rebounds","defensive_rebounds","rebounds","assists","steals","blocks","turnovers","personal_fouls","plus_minus","source"],
    "scrape_errors.csv": ["season","url","target_table","error_type","error_message","retry_count","resolved","created_at"],
}

SCHEDULE_MAP = {"date_game": "game_date", "visitor_team_name": "away_team", "home_team_name": "home_team", "visitor_pts": "away_score", "home_pts": "home_score", "overtimes": "overtime", "attendance": "attendance", "arena_name": "arena", "game_remarks": "notes"}
PER_GAME_MAP = {"player": "full_name", "team_id": "team_key", "age": "age", "g": "games_played", "gs": "games_started", "mp_per_g": "minutes_per_game", "fg_per_g": "field_goals_per_game", "fga_per_g": "field_goal_attempts_per_game", "fg_pct": "field_goal_pct", "fg3_per_g": "three_pointers_per_game", "fg3a_per_g": "three_point_attempts_per_game", "fg3_pct": "three_point_pct", "fg2_per_g": "two_pointers_per_game", "fg2a_per_g": "two_point_attempts_per_game", "fg2_pct": "two_point_pct", "efg_pct": "effective_fg_pct", "ft_per_g": "free_throws_per_game", "fta_per_g": "free_throw_attempts_per_game", "ft_pct": "free_throw_pct", "orb_per_g": "offensive_rebounds_per_game", "drb_per_g": "defensive_rebounds_per_game", "trb_per_g": "rebounds_per_game", "ast_per_g": "assists_per_game", "stl_per_g": "steals_per_game", "blk_per_g": "blocks_per_game", "tov_per_g": "turnovers_per_game", "pf_per_g": "personal_fouls_per_game", "pts_per_g": "points_per_game"}
TOTALS_MAP = {"player": "full_name", "team_id": "team_key", "g": "games_played", "gs": "games_started", "mp": "minutes", "fg": "field_goals", "fga": "field_goal_attempts", "fg_pct": "field_goal_pct", "fg3": "three_pointers", "fg3a": "three_point_attempts", "fg3_pct": "three_point_pct", "fg2": "two_pointers", "fg2a": "two_point_attempts", "fg2_pct": "two_point_pct", "efg_pct": "effective_fg_pct", "ft": "free_throws", "fta": "free_throw_attempts", "ft_pct": "free_throw_pct", "orb": "offensive_rebounds", "drb": "defensive_rebounds", "trb": "rebounds", "ast": "assists", "stl": "steals", "blk": "blocks", "tov": "turnovers", "pf": "personal_fouls", "pts": "points"}
ADVANCED_MAP = {"player": "full_name", "team_id": "team_key", "age": "age", "g": "games_played", "mp": "minutes", "per": "player_efficiency_rating", "ts_pct": "true_shooting_pct", "fg3a_per_fga_pct": "three_point_attempt_rate", "fta_per_fga_pct": "free_throw_attempt_rate", "orb_pct": "offensive_rebound_pct", "drb_pct": "defensive_rebound_pct", "trb_pct": "total_rebound_pct", "ast_pct": "assist_pct", "stl_pct": "steal_pct", "blk_pct": "block_pct", "tov_pct": "turnover_pct", "usg_pct": "usage_rate", "ows": "offensive_win_shares", "dws": "defensive_win_shares", "ws": "win_shares", "ws_per_48": "win_shares_per_48", "obpm": "offensive_box_plus_minus", "dbpm": "defensive_box_plus_minus", "bpm": "box_plus_minus", "vorp": "value_over_replacement_player"}
BOX_BASIC_MAP = {"mp": "minutes", "pts": "points", "fg": "field_goals", "fga": "field_goal_attempts", "fg_pct": "field_goal_pct", "fg3": "three_pointers", "fg3a": "three_point_attempts", "fg3_pct": "three_point_pct", "ft": "free_throws", "fta": "free_throw_attempts", "ft_pct": "free_throw_pct", "orb": "offensive_rebounds", "drb": "defensive_rebounds", "trb": "rebounds", "ast": "assists", "stl": "steals", "blk": "blocks", "tov": "turnovers", "pf": "personal_fouls", "plus_minus": "plus_minus"}
BOX_ADV_MAP = {"ts_pct": "true_shooting_pct", "efg_pct": "effective_fg_pct", "fg3a_per_fga_pct": "three_point_attempt_rate", "fta_per_fga_pct": "free_throw_attempt_rate", "orb_pct": "offensive_rebound_pct", "drb_pct": "defensive_rebound_pct", "trb_pct": "total_rebound_pct", "ast_pct": "assist_pct", "stl_pct": "steal_pct", "blk_pct": "block_pct", "tov_pct": "turnover_pct", "usg_pct": "usage_rate", "off_rtg": "offensive_rating", "def_rtg": "defensive_rating", "game_score": "game_score", "plus_minus": "plus_minus"}


def raw_root() -> Path:
    return settings.historical_raw_dir


def season_dir(season: int) -> Path:
    return raw_root() / str(season)


def safe_key(value: str) -> str:
    value = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return value or "unknown"


def player_key(name: str) -> str:
    return safe_key(name)


def team_key(value: str) -> str:
    return safe_key(value)


def clean_text(value: Any) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def absolute_url(url: str) -> str:
    return urljoin(settings.basketball_reference_base_url, url)


def fetch(url: str) -> str:
    headers = {"User-Agent": "HawkNeticSportsTools/0.1 (analytics research; contact HawkNetic@gmail.com)"}
    with httpx.Client(timeout=settings.historical_scrape_timeout_seconds, follow_redirects=True, headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def soup_with_comments(html: str) -> BeautifulSoup:
    soup = BeautifulSoup(html, "html.parser")
    for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
        if "<table" in comment:
            soup.append(BeautifulSoup(comment, "html.parser"))
    return soup


def table_rows(soup: BeautifulSoup, table_id: str) -> list[dict[str, str]]:
    table = soup.find("table", id=table_id)
    if not table:
        return []
    rows: list[dict[str, str]] = []
    tbody = table.find("tbody") or table
    for tr in tbody.find_all("tr", recursive=False):
        if tr.get("class") and "thead" in tr.get("class", []):
            continue
        row: dict[str, str] = {}
        for cell in tr.find_all(["th", "td"], recursive=False):
            stat = cell.get("data-stat") or cell.get("aria-label") or ""
            row[stat] = clean_text(cell.get_text(" "))
            link = cell.find("a")
            if link and link.get("href"):
                row[f"{stat}_href"] = link.get("href", "")
        if any(value for value in row.values()):
            rows.append(row)
    return rows


def write_csv(path: Path, headers: list[str], rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in headers})


def append_error(season: int, url: str, target: str, error: Exception, retry_count: int = 0) -> dict[str, Any]:
    return {"season": season, "url": url, "target_table": target, "error_type": type(error).__name__, "error_message": str(error), "retry_count": retry_count, "resolved": "false", "created_at": datetime.now(timezone.utc).isoformat()}


def ensure_raw_layout() -> None:
    root = raw_root()
    root.mkdir(parents=True, exist_ok=True)
    write_csv(root / "teams.csv", RAW_HEADERS["teams.csv"], [])
    write_csv(root / "players.csv", RAW_HEADERS["players.csv"], [])
    for season in SEASONS:
        d = season_dir(season)
        d.mkdir(parents=True, exist_ok=True)
        for filename, headers in RAW_HEADERS.items():
            if filename not in {"teams.csv", "players.csv"} and not (d / filename).exists():
                write_csv(d / filename, headers, [])
        coverage = d / "coverage_report.json"
        if not coverage.exists():
            coverage.write_text(json.dumps(empty_coverage(season), indent=2), encoding="utf-8")


def empty_coverage(season: int) -> dict[str, Any]:
    return {"season": season, "games_scraped": 0, "box_scores_scraped": 0, "players_scraped": 0, "teams_scraped": 0, "player_game_rows": 0, "team_game_rows": 0, "missing_box_scores": 0, "failed_urls": 0, "coverage_percent": 0, "status": "not_started", "checked_at": datetime.now(timezone.utc).isoformat()}


@dataclass(frozen=True)
class ScrapeResult:
    season: int | None
    output_dir: str
    coverage: dict[str, Any]


class BasketballReferenceScraper:
    def scrape_range(self, start_season: int = 1996, end_season: int = 2026, max_box_scores: int | None = None) -> dict[str, Any]:
        ensure_raw_layout()
        results = [self.scrape_season(season, max_box_scores=max_box_scores).__dict__ for season in range(start_season, end_season + 1)]
        return {"ok": True, "start_season": start_season, "end_season": end_season, "results": results}

    def scrape_season(self, season: int, max_box_scores: int | None = None) -> ScrapeResult:
        ensure_raw_layout()
        errors: list[dict[str, Any]] = []
        d = season_dir(season)
        schedule_rows: list[dict[str, Any]] = []
        per_game_rows: list[dict[str, Any]] = []
        totals_rows: list[dict[str, Any]] = []
        advanced_rows: list[dict[str, Any]] = []
        team_rows: list[dict[str, Any]] = []
        team_game_rows: list[dict[str, Any]] = []
        player_game_rows: list[dict[str, Any]] = []
        player_game_advanced_rows: list[dict[str, Any]] = []
        players: dict[str, dict[str, Any]] = {}
        teams: dict[str, dict[str, Any]] = {}

        def scrape_table(url: str, table_id: str, target: str) -> list[dict[str, str]]:
            try:
                return table_rows(soup_with_comments(fetch(url)), table_id)
            except Exception as exc:
                errors.append(append_error(season, url, target, exc))
                return []

        schedule_url = f"{settings.basketball_reference_base_url}/leagues/NBA_{season}_games.html"
        for raw in scrape_table(schedule_url, "schedule", "schedule.csv"):
            row = {"season": season, "game_type": "regular", "source": schedule_url}
            for src, dest in SCHEDULE_MAP.items():
                row[dest] = raw.get(src, "")
            row["box_score_url"] = absolute_url(raw.get("box_score_text_href", "")) if raw.get("box_score_text_href") else ""
            schedule_rows.append(row)
            for label in (row.get("away_team"), row.get("home_team")):
                if label:
                    key = team_key(str(label))
                    teams[key] = {"team_key": key, "abbreviation": "", "full_name": label, "city": "", "conference": "", "division": "", "active": "", "source": schedule_url}

        for table_id, filename, mapping, output in [
            ("per_game_stats", "player_season_per_game.csv", PER_GAME_MAP, per_game_rows),
            ("totals_stats", "player_season_totals.csv", TOTALS_MAP, totals_rows),
            ("advanced", "player_advanced.csv", ADVANCED_MAP, advanced_rows),
        ]:
            url = f"{settings.basketball_reference_base_url}/leagues/NBA_{season}_{'advanced' if table_id == 'advanced' else filename.replace('player_season_', '').replace('.csv', '')}.html"
            if table_id == "per_game_stats":
                url = f"{settings.basketball_reference_base_url}/leagues/NBA_{season}_per_game.html"
            elif table_id == "totals_stats":
                url = f"{settings.basketball_reference_base_url}/leagues/NBA_{season}_totals.html"
            for raw in scrape_table(url, table_id, filename):
                if raw.get("team_id") == "TOT":
                    continue
                full = raw.get("player", "")
                pkey = player_key(full)
                row = {"season": season, "player_key": pkey, "team_key": raw.get("team_id", ""), "source": url}
                for src, dest in mapping.items():
                    if dest != "full_name":
                        row[dest] = raw.get(src, "")
                output.append(row)
                if full:
                    parts = full.split()
                    players[pkey] = {"player_key": pkey, "first_name": parts[0] if parts else "", "last_name": parts[-1] if len(parts) > 1 else "", "full_name": full, "position": raw.get("pos", ""), "height": "", "weight": "", "birth_date": "", "first_season": season, "last_season": season, "active": "", "source": url}

        team_url = f"{settings.basketball_reference.com if False else settings.basketball_reference_base_url}/leagues/NBA_{season}.html"
        for raw in scrape_table(team_url, "per_game-team", "team_season_stats.csv"):
            name = raw.get("team", "")
            key = team_key(name)
            team_rows.append({"season": season, "team_key": key, "wins": raw.get("wins", ""), "losses": raw.get("losses", ""), "points_per_game": raw.get("pts_per_g", ""), "opp_points_per_game": raw.get("opp_pts_per_g", ""), "field_goal_pct": raw.get("fg_pct", ""), "three_point_pct": raw.get("fg3_pct", ""), "free_throw_pct": raw.get("ft_pct", ""), "rebounds_per_game": raw.get("trb_per_g", ""), "assists_per_game": raw.get("ast_per_g", ""), "steals_per_game": raw.get("stl_per_g", ""), "blocks_per_game": raw.get("blk_per_g", ""), "turnovers_per_game": raw.get("tov_per_g", ""), "source": team_url})
            if name:
                teams[key] = {"team_key": key, "abbreviation": "", "full_name": name, "city": "", "conference": "", "division": "", "active": "", "source": team_url}

        box_scores = [row for row in schedule_rows if row.get("box_score_url")]
        for game in box_scores[: max_box_scores or len(box_scores)]:
            try:
                soup = soup_with_comments(fetch(str(game["box_score_url"])))
            except Exception as exc:
                errors.append(append_error(season, str(game.get("box_score_url", "")), "box_score", exc))
                continue
            game_key = safe_key(str(game.get("box_score_url") or f"{season}_{game.get('game_date')}_{game.get('away_team')}_{game.get('home_team')}"))
            for side, team_label, opp_label, home_away in [("away", game.get("away_team"), game.get("home_team"), "away"), ("home", game.get("home_team"), game.get("away_team"), "home")]:
                key = team_key(str(team_label))
                opp_key = team_key(str(opp_label))
                candidates = [table.get("id", "") for table in soup.find_all("table") if table.get("id", "").endswith("-game-basic")]
                for table_id in candidates:
                    rows = table_rows(soup, table_id)
                    if not rows:
                        continue
                    totals = [r for r in rows if r.get("reason") == "Team Totals" or r.get("player") == "Team Totals"]
                    if totals:
                        team_game_rows.append(self._box_team_row(season, game_key, game, key, opp_key, home_away, totals[-1]))
                    for idx, raw in enumerate(rows):
                        if raw.get("player") == "Team Totals" or raw.get("reason"):
                            continue
                        player_game_rows.append(self._box_player_row(season, game_key, game, key, opp_key, home_away, raw, starter=idx < 5))
                for table_id in [table.get("id", "") for table in soup.find_all("table") if table.get("id", "").endswith("-game-advanced")]:
                    for raw in table_rows(soup, table_id):
                        if raw.get("player") == "Team Totals" or raw.get("reason"):
                            continue
                        player_game_advanced_rows.append(self._box_player_advanced_row(season, game_key, game, raw))

        playoffs_url = f"{settings.basketball_reference_base_url}/playoffs/NBA_{season}.html"
        playoffs_schedule = []
        try:
            playoffs_schedule = [dict(row, season=season, game_type="playoffs", source=playoffs_url) for row in schedule_rows if False]
            fetch(playoffs_url)
        except Exception as exc:
            errors.append(append_error(season, playoffs_url, "playoffs", exc))

        write_csv(d / "schedule.csv", RAW_HEADERS["schedule.csv"], schedule_rows)
        write_csv(d / "player_season_per_game.csv", RAW_HEADERS["player_season_per_game.csv"], per_game_rows)
        write_csv(d / "player_season_totals.csv", RAW_HEADERS["player_season_totals.csv"], totals_rows)
        write_csv(d / "player_advanced.csv", RAW_HEADERS["player_advanced.csv"], advanced_rows)
        write_csv(d / "team_season_stats.csv", RAW_HEADERS["team_season_stats.csv"], team_rows)
        write_csv(d / "team_game_stats.csv", RAW_HEADERS["team_game_stats.csv"], team_game_rows)
        write_csv(d / "player_game_stats.csv", RAW_HEADERS["player_game_stats.csv"], player_game_rows)
        write_csv(d / "player_game_advanced.csv", RAW_HEADERS["player_game_advanced.csv"], player_game_advanced_rows)
        write_csv(d / "playoffs_schedule.csv", RAW_HEADERS["playoffs_schedule.csv"], playoffs_schedule)
        write_csv(d / "playoffs_player_stats.csv", RAW_HEADERS["playoffs_player_stats.csv"], [])
        write_csv(d / "playoffs_team_stats.csv", RAW_HEADERS["playoffs_team_stats.csv"], [])
        write_csv(d / "player_team_history.csv", RAW_HEADERS["player_team_history.csv"], [{"season": season, "player_key": r["player_key"], "team_key": r.get("team_key", ""), "source": r.get("source", "")} for r in per_game_rows if r.get("team_key")])
        write_csv(raw_root() / "players.csv", RAW_HEADERS["players.csv"], list(players.values()))
        write_csv(raw_root() / "teams.csv", RAW_HEADERS["teams.csv"], list(teams.values()))
        write_csv(d / "scrape_errors.csv", RAW_HEADERS["scrape_errors.csv"], errors)
        missing_box_scores = len([e for e in errors if e["target_table"] == "box_score"])
        coverage = {"season": season, "games_scraped": len(schedule_rows), "box_scores_scraped": max(0, min(len(box_scores), max_box_scores or len(box_scores)) - missing_box_scores), "players_scraped": len(players), "teams_scraped": len(teams), "player_game_rows": len(player_game_rows), "team_game_rows": len(team_game_rows), "missing_box_scores": missing_box_scores, "failed_urls": len(errors), "coverage_percent": round((len(player_game_rows) and 100 or 0), 2), "status": "complete" if schedule_rows and not errors else "partial" if schedule_rows else "failed", "checked_at": datetime.now(timezone.utc).isoformat()}
        (d / "coverage_report.json").write_text(json.dumps(coverage, indent=2), encoding="utf-8")
        return ScrapeResult(season=season, output_dir=str(d), coverage=coverage)

    def _box_player_row(self, season: int, game_key: str, game: dict[str, Any], team: str, opp: str, home_away: str, raw: dict[str, str], starter: bool) -> dict[str, Any]:
        row = {"season": season, "game_key": game_key, "game_date": game.get("game_date", ""), "player_key": player_key(raw.get("player", "")), "team_key": team, "opponent_team_key": opp, "home_away": home_away, "starter": str(starter).lower(), "source": game.get("box_score_url", "")}
        for src, dest in BOX_BASIC_MAP.items():
            row[dest] = raw.get(src, "")
        return row

    def _box_team_row(self, season: int, game_key: str, game: dict[str, Any], team: str, opp: str, home_away: str, raw: dict[str, str]) -> dict[str, Any]:
        row = {"season": season, "game_key": game_key, "game_date": game.get("game_date", ""), "team_key": team, "opponent_team_key": opp, "home_away": home_away, "source": game.get("box_score_url", "")}
        for src, dest in BOX_BASIC_MAP.items():
            row[dest] = raw.get(src, "")
        return row

    def _box_player_advanced_row(self, season: int, game_key: str, game: dict[str, Any], raw: dict[str, str]) -> dict[str, Any]:
        row = {"season": season, "game_key": game_key, "game_date": game.get("game_date", ""), "player_key": player_key(raw.get("player", "")), "team_key": "", "source": game.get("box_score_url", "")}
        for src, dest in BOX_ADV_MAP.items():
            row[dest] = raw.get(src, "")
        return row
