from __future__ import annotations

import logging
from datetime import date as current_date
from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.repositories import (
    AuditRepository,
    BdlRepository,
    HistoricalRepository,
    ModelingRepository,
    NbaPlatformRepository,
    PlanRepository,
    SubscriptionRepository,
    PasswordResetRepository,
    UserRepository,
)
from app.security import SESSION_COOKIE, session_manager
from app.services.auth import authenticate, get_current_user
from app.services.balldontlie import BallDontLieService
from app.services.billing import BillingService
from app.services.platform import PlatformService


templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))
router = APIRouter(tags=["web"])
logger = logging.getLogger(__name__)


def _safe_plans() -> list[dict]:
    try:
        return PlanRepository.list_active()
    except Exception as exc:
        logger.exception("Failed to load pricing plans for public page: %s", exc)
        return []


LOGIN_EMAIL_COOKIE = "hawknetic_login_email"
REMEMBER_ME_MAX_AGE = 60 * 60 * 24 * 30
LOGIN_EMAIL_MAX_AGE = 60 * 60 * 24 * 365


def _set_session_cookie(response: RedirectResponse, user_id: int, remember: bool = False) -> None:
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_manager.dumps({"user_id": user_id}),
        httponly=True,
        samesite="lax",
        max_age=REMEMBER_ME_MAX_AGE if remember else None,
    )


def render(request: Request, template_name: str, **context):
    current_user = get_current_user(request)
    if current_user:
        sub = SubscriptionRepository.get_active_for_user(int(current_user["id"]))
        current_user = dict(current_user)
        current_user["is_paid"] = PlatformService.is_paid_user(sub)
    context.setdefault("current_user", current_user)
    context.setdefault("support_email", settings.support_email)
    context.setdefault("request", request)
    return templates.TemplateResponse(request, template_name, context)


@router.get("/", response_class=HTMLResponse)
def landing(request: Request):
    return render(request, "landing.html", plans=_safe_plans())


@router.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request):
    return render(request, "pricing.html", plans=_safe_plans())


@router.get("/contact", response_class=HTMLResponse)
def contact(request: Request):
    return render(request, "contact.html")


@router.get("/refund-policy", response_class=HTMLResponse)
def refund_policy(request: Request):
    return render(request, "refund_policy.html")


@router.get("/cancellation-policy", response_class=HTMLResponse)
def cancellation_policy(request: Request):
    return render(request, "cancellation_policy.html")


@router.get("/terms", response_class=HTMLResponse)
def terms(request: Request):
    return render(request, "terms.html")


@router.get("/privacy", response_class=HTMLResponse)
def privacy(request: Request):
    return render(request, "privacy.html")


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    return render(request, "login.html", error=None, email=request.cookies.get(LOGIN_EMAIL_COOKIE, ""), reset_success=request.query_params.get("reset") == "ok")


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form(...), password: str = Form(...), remember_me: str | None = Form(None)):
    user = authenticate(email=email, password=password)
    if not user:
        return render(request, "login.html", error="Invalid credentials.")
    response = RedirectResponse(url="/dashboard", status_code=303)
    _set_session_cookie(response, int(user["id"]), remember=bool(remember_me))
    response.set_cookie(LOGIN_EMAIL_COOKIE, email.lower().strip(), max_age=LOGIN_EMAIL_MAX_AGE, httponly=True, samesite="lax")
    AuditRepository.log(int(user["id"]), "login_success", "user", str(user["id"]), request.headers.get("user-agent", ""))
    return response


@router.get("/forgot-password", response_class=HTMLResponse)
def forgot_password_page(request: Request):
    return render(request, "forgot_password.html", message=None, reset_url=None, email=request.cookies.get(LOGIN_EMAIL_COOKIE, ""))


@router.post("/forgot-password", response_class=HTMLResponse)
def forgot_password_submit(request: Request, email: str = Form(...)):
    recovery = PasswordResetRepository.create_for_email(
        email=email,
        requester_ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )
    reset_url = None
    if recovery:
        reset_url = f"{str(request.url_for('reset_password_page'))}?token={recovery['token']}"
        AuditRepository.log(int(recovery["user_id"]), "password_reset_requested", "user", str(recovery["user_id"]), email)
    return render(request, "forgot_password.html", message="If that email is in HawkNetic, a recovery link has been generated.", reset_url=reset_url, email=email)


