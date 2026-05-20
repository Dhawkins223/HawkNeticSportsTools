from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings
from app.database import database_readiness, database_status, init_db, table_counts
from app.repositories import BdlRepository, MappingRepository
from app.services.balldontlie import BallDontLieService
from app.services.raw_imports import RawImportTracker


DEFAULT_PLAYER_SEARCHES = ("lebron", "curry", "durant", "tatum", "jokic", "doncic", "giannis", "shai")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap Railway PostgreSQL with real HawkNetic source data.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned work without writing provider data.")
    parser.add_argument("--skip-bdl", action="store_true", help="Skip Ball Don't Lie sync.")
    parser.add_argument("--season", type=int, default=date.today().year, help="Season to request for provider games.")
    parser.add_argument("--start-date", help="Optional start date for game sync, YYYY-MM-DD.")
    parser.add_argument("--end-date", help="Optional end date for game sync, YYYY-MM-DD.")
    parser.add_argument("--player-search", action="append", dest="player_searches", help="Player search term. Can be repeated.")
    parser.add_argument("--historical-season", type=int, help="Optionally run one Basketball-Reference historical season after BDL sync.")
    parser.add_argument("--skip-existing-historical", action="store_true", help="Pass --skip-existing to the historical backfill command.")
    return parser.parse_args(argv)


def _date_range(start: str, end: str | None) -> list[str]:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end) if end else start_date
    if end_date < start_date:
        raise ValueError("--end-date must be on or after --start-date.")
    days: list[str] = []
    current = start_date
    while current <= end_date:
        days.append(current.isoformat())
        current += timedelta(days=1)
    return days


async def _fetch(endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
    client = BallDontLieService.client()
    return await client._get(f"{client.base_url}/{endpoint}", params=params)


async def _sync_payload(endpoint: str, params: dict[str, Any], source: str, writer) -> dict[str, Any]:
    job_id = RawImportTracker.create_job(source=source, season=params.get("seasons[]") or params.get("season"))
    log_id = BdlRepository.start_log(resource=source, request=params)
    try:
        payload = await _fetch(endpoint, params)
        RawImportTracker.store_balldontlie_payload(job_id, endpoint, params, payload)
        items = payload.get("data", []) if isinstance(payload, dict) else []
        written = writer(items)
        mapped = 0
        if source == "balldontlie_teams":
            mapped = MappingRepository.auto_map_teams()
        elif source == "balldontlie_players":
            mapped = MappingRepository.auto_map_players()
        elif source == "balldontlie_games":
            mapped = MappingRepository.auto_map_games()
        BdlRepository.finish_log(log_id, "succeeded", records_read=len(items), records_written=written, response_excerpt=json.dumps(payload)[:500])
        RawImportTracker.finish_job(job_id, "completed", {"records_fetched": len(items), "records_inserted": written, "records_updated": mapped})
        return {"source": source, "job_id": job_id, "records_fetched": len(items), "records_written": written, "mapped": mapped}
    except Exception as exc:
        BdlRepository.finish_log(log_id, "failed", error_text=str(exc))
        RawImportTracker.log_error(job_id, source, str(exc))
        RawImportTracker.finish_job(job_id, "failed", {"records_failed": 1}, error_message=str(exc))
        return {"source": source, "job_id": job_id, "status": "failed", "error": str(exc)}


async def bootstrap_bdl(args: argparse.Namespace) -> list[dict[str, Any]]:
    if not settings.balldontlie_api_key:
        return [{"source": "balldontlie", "status": "skipped", "reason": "BALLDONTLIE_API_KEY is not configured."}]
    searches = tuple(args.player_searches or DEFAULT_PLAYER_SEARCHES)
    results = [await _sync_payload("teams", {}, "balldontlie_teams", BdlRepository.upsert_teams)]
    for search in searches:
        results.append(await _sync_payload("players", {"search": search, "per_page": 100}, "balldontlie_players", BdlRepository.upsert_players))
    if args.start_date:
        for game_date in _date_range(args.start_date, args.end_date):
            results.append(await _sync_payload("games", {"dates[]": game_date, "per_page": 100}, "balldontlie_games", BdlRepository.upsert_games))
    else:
        results.append(await _sync_payload("games", {"seasons[]": args.season, "per_page": 100}, "balldontlie_games", BdlRepository.upsert_games))
    return results


def run_historical_backfill(season: int, skip_existing: bool) -> dict[str, Any]:
    from scripts import historical_backfill

    argv = ["--season", str(season)]
    if skip_existing:
        argv.append("--skip-existing")
    exit_code = historical_backfill.run_with_args(argv)
    return {"season": season, "exit_code": exit_code}


async def run_async(args: argparse.Namespace) -> int:
    init_db()
    before = table_counts()["row_counts"]
    plan = {
        "database": database_status(),
        "skip_bdl": args.skip_bdl,
        "season": args.season,
        "start_date": args.start_date,
        "end_date": args.end_date,
        "player_searches": args.player_searches or list(DEFAULT_PLAYER_SEARCHES),
        "historical_season": args.historical_season,
    }
    if args.dry_run:
        print(json.dumps({"ok": True, "dry_run": True, "plan": plan, "readiness": database_readiness()}, indent=2, default=str))
        return 0
    results: dict[str, Any] = {"bdl": [], "historical": None}
    if not args.skip_bdl:
        results["bdl"] = await bootstrap_bdl(args)
    if args.historical_season:
        results["historical"] = run_historical_backfill(args.historical_season, args.skip_existing_historical)
    after = table_counts()["row_counts"]
    print(json.dumps({"ok": True, "plan": plan, "results": results, "before_counts": before, "after_counts": after, "readiness": database_readiness()}, indent=2, default=str))
    return 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_async(parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
