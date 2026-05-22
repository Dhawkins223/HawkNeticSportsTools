from __future__ import annotations

import csv
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request
import hashlib
import hmac
import json
from pathlib import Path
from pydantic import BaseModel, Field

from app.config import settings
from app.database import database_readiness, database_status, execute, get_connection, table_counts
from app.repositories import AuditRepository, BdlRepository, CanonicalRepository, ConversationRepository, FindingsRepository, HistoricalRepository, LeadRepository, MappingRepository, ModelingRepository, NbaPlatformRepository, PlanRepository, RawBallDontLieRepository, SubscriptionRepository
from app.services.ai import AIService
from app.services.auth import get_current_user
from app.services.balldontlie import BallDontLieProviderError, BallDontLieService
from app.services.historical_importer import HistoricalImporter
from app.services.historical_raw import BasketballReferenceScraper, ensure_raw_layout
from app.services.slip_analysis import analyze_slip as analyze_slip_request


router = APIRouter(prefix="/api", tags=["api"])
RECENT_PRACTICE_SEASONS = (2020, 2021, 2022, 2023, 2024, 2025, 2026)


class LeadIn(BaseModel):
    email: str
    full_name: str | None = None
    company: str | None = None
    use_case: str | None = None
    consent_marketing: bool = False
    source_page: str = "/"


