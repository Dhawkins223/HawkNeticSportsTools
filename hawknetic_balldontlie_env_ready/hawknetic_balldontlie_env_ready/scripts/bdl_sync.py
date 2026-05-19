from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.database import database_engine, init_db
from app.repositories import BdlRepository, MappingRepository
from app.services.balldontlie import BallDontLieService
from app.services.raw_imports import RawImportTracker


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Railway-safe Ball Don't Lie sync runner")
    parser.add_argument("--teams", action="store_true", help="Sync teams.")
    parser.add_argument("--players", action="store_true", help="Sync players.")
    parser.add_argument("--games", action="store_true", help="Sync games.")
    parser.add_argument("--season", type=int, help="Season for games sync.")
    parser.add_argument("--start-date", help="Start date for games sync, YYYY-MM-DD.")
    parser.add_argument("--end-date", help="End date for games sync, YYYY-MM-DD.")
    parser.add_argument("--search", default="", help="Optional player search term.")
    parser.add_argument("--dry-run", action="store_true", help="Print planned sync without calling the provider or writing rows.")
    args = parser.parse_args(argv)
    if not any((args.teams, args.players, args.games)):
        args.teams = args.players = args.games = True
    if args.end_date and not args.start_date:
        parser.error("--end-date requires --start-date.")
    return args


def _date_range(start: str, end: str | None) -> list[str]:
    start_date = date.fromisoformat(start)
    end_date = date.fromisoformat(end) if end else start_date
    if end_date < start_date:
        raise ValueError("--end-date must be on or after --start-date.")
    days = []
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


async def run_async(args: argparse.Namespace) -> int:
    init_db()
    plan = {"engine": database_engine(), "teams": args.teams, "players": args.players, "games": args.games, "season": args.season, "start_date": args.start_date, "end_date": args.end_date}
    if args.dry_run:
        print(json.dumps({"status": "dry_run", **plan}))
        return 0
    BallDontLieService.ensure_configured()
    results: list[dict[str, Any]] = []
    if args.teams:
        results.append(await _sync_payload("teams", {}, "balldontlie_teams", BdlRepository.upsert_teams))
    if args.players:
        params = {"per_page": 100}
        if args.search:
            params["search"] = args.search
        results.append(await _sync_payload("players", params, "balldontlie_players", BdlRepository.upsert_players))
    if args.games:
        if args.start_date:
            for game_date in _date_range(args.start_date, args.end_date):
                results.append(await _sync_payload("games", {"dates[]": game_date, "per_page": 100}, "balldontlie_games", BdlRepository.upsert_games))
        else:
            params = {"per_page": 100}
            if args.season:
                params["seasons[]"] = args.season
            results.append(await _sync_payload("games", params, "balldontlie_games", BdlRepository.upsert_games))
    print(json.dumps({"ok": all("error" not in result for result in results), "plan": plan, "results": results}, default=str))
    return 1 if any("error" in result for result in results) else 0


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(run_async(parse_args(argv)))


if __name__ == "__main__":
    sys.exit(main())
