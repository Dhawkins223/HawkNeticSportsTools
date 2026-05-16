from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
import hashlib
import hmac
import json
from pydantic import BaseModel, Field

from app.config import settings
from app.database import database_status, execute, get_connection
from app.repositories import AuditRepository, BdlRepository, CanonicalRepository, ConversationRepository, FindingsRepository, HistoricalRepository, LeadRepository, MappingRepository, ModelingRepository, NbaPlatformRepository, PlanRepository, RawBallDontLieRepository, SubscriptionRepository
from app.services.ai import AIService
from app.services.auth import get_current_user
from app.services.balldontlie import BallDontLieProviderError, BallDontLieService


router = APIRouter(prefix="/api", tags=["api"])


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


def _raise_provider_error(exc: RuntimeError) -> None:
    status_code = exc.status_code if isinstance(exc, BallDontLieProviderError) else 500
    raise HTTPException(status_code=status_code, detail=str(exc)) from exc


def _current_user_id(request: Request) -> int | None:
    user = get_current_user(request)
    return int(user["id"]) if user else None


@router.get("/health")
def health() -> dict:
    db = database_status()
    return {"status": "ok" if db["ok"] else "degraded", "database": db, "ball_dont_lie_configured": bool(settings.balldontlie_api_key)}




@router.get("/data-status")
def data_status() -> dict:
    return {"database": database_status(), "historical_coverage": HistoricalRepository.coverage(), "bdl": BdlRepository.status(), "mappings": MappingRepository.counts(), "modeling": {"props": len(ModelingRepository.props(limit=1000)), "odds": len(ModelingRepository.odds(limit=1000)), "simulations": len(ModelingRepository.simulations(limit=1000))}}


@router.get("/database/status")
def database_status_endpoint() -> dict:
    return database_status()


@router.get("/database/coverage")
def database_coverage() -> dict:
    return HistoricalRepository.coverage()


@router.get("/teams")
def api_teams(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    from app.services.platform import PlatformService
    items = HistoricalRepository.list_teams(limit=limit)
    return {"items": items or PlatformService.list_teams(limit=limit), "source": "historical" if items else "bdl_fallback"}


@router.get("/players")
def api_players(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    from app.services.platform import PlatformService
    items = HistoricalRepository.list_players(limit=limit)
    return {"items": items or PlatformService.list_players(limit=limit), "source": "historical" if items else "bdl_fallback"}


@router.get("/games")
def api_games(limit: int = Query(default=100, ge=1, le=500)) -> dict:
    return {"items": NbaPlatformRepository.list_games(limit=limit)}


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
    return {"items": ModelingRepository.props()}


@router.get("/odds")
def api_odds() -> dict:
    return {"items": ModelingRepository.odds()}


@router.get("/simulations")
def api_simulations() -> dict:
    return {"items": ModelingRepository.simulations()}


@router.post("/simulations/run")
def api_run_simulation(payload: SimulationRunIn) -> dict:
    return {"ok": True, "result": ModelingRepository.run_simulation(game_id=payload.game_id, runs=payload.runs)}


@router.get("/parlays")
def api_parlays(request: Request) -> dict:
    return {"items": ModelingRepository.parlays(user_id=_current_user_id(request))}


@router.post("/parlays/build")
def api_build_parlay(payload: ParlayBuildIn, request: Request) -> dict:
    return {"ok": True, "parlay": ModelingRepository.build_parlay(user_id=_current_user_id(request), legs=payload.legs, name=payload.name)}


@router.post("/parlays/reorder")
def api_reorder_parlay(payload: ParlayReorderIn) -> dict:
    return ModelingRepository.reorder_parlay(payload.parlay_id, payload.leg_ids)


@router.post("/historical/rebuild")
def api_historical_rebuild() -> dict:
    return {"ok": True, "coverage": HistoricalRepository.rebuild(), "message": "Coverage rebuilt from existing PostgreSQL tables; missing seasons remain incomplete until a historical loader populates records."}


@router.post("/historical/backfill")
def api_historical_backfill() -> dict:
    return api_historical_rebuild()


@router.get("/historical/coverage")
def api_historical_coverage() -> dict:
    return HistoricalRepository.coverage()


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
