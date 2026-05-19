from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import database_engine, execute, get_connection, init_db
from app.services.historical_importer import HistoricalImporter
from app.services.historical_raw import BasketballReferenceScraper, raw_root, season_dir
from app.services.raw_imports import RawImportTracker


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Railway-safe historical backfill runner")
    parser.add_argument("--season", type=int, help="Single season to process (1996-2026).")
    parser.add_argument("--start-season", type=int, help="Season range start (1996-2026).")
    parser.add_argument("--end-season", type=int, help="Season range end (1996-2026).")
    parser.add_argument("--scrape-only", action="store_true", help="Only scrape raw files.")
    parser.add_argument("--import-only", action="store_true", help="Only import existing raw files.")
    parser.add_argument("--skip-existing", action="store_true", help="Skip season when historical_games already has rows.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned work without fetching or writing data.")
    parser.add_argument("--strict", action="store_true", help="Fail season on suspiciously low imports or unresolved IDs.")
    parser.add_argument("--sleep-seconds", type=float, default=0.0, help="Pause between seasons.")
    args = parser.parse_args(argv)

    if args.scrape_only and args.import_only:
        parser.error("Cannot use --scrape-only and --import-only together.")
    if args.season is not None and (args.start_season is not None or args.end_season is not None):
        parser.error("Use either --season or --start-season/--end-season.")
    if args.season is None and (args.start_season is None or args.end_season is None):
        parser.error("Provide --season or both --start-season and --end-season.")

    start = args.season if args.season is not None else args.start_season
    end = args.season if args.season is not None else args.end_season
    if start is None or end is None:
        parser.error("Could not resolve season inputs.")
    if start < 1996 or end > 2026 or end < start:
        parser.error("Season range must be within 1996..2026 and start <= end.")
    if args.sleep_seconds < 0:
        parser.error("--sleep-seconds must be >= 0.")
    return args


def _mode_label(args: argparse.Namespace) -> str:
    if args.scrape_only:
        return "scrape_only"
    if args.import_only:
        return "import_only"
    return "scrape_import"


def _season_game_count(season: int) -> int:
    with get_connection() as conn:
        return int(execute(conn, "SELECT COUNT(*) AS c FROM historical_games WHERE season = ?", (season,)).fetchone()["c"])


def _create_job(season: int, mode: str) -> int:
    started_at = _utc_now()
    with get_connection() as conn:
        cur = execute(conn, """
            INSERT INTO historical_backfill_jobs(season, mode, status, started_at)
            VALUES(?, ?, 'running', ?)
        """, (season, mode, started_at))
        return int(cur.lastrowid)


def _finalize_job(job_id: int, status: str, counts: dict[str, int], error_message: str | None = None) -> None:
    with get_connection() as conn:
        execute(conn, """
            UPDATE historical_backfill_jobs
               SET status = ?,
                   finished_at = ?,
                   games_count = ?,
                   players_count = ?,
                   teams_count = ?,
                   player_game_stats_count = ?,
                   team_game_stats_count = ?,
                   error_message = ?,
                   updated_at = CURRENT_TIMESTAMP
             WHERE id = ?
        """, (
            status,
            _utc_now(),
            int(counts.get("games", 0)),
            int(counts.get("players", 0)),
            int(counts.get("teams", 0)),
            int(counts.get("player_game_rows", 0)),
            int(counts.get("team_game_rows", 0)),
            error_message,
            job_id,
        ))


