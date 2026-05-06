from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request
import hashlib
import hmac
import json
from pydantic import BaseModel, Field

from app.config import settings
from app.repositories import AuditRepository, CanonicalRepository, ConversationRepository, FindingsRepository, LeadRepository, PlanRepository, RawBallDontLieRepository, SubscriptionRepository
from app.services.ai import AIService
from app.services.auth import get_current_user
from app.services.balldontlie import BallDontLieService


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


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


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
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get('/providers/balldontlie/players')
async def balldontlie_players(search: str = Query(..., min_length=1, max_length=100)) -> dict:
    try:
        return await BallDontLieService.client().search_players(search=search)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get('/providers/balldontlie/games')
async def balldontlie_games(date: str = Query(..., min_length=10, max_length=10)) -> dict:
    try:
        return await BallDontLieService.client().get_games_by_date(date_str=date)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post('/providers/balldontlie/sync/teams')
async def balldontlie_sync_teams(request: Request) -> dict:
    user = get_current_user(request)
    try:
        result = await BallDontLieService.sync_teams(user_id=int(user['id']) if user else None)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {'ok': True, 'resource': result.resource, 'raw_records_written': result.raw_records_written, 'canonical_records_written': result.canonical_records_written, 'source_count': result.source_count}


@router.post('/providers/balldontlie/sync/players')
async def balldontlie_sync_players(request: Request, search: str = Query(..., min_length=1, max_length=100)) -> dict:
    user = get_current_user(request)
    try:
        result = await BallDontLieService.sync_players(search=search, user_id=int(user['id']) if user else None)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {'ok': True, 'resource': result.resource, 'raw_records_written': result.raw_records_written, 'canonical_records_written': result.canonical_records_written, 'source_count': result.source_count}


@router.post('/providers/balldontlie/sync/games')
async def balldontlie_sync_games(request: Request, date: str = Query(..., min_length=10, max_length=10)) -> dict:
    user = get_current_user(request)
    try:
        result = await BallDontLieService.sync_games(date_str=date, user_id=int(user['id']) if user else None)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {'ok': True, 'resource': result.resource, 'raw_records_written': result.raw_records_written, 'canonical_records_written': result.canonical_records_written, 'source_count': result.source_count}


@router.get('/providers/balldontlie/storage-summary')
def balldontlie_storage_summary() -> dict:
    return {
        'provider': 'balldontlie',
        'raw': {
            'teams': RawBallDontLieRepository.count('raw_balldontlie_teams'),
            'players': RawBallDontLieRepository.count('raw_balldontlie_players'),
            'games': RawBallDontLieRepository.count('raw_balldontlie_games'),
        },
        'canonical': {
            'teams': CanonicalRepository.count('canonical_teams'),
            'players': CanonicalRepository.count('canonical_players'),
            'games': CanonicalRepository.count('canonical_games'),
        },
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
