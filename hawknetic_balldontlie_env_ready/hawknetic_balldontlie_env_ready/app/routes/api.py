from __future__ import annotations

import csv
import os
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Query, Request
import hashlib
import hmac
import json
from pathlib import Path
from pydantic import BaseModel, Field

from app.config import settings
from app.database import database_readiness, database_status, execute, get_connection, table_counts
from app.repositories import AuditRepository, BdlRepository, CanonicalRepository, ConversationRepository, FindingsRepository, HistoricalRepository, LeadRepository, MappingRepository, ModelingRepository, NbaPlatformRepository, PlanRepository, RawBallDontLieRepository, SubscriptionRepository, UserRepository
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
def analyze_slip(payload: SlipAnalysisIn, request: Request) -> dict:
    from app.services.platform_limits import (
        assert_can_run, blocked_result, increment_usage, rate_limit,
    )
    from app.services.live_readiness import check_readiness

    client_ip = (request.client.host if request.client else "anon") or "anon"
    rate_limit(f"analyze:{client_ip}", max_hits=30, window_seconds=60)

    user_id = _current_user_id(request)
    if user_id:
        assert_can_run(user_id)

    body = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()

    # Hard-block algorithm runs when live readiness has critical blockers.
    readiness = check_readiness()
    if readiness.get("blocking_reasons"):
        return blocked_result(readiness, stake=body.get("stake", 1) or 1, leg_count=len(body.get("legs", [])))

    try:
        result = analyze_slip_request(body)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if user_id:
        increment_usage(user_id)
    return result


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


# ---------------- HawkNetic v3: multi-sport + auth + saved slips ----------------

@router.get("/sports")
def api_sports() -> dict:
    """Public sport-picker payload — supported sports + market types per sport."""
    from app.services.sport_adapters import adapter_summary
    return {"items": adapter_summary()}


@router.get("/insights/top-ev")
def api_top_ev(limit: int = Query(default=15, ge=1, le=50), sport: str | None = None) -> dict:
    """Today's highest-EV legs across loaded props — the +EV / arbitrage scanner.

    For each prop, runs a single-leg analyze and ranks by per-unit EV. This is
    the headline differentiator vs. tools that only show implied probability or
    market-derived edge.
    """
    from app.services.odds_math import american_to_decimal, american_to_implied_probability, expected_value
    from app.services.simulation_engine import LegSpec, simulate_slip

    insights: list[dict] = []
    with get_connection() as conn:
        rows = execute(conn, """
            SELECT p.id, p.game_id, p.player_id, p.market, p.line, p.over_odds, p.under_odds,
                   p.confidence_tier, pl.full_name AS player_name,
                   ht.full_name AS home_team_name, vt.full_name AS visitor_team_name
            FROM props p
            LEFT JOIN historical_players pl ON pl.id = p.player_id
            LEFT JOIN historical_games g ON g.id = p.game_id
            LEFT JOIN historical_teams ht ON ht.id = g.home_team_id
            LEFT JOIN historical_teams vt ON vt.id = g.away_team_id
            WHERE p.over_odds IS NOT NULL OR p.under_odds IS NOT NULL
            ORDER BY p.updated_at DESC
            LIMIT 200
        """).fetchall()

        for row in rows:
            d = dict(row)
            for side, odds_key in (("over", "over_odds"), ("under", "under_odds")):
                american = d.get(odds_key)
                if not american:
                    continue
                try:
                    decimal = american_to_decimal(int(american))
                except ValueError:
                    continue
                stat_key_label = (d.get("market") or "").split("(")[0].strip()
                selection = f"{stat_key_label} {side}"
                spec = LegSpec(
                    leg_id=f"insight-{d['id']}-{side}",
                    game_id=int(d["game_id"]),
                    market_type="player_prop",
                    selection=selection,
                    line=float(d["line"]) if d.get("line") is not None else None,
                    decimal_odds=decimal,
                    american_odds=int(american),
                    player_id=d.get("player_id"),
                    is_under=(side == "under"),
                    stat_key=_stat_key_from_market(d.get("market") or ""),
                )
                sim = simulate_slip(conn, [spec], runs=2000)
                model_p = sim["leg_probabilities"][0]
                if model_p == 0.0 and not sim["inactive_flags"][0]:
                    continue
                implied = american_to_implied_probability(int(american))
                edge = model_p - implied
                ev = expected_value(1.0, decimal, model_p)
                if ev <= 0:
                    continue
                event_label = f"{d.get('visitor_team_name') or 'Away'} @ {d.get('home_team_name') or 'Home'}"
                insights.append({
                    "propId": d["id"],
                    "gameId": d["game_id"],
                    "eventLabel": event_label,
                    "playerName": d.get("player_name"),
                    "market": d.get("market"),
                    "line": d.get("line"),
                    "side": side,
                    "americanOdds": int(american),
                    "decimalOdds": round(decimal, 4),
                    "modelProbability": round(model_p, 4),
                    "impliedProbability": round(implied, 4),
                    "edge": round(edge, 4),
                    "ev": round(ev, 4),
                    "evPercent": round(ev * 100, 2),
                    "projection": round(sim["leg_projections"][0], 2),
                    "confidenceTier": d.get("confidence_tier"),
                })
    insights.sort(key=lambda i: i["ev"], reverse=True)
    return {"items": insights[:limit], "totalScanned": len(rows), "filtered": sport}