def _strict_validate(season: int, import_result: dict[str, Any]) -> None:
    counts = import_result.get("counts", {})
    suspicious = []
    if int(counts.get("games", 0)) < 10:
        suspicious.append(f"games_count too low ({counts.get('games', 0)})")
    if int(counts.get("player_game_rows", 0)) < 100:
        suspicious.append(f"player_game_rows too low ({counts.get('player_game_rows', 0)})")
    if int(counts.get("team_game_rows", 0)) < 10:
        suspicious.append(f"team_game_rows too low ({counts.get('team_game_rows', 0)})")

    with get_connection() as conn:
        unresolved_player = int(execute(conn, "SELECT COUNT(*) AS c FROM historical_player_game_stats WHERE season = ? AND (game_id = 0 OR player_id = 0 OR team_id = 0)", (season,)).fetchone()["c"])
        unresolved_team = int(execute(conn, "SELECT COUNT(*) AS c FROM historical_team_game_stats WHERE season = ? AND (game_id = 0 OR team_id = 0)", (season,)).fetchone()["c"])
    if unresolved_player > 0:
        suspicious.append(f"unresolved IDs in historical_player_game_stats: {unresolved_player}")
    if unresolved_team > 0:
        suspicious.append(f"unresolved IDs in historical_team_game_stats: {unresolved_team}")
    if suspicious:
        raise RuntimeError("; ".join(suspicious))


def run() -> int:
    init_db()
    args = parse_args()
    mode = _mode_label(args)
    start = args.season if args.season is not None else args.start_season
    end = args.season if args.season is not None else args.end_season
    assert start is not None and end is not None
    seasons = list(range(start, end + 1))
    if args.dry_run:
        print(json.dumps({"status": "dry_run", "engine": database_engine(), "seasons": seasons, "mode": mode, "skip_existing": args.skip_existing}))
        return 0
    scraper = BasketballReferenceScraper()
    failures = 0

    for idx, season in enumerate(seasons):
        if args.skip_existing and _season_game_count(season) > 0:
            print(json.dumps({"season": season, "status": "skipped", "reason": "existing historical_games rows found"}))
            continue

        season_started = time.monotonic()
        job_id = _create_job(season=season, mode=mode)
        raw_job_id = RawImportTracker.create_job(source="basketball_reference", season=season)
        importer = HistoricalImporter(raw_job_id=raw_job_id)
        counts = {"games": 0, "players": 0, "teams": 0, "player_game_rows": 0, "team_game_rows": 0}
        raw_payloads = 0
        try:
            if not args.import_only:
                print(json.dumps({"season": season, "phase": "scrape", "status": "started"}))
                scrape_result = scraper.scrape_season(season)
                print(json.dumps({"season": season, "phase": "scrape", "status": "completed", "coverage": scrape_result.coverage}))
            raw_payloads = RawImportTracker.store_historical_files(raw_job_id, season, season_dir(season), raw_root())
            print(json.dumps({"season": season, "phase": "raw_store", "status": "completed", "raw_payloads": raw_payloads}))

            if not args.scrape_only:
                print(json.dumps({"season": season, "phase": "import", "status": "started"}))
                import_result = importer.import_season(season)
                counts = import_result.get("counts", counts)
                if args.strict:
                    _strict_validate(season, import_result)
                print(json.dumps({"season": season, "phase": "import", "status": "completed", "counts": counts}))

            elapsed = round(time.monotonic() - season_started, 2)
            _finalize_job(job_id, "completed", counts)
            RawImportTracker.finish_job(raw_job_id, "completed", {
                "records_fetched": raw_payloads,
                "records_inserted": sum(int(value or 0) for value in counts.values()),
                "records_skipped": 0,
                "records_failed": 0,
            })
            print(json.dumps({"season": season, "status": "completed", "elapsed_seconds": elapsed, "counts": counts}))
        except Exception as exc:
            elapsed = round(time.monotonic() - season_started, 2)
            _finalize_job(job_id, "failed", counts, error_message=str(exc))
            RawImportTracker.log_error(raw_job_id, "basketball_reference", str(exc), season=season)
            RawImportTracker.finish_job(raw_job_id, "failed", {"records_fetched": raw_payloads, "records_failed": 1}, error_message=str(exc))
            print(json.dumps({"season": season, "status": "failed", "elapsed_seconds": elapsed, "error": str(exc)}))
            failures += 1

        if args.sleep_seconds and idx < len(seasons) - 1:
            time.sleep(args.sleep_seconds)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(run())