class AIChatIn(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    conversation_id: int | None = None


class SimulationRunIn(BaseModel):
    game_id: int | None = None
    runs: int = Field(default=1000, ge=1, le=100000)


class ParlayBuildIn(BaseModel):
    name: str = "Generated Parlay"
    legs: list[dict] = Field(default_factory=list)


class ParlayReorderIn(BaseModel):
    parlay_id: int
    leg_ids: list[int]


class BetSlipLegIn(BaseModel):
    id: str
    sport: str = "NBA"
    bookmaker: str = "bet365"
    gameId: str
    eventLabel: str
    startsAt: str | None = None
    marketType: str
    selection: str
    line: float | None = None
    oddsAmerican: int
    teamId: str | None = None
    playerId: str | None = None
    playerName: str | None = None
    notes: str | None = None


class SlipAnalysisIn(BaseModel):
    bookmaker: str = "bet365"
    stake: float = Field(ge=0)
    legs: list[BetSlipLegIn] = Field(min_length=1)


def _raise_provider_error(exc: RuntimeError) -> None:
    status_code = exc.status_code if isinstance(exc, BallDontLieProviderError) else 500
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _current_user_id(request: Request) -> int | None:
    user = get_current_user(request)
    return int(user["id"]) if user else None


@router.get("/health")
def health() -> dict:
    db = database_status()
    return {
        "ok": bool(db["ok"]),
        "status": "ok" if db["ok"] else "degraded",
        "service": settings.app_name,
        "environment": settings.environment,
        "database_engine": db["engine"],
        "database_connected": bool(db.get("connected", db["ok"])),
        "database": db,
        "ball_dont_lie_configured": bool(settings.balldontlie_api_key),
    }




@router.get("/data-status")
def data_status() -> dict:
    db = database_status()
    readiness = database_readiness()
    if not db["ok"]:
        return {
            "database": db,
            "readiness": readiness,
            "historical_coverage": None,
            "bdl": {"counts": {}, "latest": []},
            "mappings": {},
            "modeling": {},
            "message": "Database connection failed. Check DATABASE_URL on the backend service.",
        }
    return {
        "database": db,
        "readiness": readiness,
        "historical_coverage": HistoricalRepository.coverage(),
        "bdl": BdlRepository.status(),
        "mappings": MappingRepository.counts(),
        "modeling": {
            "props": len(ModelingRepository.props(limit=1000)),
            "odds": len(ModelingRepository.odds(limit=1000)),
            "simulations": len(ModelingRepository.simulations(limit=1000)),
        },
        "message": None if readiness["dashboard_ready"] else "Database connected, but required tables are empty. Run historical backfill or Ball Don't Lie sync.",
    }


@router.get("/database/status")
def database_status_endpoint() -> dict:
    return database_status()


@router.get("/database/readiness")
def database_readiness_endpoint() -> dict:
    return database_readiness()


@router.get("/debug/table-counts")
def debug_table_counts() -> dict:
    db = database_status()
    if not db["ok"]:
        return {"ok": False, "database": db, "row_counts": {}, "missing_tables": [], "errors": {"database": db["error"]}}
    return {"ok": True, "database": db, **table_counts()}


@router.get("/database/coverage")
def database_coverage() -> dict:
    return HistoricalRepository.coverage()


@router.get("/teams")
def api_teams(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    from app.services.platform import PlatformService
    items = HistoricalRepository.list_teams(limit=limit)
    fallback = PlatformService.list_teams(limit=limit) if not items else []
    return {"items": items or fallback, "source": "historical" if items else "bdl_fallback", "empty": not bool(items or fallback)}


@router.get("/players")
def api_players(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    from app.services.platform import PlatformService
    items = HistoricalRepository.list_players(limit=limit)
    fallback = PlatformService.list_players(limit=limit) if not items else []
    return {"items": items or fallback, "source": "historical" if items else "bdl_fallback", "empty": not bool(items or fallback)}


@router.get("/games")
def api_games(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    items = NbaPlatformRepository.list_games(limit=limit)
    return {"items": items, "empty": not bool(items), "message": None if items else "Database connected, but games tables are empty. Run historical backfill or Ball Don't Lie sync."}


@router.get("/games/today")
def api_games_today_v1(limit: int = Query(default=20, ge=1, le=100)) -> dict:
    """Public-facing 'today's games' endpoint. Treats today + ongoing live games. (Registered before /{game_id} for path priority.)"""
    from datetime import datetime, timezone
    today = datetime.now(timezone.utc).date().isoformat()
    with get_connection() as conn:
        rows = execute(conn, """
            SELECT g.id, g.game_date, g.season, g.status,
                   ht.full_name AS home_team_name, ht.abbreviation AS home_team_abbr, ht.id AS home_team_id,
                   vt.full_name AS visitor_team_name, vt.abbreviation AS visitor_team_abbr, vt.id AS visitor_team_id,
                   lg.status AS live_status, lg.period AS live_period,
                   lg.home_score AS live_home_score, lg.away_score AS live_away_score,
                   lg.last_updated AS live_last_updated
            FROM historical_games g
            LEFT JOIN historical_teams ht ON ht.id = g.home_team_id
            LEFT JOIN historical_teams vt ON vt.id = g.away_team_id
            LEFT JOIN live_games lg ON lg.game_id = g.id
            WHERE date(g.game_date) >= date(?)
               OR LOWER(COALESCE(lg.status, '')) IN ('live','in_progress','halftime')
            ORDER BY g.game_date ASC
            LIMIT ?
        """, (today, limit)).fetchall()
    return {"items": [dict(r) for r in rows], "empty": not bool(rows)}


@router.get("/games/{game_id}")
def api_game_detail(game_id: int) -> dict:
    item = NbaPlatformRepository.get_game(game_id)
    if not item:
        raise HTTPException(status_code=404, detail="Game not found")
    return {"item": item}


@router.get("/stats/player-game")
def api_player_game_stats(player_id: int | None = None, game_id: int | None = None, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    clauses = []
    params = []
    if player_id is not None:
        clauses.append("player_id = ?")
        params.append(player_id)
    if game_id is not None:
        clauses.append("game_id = ?")
        params.append(game_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with get_connection() as conn:
        rows = execute(conn, f"SELECT * FROM historical_player_game_stats {where} ORDER BY season DESC, id DESC LIMIT ?", params).fetchall()
    return {"items": [dict(row) for row in rows]}


@router.get("/props")
def api_props() -> dict:
    items = ModelingRepository.props()
    return {"items": items, "empty": not bool(items), "message": None if items else "Database connected, but props are empty. Run odds/model generation after backfill or BDL sync."}


@router.get("/odds")
def api_odds() -> dict:
    items = ModelingRepository.odds()
    return {"items": items, "empty": not bool(items), "message": None if items else "Database connected, but odds are empty."}


@router.get("/simulations")
def api_simulations() -> dict:
    items = ModelingRepository.simulations()
    return {"items": items, "empty": not bool(items), "message": None if items else "Database connected, but simulations are empty. Run a simulation to create rows."}


@router.post("/simulations/run")
def api_run_simulation(payload: SimulationRunIn) -> dict:
    return {"ok": True, "result": ModelingRepository.run_simulation(game_id=payload.game_id, runs=payload.runs)}


@router.get("/parlays")
def api_parlays(request: Request) -> dict:
    items = ModelingRepository.parlays(user_id=_current_user_id(request))
    return {"items": items, "empty": not bool(items), "message": None if items else "No saved parlays yet."}


@router.post("/parlays/build")
def api_build_parlay(payload: ParlayBuildIn, request: Request) -> dict:
    return {"ok": True, "parlay": ModelingRepository.build_parlay(user_id=_current_user_id(request), legs=payload.legs, name=payload.name)}


@router.post("/parlays/reorder")
def api_reorder_parlay(payload: ParlayReorderIn) -> dict:
    return ModelingRepository.reorder_parlay(payload.parlay_id, payload.leg_ids)


@router.post("/slips/analyze")
def analyze_slip(payload: SlipAnalysisIn) -> dict:
    try:
        request = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        return analyze_slip_request(request)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------- HawkNetic v2: live data layer ----------------

@router.get("/live/readiness")
def api_live_readiness() -> dict:
    from app.services.live_readiness import check_readiness
    return check_readiness()


@router.get("/games/{game_id}/markets")
def api_game_markets(game_id: int) -> dict:
    """Returns spreads/totals/moneylines + player props + live status for a single game."""
    with get_connection() as conn:
        props = [dict(r) for r in execute(conn, """
            SELECT p.*, pl.full_name AS player_name
            FROM props p LEFT JOIN historical_players pl ON pl.id = p.player_id
            WHERE p.game_id = ? ORDER BY p.expected_value DESC, p.updated_at DESC
        """, (game_id,)).fetchall()]
        odds = [dict(r) for r in execute(conn, "SELECT * FROM odds WHERE game_id = ? ORDER BY fetched_at DESC", (game_id,)).fetchall()]
        live_odds = [dict(r) for r in execute(conn, "SELECT * FROM live_odds WHERE game_id = ? ORDER BY last_updated DESC", (game_id,)).fetchall()]
        live_game = execute(conn, "SELECT * FROM live_games WHERE game_id = ?", (game_id,)).fetchone()
        line_movement = [dict(r) for r in execute(conn, "SELECT * FROM live_line_movement WHERE game_id = ? ORDER BY captured_at DESC LIMIT 50", (game_id,)).fetchall()]
    return {
        "gameId": game_id,
        "props": props,
        "odds": odds,
        "liveOdds": live_odds,
        "liveGame": dict(live_game) if live_game else None,
        "lineMovement": line_movement,
    }


@router.post("/live/sync")
def api_live_sync(payload: dict) -> dict:
    """Admin-only stub for ingesting a live data snapshot.

    Accepts: { kind: 'odds'|'player_status'|'game_state'|'injury', payload: {...} }
    Persists raw payload to live_data_snapshots and dispatches a writer per kind.
    """
    from app.services.live_sync import ingest_snapshot
    return ingest_snapshot(payload)


@router.get("/live/snapshots")
def api_live_snapshots(limit: int = Query(default=25, ge=1, le=200)) -> dict:
    with get_connection() as conn:
        rows = execute(conn, "SELECT id, kind, created_at, substr(payload, 1, 500) AS preview FROM live_data_snapshots ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.get("/live/odds")
def api_live_odds(game_id: int | None = None, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    with get_connection() as conn:
        if game_id:
            rows = execute(conn, "SELECT * FROM live_odds WHERE game_id = ? ORDER BY last_updated DESC LIMIT ?", (game_id, limit)).fetchall()
        else:
            rows = execute(conn, "SELECT * FROM live_odds ORDER BY last_updated DESC LIMIT ?", (limit,)).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/historical/rebuild")
def api_historical_rebuild() -> dict:
    return {"ok": True, "coverage": HistoricalRepository.rebuild(), "message": "Coverage rebuilt from existing PostgreSQL tables; missing seasons remain incomplete until a historical loader populates records."}


def _scrape_and_import_season(season: int, max_box_scores: int | None = None) -> dict:
    scrape_result = BasketballReferenceScraper().scrape_season(season, max_box_scores=max_box_scores)
    if int(scrape_result.coverage.get("games_scraped") or 0) == 0 and int(scrape_result.coverage.get("box_scores_scraped") or 0) == 0:
        return {
            "ok": False,
            "season": season,
            "scrape": {"output_dir": scrape_result.output_dir, "coverage": scrape_result.coverage},
            "import": None,
            "coverage": HistoricalRepository.coverage(),
            "failure_reason": "Scrape returned zero games and zero box scores; import was skipped. Check raw/historical/<season>/scrape_errors.csv for URL/status details.",
        }
    import_result = HistoricalImporter().import_season(season)
    return {
        "ok": True,
        "season": season,
        "scrape": {"output_dir": scrape_result.output_dir, "coverage": scrape_result.coverage},
        "import": import_result,
        "coverage": HistoricalRepository.coverage(),
    }


@router.post("/historical/backfill")
def api_historical_backfill(start_season: int = Query(default=1996, ge=1996, le=2026), end_season: int = Query(default=2026, ge=1996, le=2026), max_box_scores: int | None = Query(default=None, ge=1)) -> dict:
    if end_season < start_season:
        raise HTTPException(status_code=400, detail="end_season must be greater than or equal to start_season")
    results = [_scrape_and_import_season(season, max_box_scores=max_box_scores) for season in range(start_season, end_season + 1)]
    return {"ok": True, "start_season": start_season, "end_season": end_season, "results": results, "coverage": HistoricalRepository.coverage()}





def _backfill_recent_practice_dataset(max_box_scores: int | None = None) -> dict:
    results = []
    for season in RECENT_PRACTICE_SEASONS:
        results.append(_scrape_and_import_season(season, max_box_scores=max_box_scores))
    return {"ok": True, "seasons": list(RECENT_PRACTICE_SEASONS), "results": results, "coverage": HistoricalRepository.coverage(), "cavs": HistoricalRepository.cavs_practice_summary()}


@router.post("/historical/backfill/recent")
def api_recent_practice_backfill(max_box_scores: int | None = Query(default=None, ge=1)) -> dict:
    return _backfill_recent_practice_dataset(max_box_scores=max_box_scores)


@router.post("/historical/backfill/recent/background")
def api_recent_practice_backfill_background(background_tasks: BackgroundTasks, max_box_scores: int | None = Query(default=None, ge=1)) -> dict:
    background_tasks.add_task(_backfill_recent_practice_dataset, max_box_scores=max_box_scores)
    return {"ok": True, "queued": True, "seasons": list(RECENT_PRACTICE_SEASONS), "message": "Recent 2020-2026 historical scrape/import queued in the web worker."}


@router.get("/practice/cavs")
def api_cavs_practice() -> dict:
    return HistoricalRepository.cavs_practice_summary()


@router.post("/historical/backfill/{season}")
def api_historical_backfill_season(season: int, max_box_scores: int | None = Query(default=None, ge=1)) -> dict:
    if season < 1996 or season > 2026:
        raise HTTPException(status_code=400, detail="Season must be between 1996 and 2026")
    return _scrape_and_import_season(season, max_box_scores=max_box_scores)




@router.get("/historical/seasons")
def api_historical_seasons() -> dict:
    return {"items": HistoricalRepository.coverage()["seasons"]}


@router.post("/historical/scrape")
def api_historical_scrape(start_season: int = Query(default=1996, ge=1996, le=2026), end_season: int = Query(default=2026, ge=1996, le=2026), max_box_scores: int | None = Query(default=None, ge=1)) -> dict:
    if end_season < start_season:
        raise HTTPException(status_code=400, detail="end_season must be greater than or equal to start_season")
    return BasketballReferenceScraper().scrape_range(start_season=start_season, end_season=end_season, max_box_scores=max_box_scores)


@router.post("/historical/scrape/{season}")
def api_historical_scrape_season(season: int, max_box_scores: int | None = Query(default=None, ge=1)) -> dict:
    if season < 1996 or season > 2026:
        raise HTTPException(status_code=400, detail="Season must be between 1996 and 2026")
    result = BasketballReferenceScraper().scrape_season(season, max_box_scores=max_box_scores)
    return {"ok": True, "season": season, "output_dir": result.output_dir, "coverage": result.coverage}


@router.post("/historical/import")
def api_historical_import(start_season: int = Query(default=1996, ge=1996, le=2026), end_season: int = Query(default=2026, ge=1996, le=2026)) -> dict:
    if end_season < start_season:
        raise HTTPException(status_code=400, detail="end_season must be greater than or equal to start_season")
    ensure_raw_layout()
    return HistoricalImporter().import_range(start_season=start_season, end_season=end_season)


@router.post("/historical/import/{season}")
def api_historical_import_season(season: int) -> dict:
    if season < 1996 or season > 2026:
        raise HTTPException(status_code=400, detail="Season must be between 1996 and 2026")
    ensure_raw_layout()
    return {"ok": True, **HistoricalImporter().import_season(season)}


@router.get("/historical/coverage")
def api_historical_coverage() -> dict:
    return HistoricalRepository.coverage()


@router.get("/historical/scrape-errors/{season}")
def api_historical_scrape_errors(season: int) -> dict:
    if season < 1996 or season > 2026:
        raise HTTPException(status_code=400, detail="Season must be between 1996 and 2026")
    path = Path(settings.historical_raw_dir) / str(season) / "scrape_errors.csv"
    if not path.exists():
        return {"ok": False, "season": season, "exists": False, "error_count": 0, "errors": [], "file_path": str(path), "message": "scrape_errors.csv not found for season"}
    with path.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    errors = [{
        "url": row.get("url", ""),
        "error": row.get("error_message") or row.get("error") or "",
        "status_code": row.get("status_code", ""),
        "response_snippet": row.get("response_snippet", ""),
        "timestamp": row.get("created_at") or row.get("checked_at") or row.get("timestamp") or "",
    } for row in rows]
    return {"ok": True, "season": season, "exists": True, "error_count": len(errors), "errors": errors, "file_path": str(path)}


@router.get("/historical/seasons/{season}")
def api_historical_season(season: int) -> dict:
    if season < 1996 or season > 2026:
        raise HTTPException(status_code=400, detail="Season must be between 1996 and 2026")
    return HistoricalRepository.season(season)


@router.get("/historical/players/{player_id}")
def api_historical_player(player_id: int) -> dict:
    item = HistoricalRepository.get_player(player_id)
    if not item:
        raise HTTPException(status_code=404, detail="Historical player not found")
    return {"item": item}


@router.get("/historical/teams/{team_id}")
def api_historical_team(team_id: int) -> dict:
    item = HistoricalRepository.get_team(team_id)
    if not item:
        raise HTTPException(status_code=404, detail="Historical team not found")
    return {"item": item}

@router.post("/leads")
def capture_lead(payload: LeadIn) -> dict:
    lead_id = LeadRepository.create(
        email=payload.email,
        full_name=payload.full_name,
        company=payload.company,
        use_case=payload.use_case,
        source_page=payload.source_page,
        consent_marketing=payload.consent_marketing,
    )
    return {"ok": True, "lead_id": lead_id}


@router.get("/me")
def me(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        return {"authenticated": False}
    return {
        "authenticated": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "company": user["company"],
            "ai_opt_in": bool(user["ai_opt_in"]),
        },
    }


@router.post("/ai/chat")
async def ai_chat(payload: AIChatIn, request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required.")
    if not bool(user["ai_opt_in"]):
        raise HTTPException(status_code=403, detail="Enable AI access from your account page first.")
    result = await AIService.explain_finding(user_id=int(user["id"]), prompt=payload.prompt, conversation_id=payload.conversation_id)
    return {
        "ok": True,
        "conversation_id": result.conversation_id,
        "provider": result.provider,
        "model": result.model,
        "content": result.content,
    }


@router.get("/findings")
def findings(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required.")
    rows = FindingsRepository.list_for_user(int(user["id"]))
    return {
        "items": [
            {"id": row["id"], "title": row["title"], "body": row["body"], "created_at": row["created_at"]}
            for row in rows
        ]
    }


@router.get("/conversations")
def conversations(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required.")
    rows = ConversationRepository.list_for_user(int(user["id"]))
    return {
        "items": [
            {"id": row["id"], "title": row["title"], "provider": row["provider"], "model": row["model"], "created_at": row["created_at"]}
            for row in rows
        ]
    }


@router.get('/providers/balldontlie/health')
def balldontlie_health() -> dict:
    return {
        'provider': 'balldontlie',
        'configured': bool(settings.balldontlie_api_key),
        'base_url': settings.balldontlie_base_url,
        'v2_base_url': settings.balldontlie_v2_base_url,
    }


@router.get('/providers/balldontlie/teams')
async def balldontlie_teams() -> dict:
    try:
        return await BallDontLieService.client().get_teams()
    except RuntimeError as exc:
        _raise_provider_error(exc)


@router.get('/providers/balldontlie/players')
async def balldontlie_players(search: str = Query(..., min_length=1, max_length=100)) -> dict:
    try:
        return await BallDontLieService.client().search_players(search=search)
    except RuntimeError as exc:
        _raise_provider_error(exc)


@router.get('/providers/balldontlie/games')
async def balldontlie_games(date: str = Query(..., min_length=10, max_length=10)) -> dict:
    try:
        return await BallDontLieService.client().get_games_by_date(date_str=date)
    except RuntimeError as exc:
        _raise_provider_error(exc)


@router.post('/providers/balldontlie/sync/teams')
async def balldontlie_sync_teams(request: Request) -> dict:
    user = get_current_user(request)
    try:
        result = await BallDontLieService.sync_teams(user_id=int(user['id']) if user else None)
    except RuntimeError as exc:
        _raise_provider_error(exc)
    return {'ok': True, 'resource': result.resource, 'raw_records_written': result.raw_records_written, 'canonical_records_written': result.canonical_records_written, 'source_count': result.source_count}


@router.post('/providers/balldontlie/sync/players')
async def balldontlie_sync_players(request: Request, search: str = Query(..., min_length=1, max_length=100)) -> dict:
    user = get_current_user(request)
    try:
        result = await BallDontLieService.sync_players(search=search, user_id=int(user['id']) if user else None)
    except RuntimeError as exc:
        _raise_provider_error(exc)
    return {'ok': True, 'resource': result.resource, 'raw_records_written': result.raw_records_written, 'canonical_records_written': result.canonical_records_written, 'source_count': result.source_count}


@router.post('/providers/balldontlie/sync/games')
async def balldontlie_sync_games(request: Request, date: str = Query(..., min_length=10, max_length=10)) -> dict:
    user = get_current_user(request)
    try:
        result = await BallDontLieService.sync_games(date_str=date, user_id=int(user['id']) if user else None)
    except RuntimeError as exc:
        _raise_provider_error(exc)
    return {'ok': True, 'resource': result.resource, 'raw_records_written': result.raw_records_written, 'canonical_records_written': result.canonical_records_written, 'source_count': result.source_count}


@router.get('/providers/balldontlie/storage-summary')
def balldontlie_storage_summary() -> dict:
    raw = {
        'teams': RawBallDontLieRepository.count('raw_balldontlie_teams'),
        'players': RawBallDontLieRepository.count('raw_balldontlie_players'),
        'games': RawBallDontLieRepository.count('raw_balldontlie_games'),
    }
    canonical = {
        'teams': CanonicalRepository.count('canonical_teams'),
        'players': CanonicalRepository.count('canonical_players'),
        'games': CanonicalRepository.count('canonical_games'),
    }
    return {
        'provider': 'balldontlie',
        'raw': raw,
        'canonical': canonical,
        'bdl': raw,
        'historical': canonical,
        'mappings': MappingRepository.counts(),
    }


@router.post("/billing/stripe/webhook")
async def stripe_webhook(request: Request, stripe_signature: str | None = Header(default=None, alias="Stripe-Signature")) -> dict:
    if not settings.stripe_webhook_secret:
        return {"ok": True, "status": "ignored", "reason": "No webhook secret configured."}
    if not stripe_signature:
        raise HTTPException(status_code=400, detail="Missing Stripe-Signature header.")

    body = await request.body()
    _verify_stripe_signature(payload=body, signature_header=stripe_signature, secret=settings.stripe_webhook_secret)
    event = json.loads(body.decode("utf-8"))
    event_type = event.get("type", "")
    data = event.get("data", {}).get("object", {})

    if event_type == "checkout.session.completed":
        metadata = data.get("metadata", {}) or {}
        plan_code = metadata.get("plan_code")
        user_id = int(metadata.get("user_id", 0) or 0)
        if user_id and plan_code:
            plan = PlanRepository.get_by_code(plan_code)
            if plan:
                SubscriptionRepository.subscribe_stripe(
                    user_id=user_id,
                    plan_id=int(plan["id"]),
                    amount_cents=int(plan["price_cents"]),
                    external_subscription_id=data.get("subscription"),
                    external_customer_id=data.get("customer"),
                    external_payment_id=data.get("payment_intent"),
                )
                AuditRepository.log(user_id, "stripe_checkout_completed", "subscription", str(user_id), event.get("id", ""))

    return {"ok": True, "received": True, "event_type": event_type}


def _verify_stripe_signature(payload: bytes, signature_header: str, secret: str) -> None:
    parts = {}
    for item in signature_header.split(","):
        if "=" in item:
            k, v = item.split("=", 1)
            parts[k.strip()] = v.strip()
    timestamp = parts.get("t")
    expected = parts.get("v1")
    if not timestamp or not expected:
        raise HTTPException(status_code=400, detail="Malformed Stripe signature header.")
    signed_payload = f"{timestamp}.".encode("utf-8") + payload
    digest = hmac.new(secret.encode("utf-8"), signed_payload, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")


@router.post("/bdl/sync/teams")
async def api_bdl_sync_teams(request: Request) -> dict:
    return await balldontlie_sync_teams(request)


@router.post("/bdl/sync/players")
async def api_bdl_sync_players(request: Request, search: str = Query(default="lebron", min_length=1, max_length=100)) -> dict:
    return await balldontlie_sync_players(request, search=search)


@router.post("/bdl/sync/games")
async def api_bdl_sync_games(request: Request, date: str = Query(..., min_length=10, max_length=10)) -> dict:
    return await balldontlie_sync_games(request, date=date)


@router.post("/bdl/sync/stats")
async def api_bdl_sync_stats(request: Request) -> dict:
    try:
        result = await BallDontLieService.sync_stats(user_id=_current_user_id(request))
    except RuntimeError as exc:
        _raise_provider_error(exc)
    return {"ok": True, **result.__dict__}


@router.post("/bdl/sync/live")
async def api_bdl_sync_live(request: Request) -> dict:
    try:
        result = await BallDontLieService.sync_live(user_id=_current_user_id(request))
    except RuntimeError as exc:
        _raise_provider_error(exc)
    return {"ok": True, **result.__dict__}


@router.get("/bdl/status")
def api_bdl_status() -> dict:
    return BdlRepository.status()


@router.get("/bdl/logs")
def api_bdl_logs() -> dict:
    return {"items": BdlRepository.logs(limit=100)}