def _stat_key_from_market(label: str) -> str | None:
    text = label.lower()
    if "three" in text:
        return "threes"
    if "rebound" in text:
        return "rebounds"
    if "assist" in text:
        return "assists"
    if "point" in text:
        return "points"
    return None


# ---- Auth ----

class SignupIn(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=200)
    full_name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: str
    password: str


def _set_session_cookie(response, user_id: int) -> None:
    from app.security import SESSION_COOKIE, session_manager
    from app.services.platform_limits import is_production
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_manager.dumps({"user_id": user_id}),
        httponly=True,
        secure=is_production(),
        samesite="lax",
        max_age=60 * 60 * 24 * 7,
        path="/",
    )


def _public_user(user: dict) -> dict:
    from fastapi.encoders import jsonable_encoder
    return jsonable_encoder({k: v for k, v in user.items() if k not in {"password_hash", "marketing_opt_in"}})


@router.post("/auth/signup")
def auth_signup(payload: SignupIn, request: Request) -> dict:
    from fastapi.responses import JSONResponse
    from app.services.platform_limits import rate_limit
    client_ip = (request.client.host if request.client else "anon") or "anon"
    rate_limit(f"signup:{client_ip}", max_hits=5, window_seconds=600)
    if UserRepository.get_by_email(payload.email):
        raise HTTPException(status_code=409, detail="An account with that email already exists.")
    user_id = UserRepository.create(payload.email, payload.password, payload.full_name, None, False)
    user = UserRepository.get_by_id(user_id)
    response = JSONResponse({"ok": True, "user": _public_user(user or {})})
    _set_session_cookie(response, user_id)
    return response