@router.get("/reset-password", response_class=HTMLResponse)
def reset_password_page(request: Request, token: str = ""):
    recovery = PasswordResetRepository.get_valid(token)
    return render(request, "reset_password.html", token=token, recovery=recovery, error=None)


@router.post("/reset-password", response_class=HTMLResponse)
def reset_password_submit(request: Request, token: str = Form(...), password: str = Form(...), confirm_password: str = Form(...)):
    recovery = PasswordResetRepository.get_valid(token)
    if not recovery:
        return render(request, "reset_password.html", token=token, recovery=None, error="This recovery link is invalid or expired.")
    if len(password) < 8:
        return render(request, "reset_password.html", token=token, recovery=recovery, error="Use at least 8 characters for the new password.")
    if password != confirm_password:
        return render(request, "reset_password.html", token=token, recovery=recovery, error="Passwords do not match.")
    if not PasswordResetRepository.reset_password(token, password):
        return render(request, "reset_password.html", token=token, recovery=None, error="This recovery link is invalid or expired.")
    AuditRepository.log(int(recovery["user_id"]), "password_reset_completed", "user", str(recovery["user_id"]), recovery["email"])
    return RedirectResponse(url="/login?reset=ok", status_code=303)


@router.get("/register", response_class=HTMLResponse)
def register_page(request: Request):
    return render(request, "register.html", error=None)


