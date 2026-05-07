from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app.repositories import AuditRepository, NbaPlatformRepository, PlanRepository, SubscriptionRepository, UserRepository
from app.security import SESSION_COOKIE, session_manager
from app.services.auth import authenticate, get_current_user
from app.services.billing import BillingService
from app.services.platform import PlatformService


templates = Jinja2Templates(directory=str(Path(__file__).resolve().parents[1] / 'templates'))
router = APIRouter(tags=["web"])


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
    return render(request, "landing.html", plans=PlanRepository.list_active())


@router.get("/pricing", response_class=HTMLResponse)
def pricing(request: Request):
    return render(request, "pricing.html", plans=PlanRepository.list_active())


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
    return render(request, "login.html", error=None)


@router.post("/login", response_class=HTMLResponse)
def login_submit(request: Request, email: str = Form(...), password: str = Form(...)):
    user = authenticate(email=email, password=password)
    if not user:
        return render(request, "login.html", error="Invalid credentials.")
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_manager.dumps({"user_id": int(user["id"])}),
        httponly=True,
        samesite="lax",
    )
    AuditRepository.log(int(user["id"]), "login_success", "user", str(user["id"]), request.headers.get("user-agent", ""))
    return response


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
    response.set_cookie(
        key=SESSION_COOKIE,
        value=session_manager.dumps({"user_id": user_id}),
        httponly=True,
        samesite="lax",
    )
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
    recent_games = NbaPlatformRepository.list_games(limit=6)
    provider_health = NbaPlatformRepository.provider_health()
    todays_slate = [g for g in recent_games if g["game_date"] == str(__import__("datetime").date.today())]
    return render(
        request,
        "dashboard.html",
        subscription=subscription,
        summary=summary,
        recent_games=recent_games,
        todays_slate=todays_slate,
        provider_health=provider_health,
        snapshot=snapshot,
        is_paid=PlatformService.is_paid_user(subscription),
    )


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
    return render(request, "team_detail.html", team=team, roster=roster, is_paid=bool(subscription))


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
    return render(request, "upgrade.html", is_paid=bool(subscription), plans=PlanRepository.list_active(), subscription=subscription)


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


@router.get("/games", response_class=HTMLResponse)
def games(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return render(request, "games.html", games=PlatformService.list_games())


@router.get("/teams", response_class=HTMLResponse)
def teams(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return render(request, "teams.html", teams=PlatformService.list_teams())


@router.get("/teams/{team_id}", response_class=HTMLResponse)
def team_detail(request: Request, team_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    payload = PlatformService.get_team(team_id)
    if not payload:
        return RedirectResponse(url="/teams", status_code=303)
    return render(request, "team_detail.html", **payload)


@router.get("/players", response_class=HTMLResponse)
def players(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    return render(request, "players.html", players=PlatformService.list_players())


@router.get("/players/{player_id}", response_class=HTMLResponse)
def player_detail(request: Request, player_id: int):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    player = PlatformService.get_player(player_id)
    if not player:
        return RedirectResponse(url="/players", status_code=303)
    return render(request, "player_detail.html", player=player)


@router.get("/edges", response_class=HTMLResponse)
def edges(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    return render(request, "edges.html", subscription=subscription, is_paid=PlatformService.is_paid_user(subscription))


@router.get("/upgrade", response_class=HTMLResponse)
def upgrade(request: Request):
    user = get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=303)
    subscription = SubscriptionRepository.get_active_for_user(int(user["id"]))
    return render(request, "upgrade.html", plans=PlanRepository.list_active(), subscription=subscription)