@router.post("/auth/login")
def auth_login(payload: LoginIn, request: Request) -> dict:
    from fastapi.responses import JSONResponse
    from app.services.auth import authenticate
    from app.services.platform_limits import rate_limit, reset_rate_limit
    client_ip = (request.client.host if request.client else "anon") or "anon"
    bucket = f"login:{client_ip}:{payload.email.lower()}"
    rate_limit(bucket, max_hits=5, window_seconds=900)
    user = authenticate(payload.email, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password.")
    reset_rate_limit(bucket)
    response = JSONResponse({"ok": True, "user": _public_user(user)})
    _set_session_cookie(response, int(user["id"]))
    return response


@router.post("/auth/logout")
def auth_logout() -> dict:
    from fastapi.responses import JSONResponse
    from app.security import SESSION_COOKIE
    response = JSONResponse({"ok": True})
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/auth/me")
def auth_me(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return {"ok": True, "user": _public_user(user)}


# ---- Saved slips (user-scoped) ----

class SaveSlipIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    sport: str = "NBA"
    legs: list[dict] = Field(min_length=1)
    result_json: dict | None = None


@router.get("/slips")
def api_list_slips(request: Request) -> dict:
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required to view saved slips.")
    with get_connection() as conn:
        rows = execute(conn, """
            SELECT id, name, estimated_odds, win_probability, loss_probability,
                   confidence_tier, risk_tier, correlation_warning, trap_leg_warning,
                   created_at, updated_at
            FROM parlays WHERE user_id = ? ORDER BY updated_at DESC LIMIT 50
        """, (user_id,)).fetchall()
    return {"items": [dict(r) for r in rows]}


@router.post("/slips")
def api_save_slip(payload: SaveSlipIn, request: Request) -> dict:
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required to save slips.")
    parlay = ModelingRepository.build_parlay(user_id=user_id, legs=payload.legs, name=payload.name, sport=payload.sport)
    return {"ok": True, "slip": parlay}


@router.delete("/slips/{slip_id}")
def api_delete_slip(slip_id: int, request: Request) -> dict:
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required.")
    with get_connection() as conn:
        existing = execute(conn, "SELECT user_id FROM parlays WHERE id = ?", (slip_id,)).fetchone()
        if not existing or int(dict(existing).get("user_id") or 0) != user_id:
            raise HTTPException(status_code=404, detail="Slip not found.")
        execute(conn, "DELETE FROM parlay_legs WHERE parlay_id = ?", (slip_id,))
        execute(conn, "DELETE FROM parlays WHERE id = ?", (slip_id,))
    return {"ok": True}


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



# ============================================================================
# HawkneticSports v3.2 — Billing, run-by-id, results, reorder, admin aliases
# ============================================================================


# ---------------- Billing ----------------

class CheckoutIn(BaseModel):
    plan: str = Field(min_length=1, max_length=20)


@router.post("/billing/create-checkout-session")
def api_billing_checkout(payload: CheckoutIn, request: Request) -> dict:
    from app.services.billing import create_checkout_session as svc_create_checkout
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required.")
    user = UserRepository.get_by_id(user_id) or {}
    origin = request.headers.get("origin") or os.environ.get("NEXT_PUBLIC_APP_URL") or str(request.base_url).rstrip("/")
    return svc_create_checkout(user_id=user_id, user_email=user.get("email", ""), plan=payload.plan.lower(), origin=origin)


@router.post("/billing/create-portal-session")
def api_billing_portal(request: Request) -> dict:
    from app.services.billing import create_portal_session as svc_create_portal
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required.")
    origin = request.headers.get("origin") or os.environ.get("NEXT_PUBLIC_APP_URL") or str(request.base_url).rstrip("/")
    return svc_create_portal(user_id=user_id, origin=origin)


@router.get("/billing/subscription")
def api_billing_subscription(request: Request) -> dict:
    from app.services.billing import get_subscription_for_user
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required.")
    return get_subscription_for_user(user_id)


@router.post("/webhooks/stripe")
async def api_stripe_webhook(request: Request) -> dict:
    from app.services.billing import handle_webhook
    body = await request.body()
    signature = request.headers.get("stripe-signature")
    return handle_webhook(body, signature)


# ---------------- Saved-slip run-by-id ----------------

class ReorderItem(BaseModel):
    leg_id: int
    position: int


class ReorderIn(BaseModel):
    leg_order: list[ReorderItem] = Field(min_length=1)


@router.post("/slips/{slip_id}/run")
def api_run_saved_slip(slip_id: int, request: Request, stake: float = Query(default=10.0, ge=0.01, le=100000.0)) -> dict:
    from app.services.platform_limits import (
        assert_can_run, blocked_result, increment_usage, rate_limit, run_saved_slip,
    )
    from app.services.live_readiness import check_readiness
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required.")
    client_ip = (request.client.host if request.client else "anon") or "anon"
    rate_limit(f"run:{client_ip}", max_hits=20, window_seconds=60)
    assert_can_run(user_id)

    readiness = check_readiness()
    if readiness.get("blocking_reasons"):
        # Persist a blocked record so history shows the reason and no usage is consumed.
        from app.services.platform_limits import persist_slip_result
        result = blocked_result(readiness, stake=stake, leg_count=0)
        persist_slip_result(slip_id=slip_id, user_id=user_id, sport=None, result=result)
        return result

    result = run_saved_slip(slip_id=slip_id, user_id=user_id, stake=stake)
    increment_usage(user_id)
    return result


@router.get("/slips/{slip_id}/results")
def api_slip_results(slip_id: int, request: Request, limit: int = Query(default=25, ge=1, le=100)) -> dict:
    from app.services.platform_limits import list_slip_results
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required.")
    return {"items": list_slip_results(slip_id=slip_id, user_id=user_id, limit=limit)}


@router.patch("/slips/{slip_id}/reorder")
def api_reorder_slip(slip_id: int, payload: ReorderIn, request: Request) -> dict:
    from app.services.platform_limits import reorder_slip
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required.")
    return reorder_slip(slip_id=slip_id, user_id=user_id, leg_order=[item.model_dump() for item in payload.leg_order])


# ---------------- Usage / plan introspection ----------------

@router.get("/user/usage")
def api_user_usage(request: Request) -> dict:
    from app.services.platform_limits import usage_for_user_today
    user_id = _current_user_id(request)
    if not user_id:
        raise HTTPException(status_code=401, detail="Login required.")
    return usage_for_user_today(user_id)


# ---------------- Admin aliases (public name → existing handler) ----------------

@router.get("/admin/live-readiness")
def api_admin_live_readiness(request: Request) -> dict:
    from app.services.live_readiness import check_readiness
    return check_readiness()


@router.get("/admin/database-readiness")
def api_admin_database_readiness(request: Request) -> dict:
    return database_readiness()


@router.get("/admin/logs")
def api_admin_logs(request: Request, limit: int = Query(default=100, ge=1, le=500)) -> dict:
    """Returns the most recent audit + provider logs combined."""
    with get_connection() as conn:
        audit = [dict(r) for r in execute(conn, "SELECT id, user_id, action, entity_type, entity_id, created_at FROM audit_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        snapshots = [dict(r) for r in execute(conn, "SELECT id, kind, created_at FROM live_data_snapshots ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
        bdl = [dict(r) for r in execute(conn, "SELECT id, action, status, created_at FROM bdl_ingestion_logs ORDER BY id DESC LIMIT ?", (limit,)).fetchall()]
    return {"audit": audit, "snapshots": snapshots, "provider_logs": bdl}