@router.post("/register", response_class=HTMLResponse)
def register_submit(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    company: str = Form(""),
    marketing_opt_in: str | None = Form(None),
):
    if UserRepository.get_by_email(email):
        return render(request, "register.html", error="Email already exists.")
    user_id = UserRepository.create(
        email=email,
        password=password,
        full_name=full_name,
        company=company,
        marketing_opt_in=bool(marketing_opt_in),
    )
    AuditRepository.log(user_id, "user_registered", "user", str(user_id), email)
    response = RedirectResponse(url="/dashboard", status_code=303)
    _set_session_cookie(response, user_id, remember=True)
    response.set_cookie(LOGIN_EMAIL_COOKIE, email.lower().strip(), max_age=LOGIN_EMAIL_MAX_AGE, httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


@router.post("/lead")
def lead_submit(
    email: str = Form(...),
    full_name: str = Form(""),
    company: str = Form(""),
    use_case: str = Form(""),
    consent_marketing: str | None = Form(None),
):
    from app.repositories import LeadRepository

    LeadRepository.create(
        email=email,
        full_name=full_name or None,
        company=company or None,
        use_case=use_case or None,
        source_page="/",
        consent_marketing=bool(consent_marketing),
    )
    return RedirectResponse(url="/?lead=ok", status_code=303)


@router.get("/dashboard", response_class=HTMLResponse)
def dashboard(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    snapshot = PlatformService.dashboard_snapshot()
    summary = NbaPlatformRepository.dashboard_summary()
    storage_summary = NbaPlatformRepository.storage_summary()
    historical_coverage = HistoricalRepository.coverage()
    bdl_status = BdlRepository.status()
    recent_games = NbaPlatformRepository.list_games(limit=6)
    provider_health = NbaPlatformRepository.provider_health()
    recent_teams = PlatformService.list_teams(limit=6)
    recent_players = PlatformService.list_players(limit=6)
    props = ModelingRepository.props(limit=10)
    simulations = ModelingRepository.simulations(limit=5)
    todays_slate = [g for g in recent_games if g.get("game_date") == str(__import__("datetime").date.today())]
    return render(
        request,
        "dashboard.html",
        subscription=subscription,
        summary=summary,
        recent_games=recent_games,
        todays_slate=todays_slate,
        provider_health=provider_health,
        storage_summary=storage_summary,
        historical_coverage=historical_coverage,
        bdl_status=bdl_status,
        recent_teams=recent_teams,
        recent_players=recent_players,
        props=props,
        simulations=simulations,
        cavs_practice=HistoricalRepository.cavs_practice_summary(),
        snapshot=snapshot,
        is_paid=PlatformService.is_paid_user(subscription),
        sync_status=request.query_params.get("sync"),
    )


@router.post("/dashboard/sync")
async def dashboard_sync(
    request: Request,
    sync_type: str = Form(...),
    search: str = Form("lebron"),
    date: str = Form(""),
):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)

    user_id = int(user["id"])
    sync_type = sync_type.strip().lower()
    search_value = search.strip()
    date_value = date.strip() or current_date.today().isoformat()

    try:
        if sync_type == "teams":
            await BallDontLieService.sync_teams(user_id=user_id)
        elif sync_type == "players":
            if not search_value:
                return RedirectResponse(url="/dashboard?sync=missing-search", status_code=303)
            await BallDontLieService.sync_players(search=search_value, user_id=user_id)
        elif sync_type == "games":
            await BallDontLieService.sync_games(date_str=date_value, user_id=user_id)
        elif sync_type == "all":
            await BallDontLieService.sync_teams(user_id=user_id)
            if search_value:
                await BallDontLieService.sync_players(search=search_value, user_id=user_id)
            await BallDontLieService.sync_games(date_str=date_value, user_id=user_id)
        else:
            return RedirectResponse(url="/dashboard?sync=invalid", status_code=303)
    except RuntimeError:
        return RedirectResponse(url="/dashboard?sync=error", status_code=303)

    return RedirectResponse(url="/dashboard?sync=ok", status_code=303)


@router.get("/games", response_class=HTMLResponse)
def games(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    query = (request.query_params.get("q") or "").lower().strip()
    games_list = NbaPlatformRepository.list_games(limit=200)
    if query:
        games_list = [g for g in games_list if query in ((g["home_team_name"] or "") + " " + (g["visitor_team_name"] or "")).lower()]
    return render(request, "games.html", games=games_list, query=query, is_paid=bool(subscription))


@router.get("/games/{game_id}", response_class=HTMLResponse)
def game_detail(request: Request, game_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    game = NbaPlatformRepository.get_game(game_id)
    if not game:
        return RedirectResponse(url="/games", status_code=303)
    return render(request, "game_detail.html", game=game, is_paid=bool(subscription))


@router.get("/players/{player_id}", response_class=HTMLResponse)
def player_detail(request: Request, player_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    player = NbaPlatformRepository.get_player(player_id)
    if not player:
        return RedirectResponse(url="/dashboard", status_code=303)
    return render(request, "player_detail.html", player=player, is_paid=bool(subscription))


@router.get("/teams/{team_id}", response_class=HTMLResponse)
def team_detail(request: Request, team_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    team = NbaPlatformRepository.get_team(team_id)
    if not team:
        return RedirectResponse(url="/dashboard", status_code=303)
    roster = NbaPlatformRepository.list_team_players(team_id)
    team_payload = PlatformService.get_team(team_id) or {}
    return render(
        request,
        "team_detail.html",
        team=team,
        roster=roster,
        recent_games=team_payload.get("recent_games", []),
        is_paid=bool(subscription),
    )


@router.get("/edges", response_class=HTMLResponse)
def edges(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    return render(request, "edges.html", is_paid=bool(subscription))


@router.get("/upgrade", response_class=HTMLResponse)
def upgrade(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    return render(request, "upgrade.html", is_paid=bool(subscription), plans=_safe_plans(), subscription=subscription)


@router.get("/account", response_class=HTMLResponse)
def account(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    return render(request, "account.html", subscription=subscription, message=None)


@router.post("/account/ai-opt-in")
def ai_opt_in(request: Request, enabled: str = Form(...)):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    value = enabled == "true"
    UserRepository.set_ai_opt_in(int(user["id"]), value)
    AuditRepository.log(int(user["id"]), "ai_opt_in_changed", "user", str(user["id"]), str(value))
    return RedirectResponse(url="/account", status_code=303)


@router.post("/checkout/{plan_code}")
def checkout(request: Request, plan_code: str):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    result = BillingService.checkout(user_id=int(user["id"]), plan_code=plan_code)
    if result.redirect_url:
        return RedirectResponse(url=result.redirect_url, status_code=303)
    return RedirectResponse(url=f"/account?billing={result.status}", status_code=303)


@router.post("/account/cancel")
def cancel_subscription(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    BillingService.cancel(int(user["id"]))
    return RedirectResponse(url="/account?canceled=1", status_code=303)


@router.get("/teams", response_class=HTMLResponse)
def teams(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return render(request, "teams.html", teams=PlatformService.list_teams())


@router.get("/players", response_class=HTMLResponse)
def players(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return render(request, "players.html", players=PlatformService.list_players())

