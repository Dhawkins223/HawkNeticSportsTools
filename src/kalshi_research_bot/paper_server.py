from __future__ import annotations

import base64
import html
import json
import os
import secrets
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Mapping
from urllib.parse import parse_qs, urlparse

from .auth import (
    AuthPrincipal,
    LocalAuthStore,
    SESSION_COOKIE_NAME,
    role_allows,
    session_token_from_cookie,
    user_auth_enabled,
)
from .combo_safety import slip_has_authoritative_combo_evidence
from .database import database_startup_status, json_default, production_safety_status
from .connectors.http import prune_http_cache
from .config import repo_path
from .monitoring import build_internal_status
from .operator_inbox import OperatorInbox, PRIORITIES, TARGETS
from .review_packet import (
    SLIP_SOURCES,
    build_all_review_packets,
    build_review_packet,
    render_review_packet_text,
    safe_review_packet_filename,
)
from .research_record import build_research_record
from .slip_safety import consumer_payload, gate_slip_payload, slip_payload_gate
from .source_quality import build_dashboard_quality_gate
from .business_store import create_store
from .kalshi_ingestion import load_latest_kalshi_snapshot
from .sports_board import load_sports_board, summarize_sports_board
from .sports_clv import build_sports_clv_report
from .storage import PostgresStore


REFRESH_COOLDOWN_SECONDS = 60
DEFAULT_KALSHI_RUN_ID = "stage3a_20260703_170707"
DEFAULT_REFRESH_LEDGER_MAX_PAYLOAD_AGE_SECONDS = 1800
DEFAULT_DASHBOARD_MAX_SLIP_AGE_SECONDS = 1800
DEFAULT_DETAIL_PAGE_SIZE = 50
MAX_DETAIL_PAGE_SIZE = 200
HOSTED_RUNTIME_ENV_KEYS = (
    "RAILWAY_ENVIRONMENT",
    "RAILWAY_ENVIRONMENT_ID",
    "RAILWAY_PROJECT_ID",
    "RAILWAY_PUBLIC_DOMAIN",
)
REFRESH_ACTION_HEADER = "X-Research-Action"
REFRESH_ACTION_VALUE = "refresh-dashboard"


def _env_flag(values: Mapping[str, str], name: str, default: bool = False) -> bool:
    value = values.get(name)
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def hosted_runtime(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return any(str(values.get(name) or "").strip() for name in HOSTED_RUNTIME_ENV_KEYS) or str(
        values.get("APP_ENV") or ""
    ).strip().lower() in {"staging", "production"}


def dashboard_auth_enabled(env: dict[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    require_hosted_auth = _env_flag(values, "DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED", True)
    return (
        _env_flag(values, "DASHBOARD_AUTH_ENABLED")
        or user_auth_enabled(values)
        or bool(values.get("DASHBOARD_AUTH_PASSWORD"))
        or (require_hosted_auth and hosted_runtime(values))
    )


def dashboard_auth_configured(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    basic_configured = _env_flag(values, "DASHBOARD_BASIC_FALLBACK_ENABLED", True) and bool(
        values.get("DASHBOARD_AUTH_PASSWORD")
    )
    return basic_configured or user_auth_enabled(values) or not dashboard_auth_enabled(dict(values))


def valid_dashboard_auth(header: str | None, env: dict[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    if not dashboard_auth_enabled(values):
        return True
    expected_password = values.get("DASHBOARD_AUTH_PASSWORD")
    if not expected_password:
        return False
    expected_username = values.get("DASHBOARD_AUTH_USERNAME", "hawknetic")
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header.removeprefix("Basic "), validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    username, separator, password = decoded.partition(":")
    if not separator:
        return False
    return secrets.compare_digest(username, expected_username) and secrets.compare_digest(password, expected_password)


def authenticate_dashboard_request(
    authorization_header: str | None,
    cookie_header: str | None = None,
    *,
    env: Mapping[str, str] | None = None,
    auth_store: LocalAuthStore | None = None,
) -> AuthPrincipal | None:
    values = os.environ if env is None else env
    if not dashboard_auth_enabled(dict(values)):
        return AuthPrincipal(username="local", role="admin", auth_method="local_unprotected")
    if user_auth_enabled(values) and auth_store is not None:
        session_token = session_token_from_cookie(cookie_header)
        principal = auth_store.resolve_session(session_token or "")
        if principal is not None:
            return principal
    basic_fallback_enabled = _env_flag(values, "DASHBOARD_BASIC_FALLBACK_ENABLED", True)
    if basic_fallback_enabled and valid_dashboard_auth(authorization_header, dict(values)):
        role = str(values.get("DASHBOARD_BASIC_AUTH_ROLE") or "admin").strip().lower()
        if role not in {"admin", "researcher", "read_only"}:
            role = "read_only"
        return AuthPrincipal(
            username=str(values.get("DASHBOARD_AUTH_USERNAME") or "hawknetic"),
            role=role,
            auth_method="basic_fallback",
        )
    return None


def build_session_cookie(session_token: str, *, secure: bool) -> str:
    parts = [
        f"{SESSION_COOKIE_NAME}={session_token}",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        "Max-Age=28800",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def clear_session_cookie(*, secure: bool) -> str:
    parts = [
        f"{SESSION_COOKIE_NAME}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        "Max-Age=0",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def render_login_page() -> str:
    return """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Sign in · Hawknetic Predictions</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; --bg:#05090c; --surface:#0b1317; --surface-2:#081014; --muted:#75867f; --text:#f2f8f5; --secondary:#afbeb8; --border:#1d2a30; --accent:#00e676; --accent-deep:#00c853; --purple:#7c4dff; --danger:#ff5252; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; background: radial-gradient(circle at 18% 60%, rgba(0,230,118,.08), transparent 30rem), radial-gradient(circle at 78% 16%, rgba(124,77,255,.07), transparent 28rem), var(--bg); color: var(--text); }
    .login-shell { display: grid; grid-template-columns: minmax(0, 1.05fr) minmax(390px, .95fr); width: min(1180px, calc(100% - 36px)); min-height: 100vh; margin: 0 auto; gap: clamp(40px, 8vw, 110px); align-items: center; padding: 54px 0; }
    .brand { display: inline-flex; align-items: center; gap: 10px; color: var(--text); font-size: 19px; font-weight: 720; letter-spacing: -.045em; text-decoration: none; }
    .brand strong { color: var(--accent); }
    .brand svg { width: 38px; height: 38px; fill: var(--accent); filter: drop-shadow(0 0 12px rgba(0,230,118,.26)); }
    .brand .eye { fill: #04110a; }
    .login-story h1 { max-width: 610px; margin: 44px 0 17px; font-size: clamp(42px, 6vw, 68px); line-height: .98; letter-spacing: -.058em; }
    .login-story h1 span { color: var(--accent); }
    .login-story > p { max-width: 580px; color: var(--secondary); font-size: 16px; line-height: 1.65; }
    .feature-list { display: grid; gap: 14px; margin: 36px 0 0; padding: 0; list-style: none; }
    .feature-list li { display: grid; grid-template-columns: 39px minmax(0,1fr); gap: 13px; align-items: center; }
    .feature-list b { display: grid; place-items: center; width: 39px; height: 39px; border: 1px solid rgba(0,230,118,.23); border-radius: 11px; background: rgba(0,230,118,.07); color: var(--accent); font-size: 17px; }
    .feature-list strong, .feature-list small { display: block; }
    .feature-list strong { color: var(--text); font-size: 13px; }
    .feature-list small { margin-top: 3px; color: var(--muted); font-size: 11px; line-height: 1.45; }
    .research-trust { display: flex; flex-wrap: wrap; gap: 16px; margin-top: 42px; padding-top: 18px; border-top: 1px solid var(--border); color: var(--muted); font-size: 10px; }
    .research-trust span { display: inline-flex; gap: 6px; align-items: center; }
    .research-trust i { width: 7px; height: 7px; border-radius: 50%; background: var(--accent); }
    main { width: 100%; padding: clamp(26px, 4vw, 40px); border: 1px solid var(--border); border-radius: 17px; background: linear-gradient(145deg, rgba(14,23,28,.98), rgba(7,14,18,.98)); box-shadow: 0 32px 90px rgba(0,0,0,.34); }
    .form-kicker { margin: 0 0 10px; color: var(--accent); font-size: 10px; font-weight: 820; letter-spacing: .11em; text-transform: uppercase; }
    h2 { margin: 0; font-size: 31px; line-height: 1.1; letter-spacing: -.035em; }
    main > p:not(.form-kicker) { margin: 9px 0 24px; color: var(--secondary); font-size: 12px; line-height: 1.55; }
    label { display: grid; gap: 8px; margin: 16px 0; color: var(--secondary); font-size: 11px; font-weight: 720; }
    input { width: 100%; min-height: 49px; border: 1px solid var(--border); border-radius: 10px; padding: 11px 13px; background: var(--surface-2); color: var(--text); font: inherit; }
    input::placeholder { color: #56655f; }
    input:focus-visible { outline: 2px solid rgba(0,230,118,.62); outline-offset: 2px; border-color: var(--accent); }
    button { width: 100%; min-height: 49px; margin-top: 7px; border: 0; border-radius: 10px; background: linear-gradient(100deg, var(--accent-deep), #42eca0); color: #03120a; font: inherit; font-weight: 820; cursor: pointer; }
    .login-boundary { margin-top: 23px; border-top: 1px solid var(--border); padding-top: 18px; color: var(--muted); font-size: 10px; line-height: 1.55; text-align: center; }
    #login-status { min-height: 24px; color: var(--danger); }
    @media (max-width: 820px) { .login-shell { grid-template-columns: 1fr; width: min(100% - 26px, 520px); gap: 35px; padding: 34px 0; } .login-story h1 { margin-top: 32px; font-size: 45px; } .feature-list { grid-template-columns: 1fr 1fr; } }
    @media (max-width: 520px) { .login-shell { width: calc(100% - 18px); padding: 18px 0; } .login-story h1 { font-size: 38px; } .login-story > p { font-size: 13px; } .feature-list { grid-template-columns: 1fr; } main { padding: 23px 18px; } }
  </style>
</head>
<body>
  <div class="login-shell">
    <section class="login-story" aria-labelledby="login-story-title">
      <a class="brand" href="/" aria-label="Hawknetic Predictions home">
        <svg viewBox="0 0 48 48" aria-hidden="true"><path d="M6 22.5C12.5 8 29.5 4 42 10c-7.5.5-12.8 2.8-16 6.8 5.6-2.1 10.6-1.7 15 1-7.8 1.2-13.5 4.2-17.2 9 4.8-1.7 9.1-1.3 12.9 1.2-7.4.8-12.6 3.5-15.6 8.1-2.8-3.7-4-7.7-3.4-12.1-3.2 3.1-5 6.9-5.4 11.4C8.2 31.9 6.1 27.7 6 22.5Z"/><path class="eye" d="M27.5 13.5 34 14l-4.8 3.5Z"/></svg>
        <span>Hawknetic<strong>Predictions</strong></span>
      </a>
      <h1 id="login-story-title">Review the data.<br><span>Make your own call.</span></h1>
      <p>A private research workspace for fresh Kalshi source evidence, exact listed combo verification, and transparent review packets.</p>
      <ul class="feature-list">
        <li><b>↻</b><span><strong>Fresh source evidence</strong><small>Timestamped public market snapshots with stale-data blocking.</small></span></li>
        <li><b>◇</b><span><strong>Exact contract validation</strong><small>Only verified listed combinations enter the review workflow.</small></span></li>
        <li><b>▤</b><span><strong>Transparent review packets</strong><small>See every ticker, side, price, event time, and probability source.</small></span></li>
        <li><b>✓</b><span><strong>Research-only controls</strong><small>No automatic trading, order upload, or guaranteed outcomes.</small></span></li>
      </ul>
      <div class="research-trust"><span><i></i>Private workspace</span><span><i></i>Freshness gated</span><span><i></i>Manual review only</span></div>
    </section>
    <main>
      <p class="form-kicker">Private research platform</p>
      <h2>Welcome back</h2>
      <p>Sign in with your research account to open the live builder.</p>
      <form id="login-form">
        <label>Username<input name="username" autocomplete="username" placeholder="Enter your username" required></label>
        <label>Password<input name="password" type="password" autocomplete="current-password" placeholder="Enter your password" required></label>
        <button type="submit">Sign in to Hawknetic Predictions →</button>
        <p id="login-status" role="status" aria-live="polite"></p>
      </form>
      <div class="login-boundary">Research and decision support only. Your account cannot place or upload orders.</div>
    </main>
  </div>
  <script>
    document.querySelector('#login-form').addEventListener('submit', async event => {
      event.preventDefault();
      const status = document.querySelector('#login-status');
      const form = new FormData(event.currentTarget);
      status.textContent = 'Signing in...';
      const response = await fetch('/auth/login', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({username: form.get('username'), password: form.get('password')})
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        status.textContent = payload.error === 'invalid_credentials' ? 'Sign-in failed.' : 'Sign-in is unavailable.';
        return;
      }
      sessionStorage.setItem('research_csrf_token', payload.csrf_token || '');
      window.location.assign('/');
    });
  </script>
</body>
</html>"""


def render_operator_page() -> str:
    priority_options = "".join(
        f'<option value="{value}"{" selected" if value == "normal" else ""}>{value.title()}</option>'
        for value in PRIORITIES
    )
    target_options = "".join(f'<option value="{value}">{value.title()}</option>' for value in TARGETS)
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Private Operator Inbox</title>
  <style>
    :root {{ color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; --bg:#0b0f12; --surface:#11171b; --muted:#879893; --text:#edf4f1; --border:#2a363b; --accent:#29b779; --warning:#d99a2b; }}
    * {{ box-sizing: border-box; }}
    body {{ margin: 0; background: var(--bg); color: var(--text); }}
    main {{ width: min(100% - 28px, 980px); margin: 28px auto 60px; }}
    a {{ color: #8fd2b5; }}
    h1 {{ margin: 0; font-size: 30px; line-height: 1.12; }}
    .notice, form, article {{ border: 1px solid var(--border); border-radius: 8px; background: var(--surface); padding: 18px; }}
    .notice {{ margin: 18px 0; border-color: color-mix(in srgb, var(--warning) 48%, var(--border)); }}
    form {{ display: grid; gap: 14px; }}
    label {{ display: grid; gap: 7px; color: #b8c6c1; font-size: 13px; font-weight: 750; }}
    input, textarea, select, button {{ width: 100%; min-height: 44px; border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; background: #0f1518; color: var(--text); font: inherit; }}
    textarea {{ min-height: 220px; resize: vertical; }}
    input:focus-visible, textarea:focus-visible, select:focus-visible, button:focus-visible, a:focus-visible {{ outline: 2px solid #75b9e6; outline-offset: 2px; }}
    button {{ background: var(--accent); color: #06100c; border-color: var(--accent); font-weight: 800; cursor: pointer; }}
    #queue {{ display: grid; gap: 12px; margin-top: 22px; }}
    article p {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
    .meta {{ color: var(--muted); font-size: .9rem; }}
    .status {{ min-height: 24px; }}
  </style>
</head>
<body>
  <main>
    <p><a href="/">Back to research dashboard</a></p>
    <h1>Private operator inbox</h1>
    <div class="notice"><strong>Manual review only.</strong> Messages placed here are stored as instructions. They never run commands, edit code, deploy, trade, or contact an account automatically.</div>
    <form id="operator-form">
      <label>Title<input name="title" maxlength="200" required></label>
      <label>Priority<select name="priority">{priority_options}</select></label>
      <label>Target<select name="target">{target_options}</select></label>
      <label>Message for Codex or the operator<textarea name="body" maxlength="100000" required></textarea></label>
      <button type="submit">Queue for review</button>
      <div id="form-status" class="status" role="status" aria-live="polite"></div>
    </form>
    <section id="queue" aria-label="Queued operator messages"></section>
  </main>
  <script>
    const csrfToken = sessionStorage.getItem('research_csrf_token') || '';
    const queue = document.querySelector('#queue');
    const formStatus = document.querySelector('#form-status');

    function renderMessages(messages) {{
      queue.replaceChildren();
      for (const message of messages) {{
        const card = document.createElement('article');
        const heading = document.createElement('h2');
        heading.textContent = message.title;
        const meta = document.createElement('div');
        meta.className = 'meta';
        meta.textContent = `${{message.priority}} / ${{message.target}} / ${{message.status}} / ${{message.message_id}}`;
        const body = document.createElement('p');
        body.textContent = message.body;
        card.append(heading, meta, body);
        queue.append(card);
      }}
      if (!messages.length) {{
        const empty = document.createElement('article');
        empty.textContent = 'No messages are queued.';
        queue.append(empty);
      }}
    }}

    async function loadQueue() {{
      const response = await fetch('/internal/operator-messages.json', {{headers: {{'Accept': 'application/json'}}}});
      if (!response.ok) return;
      const payload = await response.json();
      renderMessages(payload.messages || []);
    }}

    document.querySelector('#operator-form').addEventListener('submit', async event => {{
      event.preventDefault();
      const formElement = event.currentTarget;
      formStatus.textContent = 'Queueing for manual review...';
      const form = new FormData(formElement);
      const headers = {{'Content-Type': 'application/json'}};
      if (csrfToken) headers['X-CSRF-Token'] = csrfToken;
      const response = await fetch('/internal/operator-messages', {{
        method: 'POST',
        headers,
        body: JSON.stringify({{
          title: form.get('title'),
          body: form.get('body'),
          priority: form.get('priority'),
          target: form.get('target')
        }})
      }});
      const payload = await response.json().catch(() => ({{}}));
      if (!response.ok) {{
        formStatus.textContent = `Message was not queued: ${{payload.error || 'request_failed'}}`;
        return;
      }}
      formStatus.textContent = 'Queued. No automatic action was taken.';
      formElement.reset();
      await loadQueue();
    }});

    loadQueue();
  </script>
</body>
</html>"""


def valid_refresh_action(headers: Mapping[str, str] | None) -> bool:
    if headers is None:
        return False
    value = str(headers.get(REFRESH_ACTION_HEADER) or "")
    return secrets.compare_digest(value, REFRESH_ACTION_VALUE)


def dashboard_security_headers() -> dict[str, str]:
    return {
        "Content-Security-Policy": (
            "default-src 'self'; base-uri 'none'; frame-ancestors 'none'; "
            "form-action 'self'; img-src 'self' data:; connect-src 'self'; "
            "script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'"
        ),
        "Cross-Origin-Opener-Policy": "same-origin",
        "Cross-Origin-Resource-Policy": "same-origin",
        "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
        "Referrer-Policy": "no-referrer",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "DENY",
    }


def append_jsonl(path: Path, payload: dict) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, sort_keys=True) + "\n")
    except OSError:
        return


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def safe_dashboard_payload(payload: dict) -> dict:
    return gate_slip_payload(
        payload,
        max_age_seconds=_env_int(
            "DASHBOARD_MAX_SLIP_AGE_SECONDS",
            DEFAULT_DASHBOARD_MAX_SLIP_AGE_SECONDS,
        ),
    )


def build_detail_collection_payload(
    payload: dict,
    collection: str,
    query: Mapping[str, list[str]] | None = None,
) -> dict:
    """Return one bounded, freshness-gated collection for authenticated clients."""
    if collection not in {"games", "markets"}:
        raise ValueError(f"unsupported_detail_collection:{collection}")
    query = query or {}

    def bounded_integer(name: str, default: int, maximum: int) -> int:
        raw = (query.get(name) or [str(default)])[0]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            value = default
        return max(0, min(value, maximum))

    records = list(payload.get(collection) or [])
    total_count = len(records)
    gate = payload.get("public_data_gate") or {}
    ready = gate.get("status") == "ready"
    offset = bounded_integer("offset", 0, total_count)
    limit = bounded_integer("limit", DEFAULT_DETAIL_PAGE_SIZE, MAX_DETAIL_PAGE_SIZE)
    visible = records[offset : offset + limit] if ready and limit else []
    next_offset = offset + len(visible)
    if next_offset >= total_count or not ready:
        next_offset = None
    return {
        "collection": collection,
        "generated_at": payload.get("generated_at"),
        "public_data_gate": gate,
        "status": "ready" if ready else "withheld",
        "total_count": total_count,
        "returned_count": len(visible),
        "withheld_count": 0 if ready else total_count,
        "offset": offset,
        "limit": limit,
        "next_offset": next_offset,
        "items": visible,
    }


def build_data_catalog_payload(payload: dict) -> dict:
    """Describe authenticated data routes without copying full source payloads."""
    gate = payload.get("public_data_gate") or {}
    ready = gate.get("status") == "ready"
    return {
        "generated_at": payload.get("generated_at"),
        "status": "ready" if ready else "withheld",
        "public_data_gate": gate,
        "collections": {
            "games": {
                "count": len(payload.get("games") or []),
                "href": "/api/v1/games?limit=50&offset=0",
            },
            "markets": {
                "count": len(payload.get("markets") or []),
                "href": "/api/v1/markets?limit=50&offset=0",
            },
            "sports": {"href": "/sports.json?detail=full"},
            "sports_clv": {"href": "/sports-clv.json"},
        },
    }


def build_service_readiness(payload: dict) -> dict:
    gate = slip_payload_gate(
        payload,
        max_age_seconds=_env_int(
            "DASHBOARD_MAX_SLIP_AGE_SECONDS",
            DEFAULT_DASHBOARD_MAX_SLIP_AGE_SECONDS,
        ),
    )
    database = database_startup_status()
    safety = production_safety_status()
    authentication_required = dashboard_auth_enabled()
    authentication_configured = dashboard_auth_configured()
    ready = (
        gate["status"] == "ready"
        and bool(database.get("ready"))
        and safety["ready"]
        and authentication_configured
    )
    return {
        "status": "ready" if ready else "blocked",
        "service": "kalshi-research-dashboard",
        "data_gate": gate["code"],
        "generated_at": payload.get("generated_at"),
        "database": {
            "backend": database.get("backend") or database.get("dialect"),
            "state": database.get("state"),
            "ready": bool(database.get("ready")),
            "pending_versions": database.get("pending_versions", []),
        },
        "authentication": {
            "required": authentication_required,
            "configured": authentication_configured,
        },
        "production_safety": safety,
    }


def _paper_run_exists(store: PostgresStore, run_id: str) -> bool:
    with store.connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM app.paper_test_runs WHERE run_id = %s LIMIT 1",
            (run_id,),
        ).fetchone()
    return bool(row)


def _ensure_paper_run(store: PostgresStore, run_id: str) -> bool:
    from .evaluation.paper_live import start_paper_test_run

    run = start_paper_test_run(store, run_id=run_id)
    return bool(run.get("created"))


def log_refresh_predictions(payload: dict) -> dict:
    from .evaluation.paper_live import log_forward_predictions

    run_id = os.environ.get("KALSHI_RUN_ID") or DEFAULT_KALSHI_RUN_ID
    max_payload_age_seconds = _env_int(
        "KALSHI_PAPER_MAX_PAYLOAD_AGE_SECONDS",
        DEFAULT_REFRESH_LEDGER_MAX_PAYLOAD_AGE_SECONDS,
    )
    store = create_store()
    run_created = _ensure_paper_run(store, run_id)
    result = log_forward_predictions(
        store,
        payload,
        run_id=run_id,
        max_payload_age_seconds=max_payload_age_seconds,
    )
    return {
        "ok": True,
        "run_id": result.get("run_id", run_id),
        "run_created": run_created,
        "database_backend": "postgres",
        "max_payload_age_seconds": max_payload_age_seconds,
        "attempted_predictions": result.get("attempted_predictions", 0),
        "logged_predictions": result.get("logged_predictions", 0),
        "rejected_predictions": result.get("rejected_predictions", 0),
        "duplicate_rows_ignored": result.get("duplicate_rows_ignored", 0),
        "rejection_reasons": result.get("rejection_reasons", []),
        "prediction_timestamp": result.get("prediction_timestamp"),
    }


def latest_jsonl(path: Path, limit: int = 20) -> list[dict]:
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").splitlines()[-limit:]
    except OSError:
        return []
    rows = []
    for line in lines:
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def build_quality_status(payload: dict, audit_path: Path, error_path: Path) -> dict:
    generated_at = payload.get("generated_at")
    age_seconds = None
    if generated_at:
        try:
            generated = datetime.fromisoformat(str(generated_at))
            age_seconds = max(0, int(datetime.now().astimezone().timestamp() - generated.timestamp()))
        except ValueError:
            age_seconds = None
    latest_errors = latest_jsonl(error_path, 5)
    audit_rows = latest_jsonl(audit_path, 10)
    slip_counts = {
        "primary": int((payload.get("custom_slip") or {}).get("leg_count") or 0),
        "leverage": int((payload.get("leverage_slip") or {}).get("leg_count") or 0),
        "all_day": int((payload.get("all_day_slip") or {}).get("leg_count") or 0),
        "research_edge": int((payload.get("research_edge_slip") or {}).get("leg_count") or 0),
    }
    warnings = []
    if payload.get("refresh_error"):
        warnings.append("latest refresh has an error")
    if age_seconds is not None and age_seconds > 1800:
        warnings.append("data is older than 30 minutes")
    if not any(slip_counts.values()):
        warnings.append("no slips are currently built")
    source_quality_gate = build_dashboard_quality_gate(
        payload,
        audit_rows=audit_rows,
        latest_errors=latest_errors,
    )
    for reason in source_quality_gate.get("reasons", []):
        if reason not in warnings:
            warnings.append(reason)
    return {
        "status": "WATCH" if warnings else "OK",
        "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "generated_at": generated_at,
        "data_age_seconds": age_seconds,
        "slip_counts": slip_counts,
        "source_quality_gate": source_quality_gate,
        "metric_contamination_checks": {
            "manual_review_only": True,
            "auto_trade_enabled": False,
            "auto_bet_enabled": False,
            "kalshi_order_upload_enabled": False,
            "unresolved_rows_excluded_from_metrics": True,
            "rejected_rows_excluded_from_metrics": True,
        },
        "audit_events": len(audit_rows),
        "latest_errors": latest_errors,
        "warnings": warnings,
        "controls": {
            "frontend": "local responsive dashboard",
            "api": "/healthz, /readyz, /data.json, /refresh-status, /quality.json, /research-record.json, /review-packet.json, /review-packet.txt, POST /refresh",
            "cache": "short-lived file cache for public API responses",
            "rate_limit": f"manual refresh cooldown {REFRESH_COOLDOWN_SECONDS}s plus no-overlap lock",
            "audit": str(audit_path),
            "error_tracking": str(error_path),
            "security": "hosted authentication required by default; no automatic trade execution",
        },
    }


def load_payload(path: Path) -> dict:
    if not path.exists():
        return {
            "date": "",
            "games": [],
            "markets": [],
            "safety_note": "Run the today command first to generate data.",
        }
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "date": "",
            "games": [],
            "markets": [],
            "safety_note": "Data file is being refreshed. Reload in a few seconds.",
            "refresh_error": f"{type(exc).__name__}: {exc}",
        }


def blocked_dashboard_payload(code: str, message: str) -> dict:
    return {
        "date": "",
        "generated_at": None,
        "games": [],
        "markets": [],
        "safety_note": message,
        "refresh_error": code,
    }


def load_current_payload(path: Path) -> dict:
    source = str(os.environ.get("DASHBOARD_PAYLOAD_SOURCE") or "postgres").strip().lower()
    if source == "file":
        if hosted_runtime():
            return blocked_dashboard_payload(
                "hosted_file_payload_forbidden",
                "Hosted dashboards require the PostgreSQL collector snapshot.",
            )
        return load_payload(path)
    if source != "postgres":
        return blocked_dashboard_payload(
            "invalid_dashboard_payload_source",
            "The configured dashboard data source is invalid.",
        )
    try:
        payload = load_latest_kalshi_snapshot()
    except Exception as exc:
        print(f"Dashboard PostgreSQL snapshot unavailable: {type(exc).__name__}")
        return blocked_dashboard_payload(
            "postgres_snapshot_unavailable",
            "The PostgreSQL-backed Kalshi snapshot is unavailable.",
        )
    if payload is None:
        return blocked_dashboard_payload(
            "postgres_snapshot_missing",
            "No collector-backed Kalshi snapshot has been stored yet.",
        )
    return payload


def write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    temporary_path.replace(path)


def cleanup_runtime_storage() -> dict:
    if not _env_flag(os.environ, "KALSHI_RUNTIME_CLEANUP_ENABLED", True):
        return {"ok": True, "skipped": True, "reason": "runtime_cleanup_disabled"}
    try:
        result = prune_http_cache()
        if result.get("deleted_files"):
            print(
                "Runtime cleanup pruned "
                f"{result.get('deleted_files')} cache files "
                f"({int(result.get('deleted_bytes') or 0)} bytes)."
            )
        return result
    except Exception as exc:
        result = {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        print(f"Runtime cleanup failed: {result['error']}")
        return result


def money(value: object) -> str:
    if value is None or value == "":
        return "n/a"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return html.escape(str(value))


def percent(value: object, decimals: int = 2) -> str:
    try:
        return f"{float(value) * 100:.{decimals}f}%"
    except (TypeError, ValueError):
        return "n/a"


def display_timestamp(value: object) -> str:
    if not value:
        return "pending"
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return html.escape(str(value))
    if stamp.tzinfo is not None:
        stamp = stamp.astimezone()
    return stamp.strftime("%b %d, %I:%M %p").replace(" 0", " ").replace(", 0", ", ")


def display_event_time(value: object) -> str:
    if not value:
        return "Time TBD"
    try:
        stamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return "Time TBD"
    if stamp.tzinfo is not None:
        today = datetime.now(stamp.tzinfo).date()
    else:
        today = datetime.now().date()
    day_delta = (stamp.date() - today).days
    if day_delta == 0:
        day_text = "Today"
    elif day_delta == 1:
        day_text = "Tomorrow"
    else:
        day_text = stamp.strftime("%b %d").replace(" 0", " ")
    time_text = stamp.strftime("%I:%M %p").lstrip("0")
    return f"{day_text} · {time_text}"


def slip_copy_text(slip: dict, label: str) -> str:
    if slip.get("action") != "BUILD_SLIP":
        return f"{label}\nNo slip generated."
    lines = [
        label,
        f"Legs: {slip.get('leg_count', 0)}",
        f"Est. price: {money(slip.get('estimated_combo_price_cents'))}c",
        f"$5 payout if right: ${money(slip.get('estimated_payout_if_right'))}",
        "",
    ]
    for index, leg in enumerate(slip.get("legs", []), start=1):
        event = leg.get("display_event") or leg.get("event_ticker") or "Unknown event"
        side = str(leg.get("side", "")).upper()
        label_text = leg.get("subtitle") or leg.get("title") or leg.get("market_ticker", "")
        probability = percent(leg.get("probability"))
        if leg.get("research_probability") is not None:
            kalshi = percent(leg.get("kalshi_probability"))
            margin = percent(leg.get("margin_of_error"))
            evidence_count = leg.get("evidence_count", 0)
            lines.append(f"{index}. {event} - {side} {label_text} (model {probability}, Kalshi {kalshi}, +/-{margin}, {evidence_count} sources)")
        else:
            lines.append(f"{index}. {event} - {side} {label_text} ({probability})")
    return "\n".join(lines)


def render_brand() -> str:
    return """
    <a class="brand" href="#builder" aria-label="Hawknetic Predictions builder">
      <svg class="brand-mark" viewBox="0 0 48 48" aria-hidden="true">
        <path d="M6 22.5C12.5 8 29.5 4 42 10c-7.5.5-12.8 2.8-16 6.8 5.6-2.1 10.6-1.7 15 1-7.8 1.2-13.5 4.2-17.2 9 4.8-1.7 9.1-1.3 12.9 1.2-7.4.8-12.6 3.5-15.6 8.1-2.8-3.7-4-7.7-3.4-12.1-3.2 3.1-5 6.9-5.4 11.4C8.2 31.9 6.1 27.7 6 22.5Z"/>
        <path class="brand-eye" d="M27.5 13.5 34 14l-4.8 3.5Z"/>
      </svg>
      <span>Hawknetic<strong>Predictions</strong></span>
    </a>
    """


def render_market_browser(payload: dict) -> str:
    markets = list(payload.get("markets") or [])
    gate = payload.get("public_data_gate") or {}
    if gate.get("status") != "ready":
        return f"""
        <div class="product-empty-state">
          <span class="empty-state-icon" aria-hidden="true">!</span>
          <strong>Kalshi contracts temporarily hidden</strong>
          <p>{html.escape(str(gate.get("message") or "Fresh Kalshi evidence is required before contracts can be shown."))}</p>
        </div>
        """
    if not markets:
        heading = "No verified contracts available"
        message = "The current Kalshi response is fresh, but no exact listed combo contracts meet the review requirements."
        return f"""
        <div class="product-empty-state">
          <span class="empty-state-icon" aria-hidden="true">⌁</span>
          <strong>{html.escape(heading)}</strong>
          <p>{html.escape(message)}</p>
        </div>
        """
    visible_markets = sorted(
        markets,
        key=lambda market: (
            not bool(market.get("real_data_ready")),
            -(float(market.get("volume_24h") or 0) if str(market.get("volume_24h") or "").replace(".", "", 1).isdigit() else 0),
            str(market.get("ticker") or ""),
        ),
    )[:8]
    rows = "".join(render_market_browser_row(market) for market in visible_markets)
    return f'<div class="market-browser-list">{rows}</div>'


def market_public_quote_state(market: dict) -> str:
    explicit = str(market.get("public_quote_state") or "").lower()
    if explicit in {"tradable", "rfq_required", "unavailable"}:
        return explicit
    try:
        yes_ask = float(market.get("yes_ask_cents") or 0)
        yes_bid = float(market.get("yes_bid_cents") or 0)
        no_ask = float(market.get("no_ask_cents") or 0)
        no_bid = float(market.get("no_bid_cents") or 0)
    except (TypeError, ValueError):
        return "unavailable"
    if 0 < yes_ask < 100:
        return "tradable"
    if (
        str(market.get("ticker") or "").upper().startswith("KXMVE")
        and str(market.get("status") or "").lower() in {"active", "open"}
        and (yes_ask, yes_bid, no_ask, no_bid) == (0, 0, 100, 100)
    ):
        return "rfq_required"
    return "unavailable"


def render_market_browser_row(market: dict) -> str:
    ticker = str(market.get("ticker") or "Unidentified contract")
    title = str(market.get("title") or ticker)
    legs = list(market.get("leg_details") or [])
    leg_count = len(legs) or len(market.get("legs") or [])
    ready = bool(market.get("real_data_ready"))
    quote_state = market_public_quote_state(market)
    if quote_state == "rfq_required" and ready:
        status_text = "RFQ required"
        status_class = "warning"
        yes_quote = "RFQ required"
        no_quote = "No public quote"
        quote_message = str(
            market.get("public_quote_message")
            or "Kalshi requires an authenticated RFQ for this exact combo; the public orderbook has no executable price."
        )
    elif quote_state == "tradable" and ready:
        status_text = "Quoted"
        status_class = "good"
        yes_quote = f"{money(market.get('yes_ask_cents'))}c"
        no_quote = f"{money(market.get('no_ask_cents'))}c"
        quote_message = str(market.get("real_data_warning") or "Public Kalshi combo quote is available.")
    else:
        status_text = "Incomplete"
        status_class = "warning"
        yes_quote = "Unavailable"
        no_quote = "Unavailable"
        quote_message = str(market.get("real_data_warning") or "No public executable combo quote is available.")
    close_text = display_event_time(market.get("close_time"))
    priced_probabilities = [
        float(leg["market_implied_probability"]) * 100
        for leg in legs
        if leg.get("market_implied_probability") is not None
    ]
    probability_preview = " · ".join(f"{value:.1f}%" for value in priced_probabilities[:4])
    leg_price_summary = (
        f"{len(priced_probabilities)} priced underlying legs"
        + (f" · {probability_preview}" if probability_preview else "")
    )
    search_text = " ".join(
        [
            ticker,
            title,
            *(str(leg.get("display_event") or leg.get("title") or leg.get("market_ticker") or "") for leg in legs),
        ]
    ).lower()
    detail_items = "".join(render_market_preview_leg(leg) for leg in legs)
    if not detail_items:
        detail_items = '<li class="market-preview-empty">Underlying leg details are not available.</li>'
    return f"""
    <article class="market-browser-row" data-search="{html.escape(search_text, quote=True)}">
      <div class="market-browser-heading">
        <span class="contract-orb" aria-hidden="true"></span>
        <div>
          <strong>{html.escape(title)}</strong>
          <small>{html.escape(ticker)} · {leg_count} exact legs · closes {html.escape(close_text)}</small>
          <small>{html.escape(leg_price_summary)}</small>
        </div>
      </div>
      <div class="market-quote-cell"><small>Combo YES</small><strong>{html.escape(yes_quote)}</strong></div>
      <div class="market-quote-cell"><small>Combo NO</small><strong>{html.escape(no_quote)}</strong></div>
      <div class="market-quote-cell"><small>24h volume</small><strong>{html.escape(str(market.get("volume_24h") or "n/a"))}</strong></div>
      <span class="pill {status_class}">{status_text}</span>
      <details class="market-browser-details">
        <summary>View {len(priced_probabilities)} priced exact legs</summary>
        <ul>{detail_items}</ul>
        <p>{html.escape(quote_message)}</p>
      </details>
    </article>
    """


def render_market_preview_leg(leg: dict) -> str:
    event = leg.get("display_event") or leg.get("event_ticker") or "Event"
    label = leg.get("subtitle") or leg.get("title") or leg.get("market_ticker") or "Market"
    probability = leg.get("market_implied_probability")
    probability_text = "n/a" if probability is None else f"{float(probability) * 100:.1f}%"
    return (
        "<li>"
        f"<span><strong>{html.escape(str(event))}</strong><small>{html.escape(str(leg.get('side') or '').upper())} · {html.escape(str(label))}</small></span>"
        f"<b>{html.escape(probability_text)}</b>"
        "</li>"
    )


SPORTS_BOARD_STATE_COPY = {
    "blocked": (
        "Sports collection is blocked",
        "The public sports source refused or failed its last collection. No rows are shown until it recovers.",
    ),
    "stale": (
        "Sports odds are stale",
        "The newest uploaded sports row is older than the freshness window, so the board is withheld rather than shown as current.",
    ),
    "unavailable": (
        "No sports rows uploaded yet",
        "The sports-research worker has not written any validated rows to this database.",
    ),
    "empty": (
        "No upcoming games with posted odds",
        "The collector is fresh, but every uploaded game has already started or has no usable odds.",
    ),
}


def safe_sports_board() -> dict:
    """Load the sports board, degrading to an explicit unavailable state.

    An optional read must never make a healthy Kalshi dashboard look broken, so a
    database or collector problem becomes a named state instead of a 500.
    """
    try:
        return load_sports_board()
    except Exception as exc:  # noqa: BLE001 - surfaced to the operator as a board state
        return {
            "asset_class": "sports",
            "board_state": "unavailable",
            "state_reason": f"sports_board_unavailable:{type(exc).__name__}",
            "is_current": False,
            "events": [],
            "event_count": 0,
            "withheld_event_count": 0,
            "quote_count": 0,
            "source_health": [],
            "worker": None,
            "model_state": "baseline_only",
            "decision_status": "track_only",
        }


def safe_sports_clv_report() -> dict:
    """Load the CLV report, degrading to an empty one on any database problem."""
    try:
        return build_sports_clv_report()
    except Exception as exc:  # noqa: BLE001 - surfaced as an empty report, not a 500
        return {
            "graded_rows": 0,
            "pending_rows": 0,
            "beat_close": 0,
            "lost_to_close": 0,
            "matched_close": 0,
            "beat_rate": None,
            "beat_rate_denominator": 0,
            "average_clv": None,
            "by_market": [],
            "by_bookmaker": [],
            "unavailable_reason": f"sports_clv_unavailable:{type(exc).__name__}",
        }


def render_sports_clv_panel(report: dict) -> str:
    graded = int(report.get("graded_rows") or 0)
    if graded == 0:
        reason = str(
            report.get("unavailable_reason")
            or "No sports market has closed yet, so no price can be compared against a closing line."
        )
        return f"""
        <div class="decision warning">
          <div class="status-heading"><strong>No closing lines recorded</strong><span>0 graded</span></div>
          <p class="status-note">{html.escape(reason)}</p>
        </div>
        """
    beat = int(report.get("beat_close") or 0)
    lost = int(report.get("lost_to_close") or 0)
    matched = int(report.get("matched_close") or 0)
    beat_rate = report.get("beat_rate")
    beat_rate_text = "n/a" if beat_rate in {None, ""} else percent(beat_rate, 1)
    average = report.get("average_clv")
    try:
        average_value = float(average) if average not in {None, ""} else 0.0
    except (TypeError, ValueError):
        average_value = 0.0
    # Beating the close more often than not is the signal worth showing; it is still
    # a price comparison, never a profitability claim.
    decision_class = "good" if average_value > 0 else "warning"
    average_text = f"{average_value * 100:+.2f} pts"
    market_rows = "".join(
        f"<li><span><strong>{html.escape(str(entry.get('market_type') or 'market'))}</strong>"
        f"<small>{int(entry.get('graded_rows') or 0)} graded · {int(entry.get('beat_close') or 0)} beat close</small></span>"
        f"<b>{_clv_points_text(entry.get('average_clv'))}</b></li>"
        for entry in (report.get("by_market") or [])
    )
    book_rows = "".join(
        f"<li><span><strong>{html.escape(str(entry.get('bookmaker') or 'book'))}</strong>"
        f"<small>{int(entry.get('graded_rows') or 0)} graded · {int(entry.get('beat_close') or 0)} beat close</small></span>"
        f"<b>{_clv_points_text(entry.get('average_clv'))}</b></li>"
        for entry in (report.get("by_bookmaker") or [])[:6]
    )
    return f"""
    <div class="decision status-decision {decision_class}">
      <div class="status-heading"><strong>Closing line value</strong><span>{average_text} average</span></div>
      <p class="status-note">Price comparison against each market's last pre-start quote. Not profit and not a settled result.</p>
      <div class="metric-strip status-metrics">
        <span><small>Graded</small><strong>{graded}</strong></span>
        <span><small>Beat close</small><strong>{beat}</strong></span>
        <span><small>Lost to close</small><strong>{lost}</strong></span>
        <span><small>Matched</small><strong>{matched}</strong></span>
        <span><small>Beat rate</small><strong>{html.escape(beat_rate_text)}</strong></span>
        <span><small>Awaiting close</small><strong>{int(report.get("pending_rows") or 0)}</strong></span>
      </div>
      <details class="market-browser-details">
        <summary>Break down by market and book</summary>
        <ul>{market_rows}{book_rows}</ul>
      </details>
    </div>
    """


def _clv_points_text(value: object) -> str:
    try:
        return f"{float(value) * 100:+.2f} pts"
    except (TypeError, ValueError):
        return "n/a"


def format_american_odds(value: object) -> str:
    """Render an exact stored price as a bettor reads it (+110, -120)."""
    if value in {None, ""}:
        return "n/a"
    try:
        number = float(value)
    except (TypeError, ValueError):
        return html.escape(str(value))
    rendered = f"{number:g}"
    return f"+{rendered}" if number > 0 else rendered


def render_sports_section(board: dict) -> str:
    if not board.get("is_current"):
        state = str(board.get("board_state") or "unavailable")
        heading, message = SPORTS_BOARD_STATE_COPY.get(
            state, ("Sports board unavailable", "The sports board could not be built from the current database state.")
        )
        reason = str(board.get("state_reason") or "")
        withheld = int(board.get("withheld_event_count") or 0)
        withheld_note = (
            f"<p>{withheld} collected event(s) are held back because they are not current.</p>" if withheld else ""
        )
        return f"""
        <div class="product-empty-state">
          <span class="empty-state-icon" aria-hidden="true">◐</span>
          <strong>{html.escape(heading)}</strong>
          <p>{html.escape(message)}</p>
          {withheld_note}
          <p class="sports-state-reason">{html.escape(reason)}</p>
        </div>
        """
    events = list(board.get("events") or [])[:8]
    rows = "".join(render_sports_event(event) for event in events)
    return f'<div class="sports-board-list">{rows}</div>'


def render_sports_event(event: dict) -> str:
    markets = "".join(render_sports_market(market) for market in event.get("markets") or [])
    league = str(event.get("league") or "").upper()
    start_text = display_event_time(event.get("game_start_time"))
    search_text = " ".join(
        [
            str(event.get("away_team") or ""),
            str(event.get("home_team") or ""),
            league,
            *(str(market.get("market_type") or "") for market in event.get("markets") or []),
        ]
    ).lower()
    return f"""
    <article class="sports-event" data-league="{html.escape(league, quote=True)}" data-search="{html.escape(search_text, quote=True)}">
      <div class="sports-event-heading">
        <span class="contract-orb" aria-hidden="true"></span>
        <div>
          <strong>{html.escape(str(event.get("away_team") or "Away"))} @ {html.escape(str(event.get("home_team") or "Home"))}</strong>
          <small>{html.escape(league)} · {html.escape(start_text)} · {int(event.get("market_count") or 0)} markets</small>
        </div>
      </div>
      <div class="sports-market-list">{markets}</div>
    </article>
    """


def format_market_line(value: object, market_type: str) -> str:
    """Spreads carry a sign; totals are a bare number ("8.5", not "+8.5")."""
    if value in {None, ""}:
        return ""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return html.escape(str(value))
    rendered = f"{number:g}"
    if "spread" in market_type.strip().lower() and number > 0:
        return f"+{rendered}"
    return rendered


def render_sports_market(market: dict) -> str:
    market_type = str(market.get("market_type") or "market")
    selections = "".join(
        render_sports_selection(entry, market_type) for entry in market.get("selections") or []
    )
    # Spread sides carry their own signed line, so the heading stays unqualified.
    line_rendered = "" if "spread" in market_type.lower() else format_market_line(market.get("line"), market_type)
    line_text = f" {line_rendered}" if line_rendered else ""
    overround = market.get("overround")
    if market.get("no_vig_available"):
        vig_text = f"Overround {percent(overround, 2)}"
    else:
        vig_text = "One-sided market · no de-vig"
    books = int(market.get("bookmaker_count") or 0)
    return f"""
    <div class="sports-market">
      <div class="sports-market-head">
        <strong>{html.escape(market_type.title())}{html.escape(line_text)}</strong>
        <small>{books} book{"s" if books != 1 else ""} · {html.escape(vig_text)}</small>
      </div>
      <div class="sports-selection-list">{selections}</div>
    </div>
    """


def render_sports_selection(entry: dict, market_type: str = "") -> str:
    fair = entry.get("no_vig_probability")
    fair_text = "n/a" if fair in {None, ""} else percent(fair, 1)
    gain = entry.get("line_shopping_gain_probability")
    try:
        gain_value = float(gain) if gain not in {None, ""} else 0.0
    except (TypeError, ValueError):
        gain_value = 0.0
    gain_html = (
        f'<span class="pill good sports-shop-pill">Shop +{gain_value * 100:.1f}%</span>' if gain_value > 0 else ""
    )
    line_rendered = format_market_line(entry.get("line"), market_type)
    name = str(entry.get("selection") or "Selection")
    label = f"{name} {line_rendered}" if line_rendered else name
    return f"""
    <div class="sports-selection">
      <span class="sports-selection-name">{html.escape(label)}</span>
      <span class="sports-selection-odds">{html.escape(format_american_odds(entry.get("best_odds")))}</span>
      <span class="sports-selection-book">{html.escape(str(entry.get("best_bookmaker") or "n/a"))}</span>
      <span class="sports-selection-fair"><small>No-vig</small><b>{html.escape(fair_text)}</b></span>
      {gain_html}
    </div>
    """


def render_compact_slip(slip: dict, source_payload: dict) -> str:
    if slip.get("action") != "BUILD_SLIP":
        reason = str(slip.get("reason") or "No exact listed combo currently meets the review rules.")
        source_context = combo_source_context(source_payload, "primary")
        summary = source_payload.get("combo_source_summary") or {}
        exact_count = int(summary.get("verified_current_day_contract_count") or 0)
        quoted_count = int(summary.get("tradable_kxmve_market_count") or 0)
        rfq_count = int(summary.get("rfq_required_kxmve_market_count") or 0)
        watch_markets = sorted(
            [market for market in source_payload.get("markets") or [] if market.get("real_data_ready")],
            key=lambda market: (
                market_public_quote_state(market) != "tradable",
                -(float(market.get("adjusted_market_implied_probability") or 0)),
            ),
        )[:4]
        watch_items = "".join(render_drawer_watch_market(market) for market in watch_markets)
        return f"""
        <div class="drawer-slip-state">
          <span class="pill warning">Watchlist only</span>
          <strong>Exact combination research</strong>
          <small>Fresh source-backed markets, no account automation</small>
        </div>
        <div class="drawer-alert">
          <span aria-hidden="true">△</span>
          <p>{html.escape(reason)} Unpriced combinations remain blocked until Kalshi exposes an executable quote.</p>
        </div>
        <div class="drawer-metrics">
          <span><small>Exact today</small><strong>{exact_count}</strong></span>
          <span><small>Public quotes</small><strong>{quoted_count}</strong></span>
          <span><small>Awaiting RFQ</small><strong>{rfq_count}</strong></span>
        </div>
        <div class="drawer-watchlist-head"><strong>Top live combinations</strong><span>{len(watch_markets)} shown</span></div>
        <ul class="drawer-watchlist">{watch_items}</ul>
        {f'<p class="drawer-source-context">{html.escape(source_context)}</p>' if source_context else ''}
        <a class="drawer-primary-link" href="#market-browser">Review all live combinations <span>→</span></a>
        """
    label = "PRIMARY 80c+ REVIEW SLIP"
    fallback_copy_text = slip_copy_text(slip, label)
    review_packet = build_review_packet(
        {
            "date": source_payload.get("date"),
            "generated_at": source_payload.get("generated_at"),
            "generated_at_note": source_payload.get("generated_at_note"),
            "custom_slip": slip,
        },
        "primary",
    )
    review_text = review_packet.get("copy_blocks", {}).get("review_packet") or fallback_copy_text
    compact_legs = "".join(render_compact_slip_leg(leg) for leg in list(slip.get("legs") or [])[:10])
    hidden_leg_count = max(0, int(slip.get("leg_count") or 0) - 10)
    compatibility = slip.get("combo_compatibility") or {}
    manual_ready = bool(compatibility.get("manual_entry_ready", slip.get("manual_entry_ready")))
    status_text = "Ready to review" if manual_ready else "Review required"
    status_class = "good" if manual_ready else "warning"
    return f"""
    <div class="drawer-slip-state">
      <span class="pill {status_class}">{status_text}</span>
      <strong>{int(slip.get("leg_count") or 0)} listed legs</strong>
      <small>One exact active Kalshi combo contract</small>
    </div>
    <div class="drawer-alert">
      <span aria-hidden="true">△</span>
      <p>Manual review only. Confirm every side, price, and event start time before acting.</p>
    </div>
    <div class="drawer-metrics">
      <span><small>Price</small><strong>{money(slip.get("estimated_combo_price_cents"))}c</strong></span>
      <span><small>Implied chance</small><strong>{float(slip.get("adjusted_probability") or 0) * 100:.2f}%</strong></span>
      <span><small>Est. $5 payout</small><strong>${money(slip.get("estimated_payout_if_right"))}</strong></span>
    </div>
    <ul class="drawer-leg-list">{compact_legs}</ul>
    {f'<p class="drawer-more">+{hidden_leg_count} more listed legs in the full review</p>' if hidden_leg_count else ''}
    <button type="button" class="copy drawer-primary-action" data-copy="{html.escape(review_text, quote=True)}">Copy Review Packet</button>
    <div class="drawer-action-row">
      <a href="#primary">Full slip details</a>
      <a href="/review-packet.txt?slip=primary" download>Download TXT</a>
    </div>
    """


def render_drawer_watch_market(market: dict) -> str:
    title = str(market.get("title") or market.get("ticker") or "Exact Kalshi combination")
    legs = list(market.get("leg_details") or [])
    priced_count = sum(1 for leg in legs if leg.get("market_implied_probability") is not None)
    quote_state = market_public_quote_state(market)
    state_text = "Public quote" if quote_state == "tradable" else "RFQ required"
    state_class = "good" if quote_state == "tradable" else "warning"
    probability = market.get("adjusted_market_implied_probability")
    probability_text = "n/a" if probability is None else f"{float(probability) * 100:.1f}%"
    return f"""
    <li>
      <span class="contract-orb" aria-hidden="true"></span>
      <div><strong>{html.escape(title)}</strong><small>{len(legs)} exact legs · {priced_count} priced</small></div>
      <div class="drawer-watch-state"><b>{html.escape(probability_text)}</b><span class="pill {state_class}">{state_text}</span></div>
    </li>
    """


def render_compact_slip_leg(leg: dict) -> str:
    event = leg.get("display_event") or leg.get("event_ticker") or "Event"
    label = leg.get("subtitle") or leg.get("title") or leg.get("market_ticker") or "Market"
    start_time = leg.get("event_start_time") or ""
    probability = float(leg.get("probability") or 0) * 100
    return f"""
    <li>
      <span class="leg-status-dot" aria-hidden="true"></span>
      <div><strong>{html.escape(str(event))}</strong><small>{html.escape(str(leg.get("side") or "").upper())} · {html.escape(str(label))}</small><time datetime="{html.escape(str(start_time), quote=True)}">{html.escape(display_event_time(start_time))}</time></div>
      <b>{probability:.1f}%</b>
    </li>
    """


def render_dashboard(payload: dict, refresh_seconds: int = 0) -> str:
    payload = safe_dashboard_payload(payload)
    games = payload.get("games", [])
    markets = payload.get("markets", [])
    primary_slip = payload.get("custom_slip") or {}
    leverage_slip = payload.get("leverage_slip") or {}
    all_day_slip = payload.get("all_day_slip") or {}
    research_edge_slip = payload.get("research_edge_slip") or {}
    refresh_seconds = max(0, int(refresh_seconds or 0))
    refresh_meta = f'<meta http-equiv="refresh" content="{refresh_seconds}">' if refresh_seconds else ""
    generated_at = payload.get("generated_at") or "pending"
    display_generated_at = display_timestamp(generated_at)
    refresh_label = f"Every {refresh_seconds // 60} min" if refresh_seconds else "Manual"
    refresh_error = payload.get("refresh_error")
    refresh_error_html = (
        '<p class="subtle strong-note">Live refresh delayed. Slips are hidden until fresh data returns.</p>'
        if refresh_error
        else ""
    )
    quality_status = build_quality_status(
        payload,
        repo_path("data", "refresh_audit.jsonl"),
        repo_path("data", "error_events.jsonl"),
    )
    public_data_gate = payload.get("public_data_gate") or {}
    data_is_ready = public_data_gate.get("status") == "ready" and not refresh_error
    data_state = "ready" if data_is_ready else "blocked"
    data_label = "Fresh data" if data_is_ready else "Review blocked"
    data_message = str(public_data_gate.get("message") or "Fresh data is required before slips can be reviewed.")
    data_message_html = (
        f'<p class="data-state-message">{html.escape(data_message)}</p>' if not data_is_ready else ""
    )
    research_record = build_research_record(payload=payload)
    sports_board = safe_sports_board()
    sports_clv = safe_sports_clv_report()
    sports_summary = summarize_sports_board(sports_board)
    sports_state_label = "Live sports" if sports_summary["is_current"] else "Sports withheld"
    sports_summary_text = (
        f"{sports_summary['event_count']} upcoming games · "
        f"{sports_summary['no_vig_market_count']} de-vigged markets · "
        f"{sports_summary['line_shopping_market_count']} priced by more than one book."
        if sports_summary["is_current"]
        else "Sports rows are only shown while the collector is fresh and unblocked."
    )
    payload_json = json.dumps(
        {
            "generated_at": payload.get("generated_at"),
            "public_data_gate": payload.get("public_data_gate"),
        }
    ).replace("</", "<\\/")
    summary = payload.get("combo_source_summary") or {}
    dashboard_snapshot = payload.get("dashboard_snapshot") or {}
    snapshot_source = "PostgreSQL collector feed" if dashboard_snapshot.get("source") == "postgres" else "Local source snapshot"
    verified_contracts = int(summary.get("verified_current_day_contract_count") or 0)
    tradable_contracts = int(summary.get("tradable_kxmve_market_count") or 0)
    rfq_contracts = int(summary.get("rfq_required_kxmve_market_count") or 0)
    league_counts: dict[str, int] = {}
    for event in sports_board.get("events") or []:
        league = str(event.get("league") or "Other").upper()
        league_counts[league] = league_counts.get(league, 0) + 1
    league_labels = {
        "NBA": ("◉", "NBA"),
        "WNBA": ("◉", "WNBA"),
        "NFL": ("◈", "NFL"),
        "MLB": ("◆", "MLB"),
        "NHL": ("◇", "NHL"),
        "SOCCER": ("◌", "Soccer"),
    }
    league_buttons = "".join(
        f'<button type="button" class="sport-filter" data-league="{html.escape(league, quote=True)}">'
        f'<span aria-hidden="true">{icon}</span>{html.escape(label)}<b>{count}</b></button>'
        for league, count in sorted(league_counts.items())
        for icon, label in [league_labels.get(league, ("•", league.title()))]
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>Hawknetic Predictions · Research Builder</title>
  <style>{CSS}</style>
</head>
<body class="product-shell">
  <a class="skip-link" href="#primary">Skip to slips</a>
  <header class="app-topbar">
    <button class="mobile-menu-toggle" id="mobile-menu-toggle" type="button" aria-controls="app-sidebar" aria-expanded="false"><span></span><span></span><span></span><span class="sr-only">Open navigation</span></button>
    {render_brand()}
    <nav class="quick-nav top-navigation" aria-label="Primary navigation">
      <a href="#builder">Builder</a>
      <a href="#record">History</a>
      <a href="#research-edge">Strategies</a>
      <a href="#quality">Alerts</a>
      <a href="#market-browser">Markets</a>
      <a href="#record">Resources</a>
    </nav>
    <div class="topbar-actions">
      <span class="research-only-badge"><i aria-hidden="true"></i>Research only</span>
      <div class="refresh-control">
        <button id="refresh-slip" type="button"><span class="refresh-icon" aria-hidden="true">↻</span><span class="refresh-label">Refresh</span></button>
        <small id="refresh-status" aria-live="polite">Ready</small>
      </div>
    </div>
  </header>

  <div class="app-frame">
    <aside class="app-sidebar" id="app-sidebar">
      <div class="sidebar-section">
        <span class="sidebar-label">Sports</span>
        <div class="sport-filter-list" aria-label="Filter sports board">
          <button type="button" class="sport-filter active" data-league="all"><span aria-hidden="true">◉</span>All sports<b>{sports_summary["event_count"]}</b></button>
          {league_buttons}
        </div>
      </div>
      <div class="sidebar-section">
        <span class="sidebar-label">Filters</span>
        <label class="sidebar-select"><span>Date</span><select aria-label="Event date"><option>Today</option></select></label>
        <label class="sidebar-select"><span>League</span><select aria-label="League"><option>All leagues</option></select></label>
        <label class="sidebar-select"><span>Market</span><select aria-label="Market type"><option>All markets</option></select></label>
      </div>
      <div class="sidebar-section">
        <span class="sidebar-label">Research</span>
        <nav class="side-navigation" aria-label="Research views">
          <a href="#market-browser"><span aria-hidden="true">◇</span>Exact combos <b>{verified_contracts}</b></a>
          <a href="#quality"><span aria-hidden="true">◉</span>Source health</a>
          <a href="#record"><span aria-hidden="true">↗</span>Track record</a>
        </nav>
      </div>
      <div class="sidebar-live-card" data-state="{data_state}">
        <div class="live-badge {data_state}" role="status"><i aria-hidden="true"></i><span>{data_label}</span></div>
        <strong>{html.escape(display_generated_at)}</strong>
        <small>{len(games)} games · {len(markets)} contracts</small>
        {data_message_html}
      </div>
      <div class="sidebar-disclaimer">
        <strong>Decision support only</strong>
        <p>No account connection, order upload, automatic trade, or guaranteed outcome.</p>
      </div>
    </aside>

    <main class="workspace">
      <section class="workspace-hero" id="builder">
        <div>
          <p class="eyebrow">Live Kalshi prediction builder · research only</p>
          <h1>Build your prediction research.</h1>
          <p class="hero-tagline">Fresh market data, manual review packets, no account automation. Compare live sports prices and inspect exact Kalshi combinations.</p>
        </div>
        <div class="workspace-meta">
          <span><small>Updated</small><strong>{html.escape(display_generated_at)}</strong></span>
          <span><small>Refresh cadence</small><strong>{html.escape(refresh_label)}</strong></span>
        </div>
        <div class="source-alert {data_state}" role="status">
          <span class="source-alert-icon" aria-hidden="true">{('✓' if data_is_ready else '!')}</span>
          <div><strong>{data_label}</strong><p>{html.escape(data_message if not data_is_ready else snapshot_source + ' passed the freshness gate.')}</p></div>
        </div>
        {refresh_error_html}
        <div class="builder-stat-grid" aria-label="Current builder summary">
          <span><small>Live games</small><strong>{sports_summary["event_count"]}</strong></span>
          <span><small>Markets scanned</small><strong>{len(markets)}</strong></span>
          <span><small>Exact combos today</small><strong>{verified_contracts}</strong></span>
          <span><small>Public combo quotes</small><strong>{tradable_contracts}</strong></span>
        </div>
        <div class="builder-toolbar" role="search">
          <label class="builder-search"><span aria-hidden="true">⌕</span><input id="market-search" type="search" placeholder="Search teams, events, or markets…" aria-label="Search live markets"></label>
          <div class="date-tabs" aria-label="Date selection"><button type="button" class="active">Today</button><button type="button">Upcoming</button><button type="button">Popular</button></div>
          <span class="toolbar-live"><i aria-hidden="true"></i>Live source data</span>
        </div>
      </section>

      <section class="panel builder-board-panel" id="sports-board">
        <div class="section-head">
          <div><span class="section-label">{sports_state_label}</span><h2>Sports market board</h2></div>
          <p>{sports_summary_text}</p>
        </div>
        {render_sports_section(sports_board)}
      </section>

      <section class="panel" id="market-browser">
        <div class="section-head">
          <div><span class="section-label">Source-backed</span><h2>Live Kalshi contract browser · exact combination watchlist</h2></div>
          <p>{len(markets)} exact contracts · {rfq_contracts} awaiting RFQ · {tradable_contracts} publicly quoted.</p>
        </div>
        {render_market_browser(payload)}
      </section>

      <section class="panel" id="map">
        <div class="section-head">
          <div><span class="section-label">Builder status</span><h2>Today's review tiers</h2></div>
          <p>Only exact listed contracts with fresh source evidence appear.</p>
        </div>
        {render_visual_section(payload)}
      </section>

      <section class="panel" id="quality">
        <div class="section-head">
          <div><span class="section-label">Freshness gate</span><h2>Live Status</h2></div>
          <p>Stale or failed sources automatically hide review slips.</p>
        </div>
        {render_quality_panel(quality_status, public_data_gate)}
      </section>

      <section class="panel" id="record">
        <div class="section-head">
          <div><span class="section-label">Research only</span><h2>Track Record</h2></div>
          <p>Settled, resolved, and de-duplicated exposures only.</p>
        </div>
        {render_research_record_panel(research_record)}
      </section>

      <section class="panel slip-detail-panel" id="primary">
        <div class="section-head"><div><span class="section-label">Primary review</span><h2>80c+ Market Tier</h2></div><p>Higher-price exact combo legs</p></div>
        {render_slip_section(primary_slip, "80c+ MARKET TIER", "primary", payload)}
      </section>

      <section class="panel slip-detail-panel" id="leverage">
        <div class="section-head"><div><span class="section-label">Expanded review</span><h2>75c+ Market Tier</h2></div><p>More variance; same evidence requirements</p></div>
        {render_slip_section(leverage_slip, "75c+ MARKET TIER", "leverage", payload)}
      </section>

      <section class="panel slip-detail-panel" id="all-day">
        <div class="section-head"><div><span class="section-label">All-day review</span><h2>All-Day 75-85c Tier</h2></div><p>Verified compatible contracts only</p></div>
        {render_slip_section(all_day_slip, "ALL-DAY 75-85c TIER", "all_day", payload)}
      </section>

      <section class="panel slip-detail-panel" id="research-edge">
        <div class="section-head"><div><span class="section-label">Experimental</span><h2>Research Scout Slip</h2></div><p>Research estimates remain clearly labeled</p></div>
        {render_slip_section(research_edge_slip, "RESEARCH SCOUT SLIP", "research_edge", payload)}
      </section>
    </main>

    <aside class="prediction-drawer" aria-label="Current prediction slip">
      <div class="drawer-header">
        <div><span class="section-label">Live research</span><h2>Your research watchlist</h2></div>
        <a href="#market-browser" aria-label="Open exact combinations">↗</a>
      </div>
      {render_compact_slip(primary_slip, payload)}
      <div class="drawer-trust-card">
        <span aria-hidden="true">✓</span>
        <div><strong>Source evidence preserved</strong><p>Every displayed leg keeps its ticker, timestamp, quote, and exact combo evidence.</p></div>
      </div>
    </aside>
  </div>

  <nav class="mobile-bottom-nav" aria-label="Mobile navigation">
    <a href="#builder"><span aria-hidden="true">⌁</span>Builder</a>
    <a href="#record"><span aria-hidden="true">↗</span>History</a>
    <a href="#research-edge"><span aria-hidden="true">✦</span>Strategies</a>
    <a href="#quality"><span aria-hidden="true">◉</span>Alerts</a>
    <a href="#market-browser"><span aria-hidden="true">•••</span>More</a>
  </nav>
  <script>window.PAPER_DATA = {payload_json};</script>
  <script>{JS}</script>
</body>
</html>"""


def render_market_card(market: dict) -> str:
    leg_details = market.get("leg_details") or []
    if leg_details:
        legs = "".join(render_leg_detail(leg) for leg in leg_details)
    else:
        legs = "".join(f"<li>{html.escape(leg)}</li>" for leg in market.get("legs_text", []))
    yes_ask = market.get("yes_ask_cents")
    price_class = "warning" if yes_ask in {None, 0, 0.0} else ""
    adjusted = market.get("adjusted_market_implied_probability")
    adjusted_text = "n/a" if adjusted is None else f"{adjusted * 100:.2f}%"
    raw = market.get("raw_market_implied_probability")
    raw_text = "n/a" if raw is None else f"{raw * 100:.2f}%"
    ev = market.get("combo_ev_cents")
    ev_text = "n/a" if ev is None else f"{ev:.2f}c"
    readiness = "complete real legs" if market.get("real_data_ready") else "missing leg data"
    ready_class = "good" if market.get("real_data_ready") else "warning"
    return f"""
    <article class="card">
      <div class="card-head">
        <h3>{html.escape(market.get("ticker", ""))}</h3>
        <span class="pill {ready_class}">{readiness}</span>
      </div>
      <div class="prob-grid">
        <span>Adjusted implied <strong>{adjusted_text}</strong></span>
        <span>Raw implied <strong>{raw_text}</strong></span>
        <span>Penalty <strong>{float(market.get("correlation_penalty") or 0) * 100:.2f}%</strong></span>
        <span>Combo EV <strong>{ev_text}</strong></span>
      </div>
      <ul>{legs}</ul>
      <div class="quote-grid">
        <span>YES ask <strong class="{price_class}">{money(yes_ask)}c</strong></span>
        <span>YES bid <strong>{money(market.get("yes_bid_cents"))}c</strong></span>
        <span>NO ask <strong>{money(market.get("no_ask_cents"))}c</strong></span>
        <span>Volume <strong>{html.escape(str(market.get("volume_24h", "")))}</strong></span>
      </div>
      <button type="button" class="copy" data-title="{html.escape(market.get("title", ""), quote=True)}">Copy legs</button>
      <p class="fine-print">{html.escape(market.get("real_data_warning", ""))}</p>
    </article>
    """


def render_pick_section(pick: dict) -> str:
    action = pick.get("action", "UNKNOWN")
    candidates = pick.get("candidates") or []
    reason = html.escape(pick.get("reason", ""))
    action_class = "good" if action == "BET_CANDIDATE" else "warning"
    if not candidates:
        counts = pick.get("decision_counts") or {}
        return f"""
        <div class="decision {action_class}">
          <strong>{html.escape(action)}</strong>
          <p>{reason}</p>
          <p>Tradable combos scanned: {pick.get("tradable_combo_count", 0)}</p>
          <p>Research candidates: {counts.get("BET_CANDIDATE", 0)} · waiting: {counts.get("WAIT_FOR_DATA", 0)} · no-bet: {counts.get("NO_BET", 0)}</p>
        </div>
        """
    best = candidates[0]
    decision = best.get("decision") or {}
    legs = "".join(render_leg_detail(leg) for leg in best.get("legs", []))
    return f"""
    <div class="decision {action_class}">
      <strong>{html.escape(action)}</strong>
      <p>{reason}</p>
      <div class="prob-grid">
        <span>YES ask <strong>{money(best.get("yes_ask_cents"))}c</strong></span>
        <span>Model probability <strong>{float(best.get("model_probability") or 0) * 100:.2f}%</strong></span>
        <span>Lower-bound net edge <strong>{money(best.get("lower_bound_net_edge_cents"))}c</strong></span>
        <span>Model state <strong>{html.escape(str(decision.get("model_state") or "unknown"))}</strong></span>
        <span>Legs <strong>{best.get("leg_count", 0)}</strong></span>
      </div>
      <h3>{html.escape(best.get("ticker", ""))}</h3>
      <ul>{legs}</ul>
      <button type="button" class="copy" data-title="{html.escape(best.get("title", ""), quote=True)}">Copy research legs</button>
      <p class="fine-print">Research-only candidate. Automatic execution remains disabled.</p>
    </div>
    """


def render_slip_section(
    slip: dict,
    label: str = "COMBO SLIP",
    slip_key: str = "primary",
    source_payload: dict | None = None,
) -> str:
    action = slip.get("action", "UNKNOWN")
    if action == "BUILD_SLIP" and not slip_has_authoritative_combo_evidence(slip):
        slip = {
            "action": "NO_SLIP",
            "reason": "This combination is hidden because an exact active Kalshi KXMVE listing was not verified.",
            "eligible_leg_count": 0,
        }
        action = "NO_SLIP"
    if action != "BUILD_SLIP":
        source_context = combo_source_context(source_payload, slip_key)
        source_context_html = (
            f'<p class="status-note">{html.escape(source_context)}</p>' if source_context else ""
        )
        return f"""
        <div class="slip-card empty">
          <strong>No Slip</strong>
          <p>{html.escape(slip.get("reason", "The engine did not find enough clean legs."))}</p>
          {source_context_html}
          <span>Eligible legs: {slip.get("eligible_leg_count", 0)}</span>
        </div>
        """
    grouped: dict[str, list[dict]] = {}
    for leg in slip.get("legs", []):
        grouped.setdefault(leg.get("sport", "Sports"), []).append(leg)
    sections = []
    for sport, legs in grouped.items():
        leg_items = "".join(render_slip_leg(leg) for leg in legs)
        sections.append(
            f"""
            <section class="league-block">
              <div class="league-title">
                <h3>{html.escape(sport)}</h3>
                <span>{len(legs)} legs</span>
              </div>
              <ul class="slip-list">{leg_items}</ul>
            </section>
            """
        )
    fallback_copy_text = slip_copy_text(slip, label)
    review_text = fallback_copy_text
    ticker_stack = ""
    if slip_key in SLIP_SOURCES:
        source_payload = source_payload or {}
        review_packet = build_review_packet(
            {
                "date": source_payload.get("date"),
                "generated_at": source_payload.get("generated_at"),
                "generated_at_note": source_payload.get("generated_at_note"),
                SLIP_SOURCES[slip_key][0]: slip,
            },
            slip_key,
        )
        review_text = review_packet.get("copy_blocks", {}).get("review_packet") or fallback_copy_text
        ticker_stack = review_packet.get("copy_blocks", {}).get("ticker_stack") or ""
    copy_text = html.escape(fallback_copy_text, quote=True)
    review_copy_text = html.escape(review_text, quote=True)
    ticker_copy_text = html.escape(ticker_stack, quote=True)
    packet_href = f"/review-packet.txt?slip={html.escape(slip_key, quote=True)}"
    packet_json_href = f"/review-packet.json?slip={html.escape(slip_key, quote=True)}"
    compatibility = slip.get("combo_compatibility") or {}
    compatibility_status = compatibility.get("status", "unknown")
    manual_entry_ready = compatibility.get("manual_entry_ready", slip.get("manual_entry_ready"))
    entry_status = "Ready to review" if compatibility_status == "compatible" and manual_entry_ready else "Needs review"
    combo_categories = compatibility.get("categories") or slip.get("combo_categories") or slip.get("sports") or []
    category_text = ", ".join(str(item) for item in combo_categories) or "n/a"
    max_leg_probability = slip.get("max_leg_probability")
    leg_probability_label = "Leg Range" if max_leg_probability is not None else "Leg Floor"
    leg_probability_value = (
        f"{float(slip.get('min_leg_probability') or 0) * 100:.0f}-{float(max_leg_probability) * 100:.0f}%"
        if max_leg_probability is not None
        else f"{float(slip.get('min_leg_probability') or 0) * 100:.0f}%"
    )
    combo_probability_label = "Research Estimate" if slip_key == "research_edge" else "Implied Combo"
    return f"""
    <div class="slip-card">
      <div class="slip-topline">
        <div class="slip-heading">
          <span class="section-kicker">{html.escape(label)}</span>
          <div class="slip-count"><strong>{slip.get("leg_count", 0)}</strong><span>legs</span></div>
          <div class="slip-review-state">
            <span class="pill {'good' if entry_status == 'Ready to review' else 'warning'}">{html.escape(entry_status)}</span>
            <span>{html.escape(category_text)}</span>
          </div>
        </div>
        <div class="packet-actions">
          <button type="button" class="copy primary-copy" data-copy="{review_copy_text}">Copy Slip</button>
          <button type="button" class="copy compact-copy" data-copy="{ticker_copy_text}">Copy Tickers</button>
          <a class="packet-download" href="{packet_href}" download>TXT</a>
          <a class="packet-download" href="{packet_json_href}" download>JSON</a>
        </div>
      </div>
      <p class="packet-note">Manual entry: verify price, side, and event start time before placing anything yourself.</p>
      <div class="metric-strip">
        <span><small>{leg_probability_label}</small><strong>{leg_probability_value}</strong></span>
        <span><small>Price</small><strong>{money(slip.get("estimated_combo_price_cents"))}c</strong></span>
        <span><small>{combo_probability_label}</small><strong>{float(slip.get("adjusted_probability") or 0) * 100:.2f}%</strong></span>
        <span><small>Est. $5 Payout</small><strong>${money(slip.get("estimated_payout_if_right"))}</strong></span>
      </div>
      <div class="slip-groups">{''.join(sections)}</div>
    </div>
    """


def render_slip_leg(leg: dict) -> str:
    label = leg.get("subtitle") or leg.get("title") or leg.get("market_ticker", "")
    event = leg.get("display_event") or leg.get("event_ticker") or ""
    ticker = leg.get("market_ticker") or ""
    status = leg.get("status") or "n/a"
    category = leg.get("combo_category") or leg.get("category") or leg.get("sport") or "n/a"
    start_time = leg.get("event_start_time") or ""
    close_time = leg.get("market_close_time") or leg.get("close_time") or ""
    start_time_text = display_event_time(start_time)
    close_time_text = display_event_time(close_time)
    probability = float(leg.get("probability") or 0) * 100.0
    required = float(leg.get("required_probability") or 0) * 100.0
    side = html.escape(leg.get("side", "").upper())
    ask = money(leg.get("ask_cents"))
    if leg.get("research_probability") is not None:
        probability_kind = "Research estimate"
        margin = float(leg.get("margin_of_error") or 0) * 100.0
        kalshi = float(leg.get("kalshi_probability") or 0) * 100.0
        evidence_count = int(leg.get("evidence_count") or 0)
        detail_rows = [
            ("Kalshi", f"{kalshi:.1f}%"),
            ("Margin", f"+/-{margin:.1f}%"),
            ("Sources", str(evidence_count)),
        ]
    else:
        probability_kind = "Market implied"
        detail_rows = [("Floor", f"{required:.0f}%")]
    detail_rows.extend(
        [
            ("Category", str(category)),
            ("Status", str(status)),
            ("Closes", close_time_text),
        ]
    )
    detail_html = "".join(
        f"<div><dt>{html.escape(name)}</dt><dd>{html.escape(value)}</dd></div>" for name, value in detail_rows
    )
    return (
        f"<li class=\"slip-leg\">"
        f"<div class=\"leg-copy\"><strong>{html.escape(event)}</strong><span>{side} / {html.escape(label)}</span>"
        f"<div class=\"leg-chips\"><time datetime=\"{html.escape(str(start_time), quote=True)}\">{html.escape(start_time_text)}</time>"
        f"<span>{ask}c ask</span></div></div>"
        f"<div class=\"leg-metrics\"><b>{probability:.1f}%</b><small>{probability_kind}</small></div>"
        f"<details class=\"leg-details\"><summary>Market details</summary><code>{html.escape(ticker)}</code><dl>{detail_html}</dl></details>"
        f"</li>"
    )


def render_visual_section(payload: dict) -> str:
    tiers = [
        ("80c+ Market", "primary", payload.get("custom_slip") or {}, "market-implied"),
        ("75c+ Market", "leverage", payload.get("leverage_slip") or {}, "market-implied"),
        ("All-Day 75-85c", "all-day", payload.get("all_day_slip") or {}, "market-implied"),
        ("Research Scout", "research", payload.get("research_edge_slip") or {}, "research estimate"),
    ]
    cards = []
    built_count = 0
    total_legs = 0
    source_ready = (payload.get("public_data_gate") or {}).get("status") == "ready"
    source_context = combo_source_context(payload)
    for name, tier_class, slip, probability_kind in tiers:
        is_built = slip.get("action") == "BUILD_SLIP"
        if is_built:
            built_count += 1
        chance = float(slip.get("adjusted_probability") or 0) * 100.0 if is_built else 0.0
        payout = float(slip.get("estimated_payout_if_right") or 0) if is_built else 0.0
        legs = int(slip.get("leg_count") or 0) if is_built else 0
        total_legs += legs
        headline = str(legs) if is_built else "-"
        subline = (
            f"{chance:.2f}% {probability_kind}"
            if is_built
            else ("No qualifying legs" if source_ready else "Waiting for fresh data")
        )
        payout_text = f"Est. ${money(payout)}" if is_built else "Unavailable"
        status_text = "Ready" if is_built else ("No slip" if source_ready else "Blocked")
        cards.append(
            f"""
            <article class="map-card tier-{tier_class}">
              <div class="map-card-head">
                <span>{html.escape(name)}</span>
                <strong>{status_text}</strong>
              </div>
              <div class="map-count"><strong>{headline}</strong><em>legs</em></div>
              <div class="map-meta">
                <small>{subline}</small>
                <small>{payout_text}</small>
              </div>
            </article>
            """
        )
    generated_at = payload.get("generated_at") or "pending"
    display_generated_at = display_timestamp(generated_at)
    return f"""
    <div class="slip-map">
        <div class="slip-summary" aria-label="Slip summary">
          <span>Ready tiers</span>
          <strong>{built_count}/4</strong>
          <small>{total_legs} total manual-entry legs</small>
          <small>Last build {html.escape(display_generated_at)}</small>
          {f'<small class="status-note">{html.escape(source_context)}</small>' if source_context else ''}
        </div>
      <div class="map-panel">
        <div class="map-cards">{''.join(cards)}</div>
        <div class="update-line">
          <span>Last build</span>
          <strong>{html.escape(display_generated_at)}</strong>
        </div>
      </div>
    </div>
    """


def combo_source_context(source_payload: dict | None, slip_key: str | None = None) -> str:
    summary = (source_payload or {}).get("combo_source_summary") or {}
    active_count = int(summary.get("active_kxmve_market_count") or 0)
    verified_count = int(summary.get("verified_current_day_contract_count") or 0)
    tradable_count = int(summary.get("tradable_kxmve_market_count") or 0)
    rfq_count = int(summary.get("rfq_required_kxmve_market_count") or 0)
    if not active_count:
        return ""
    base = (
        f"Fresh Kalshi source loaded {active_count} active KXMVE contracts; "
        f"{verified_count} have complete exact-contract evidence for today; "
        f"{tradable_count} have a public executable combo quote."
    )
    if rfq_count:
        base += f" {rfq_count} require an authenticated Kalshi RFQ before a combo price exists."
    if not slip_key:
        return base
    tier = (summary.get("tiers") or {}).get(slip_key) or {}
    eligible_count = int(tier.get("eligible_exact_combo_count") or 0)
    watchlist_count = int(tier.get("rfq_watchlist_count") or 0)
    if eligible_count:
        return f"{base} {eligible_count} meet this tier's exact listed-contract criteria."
    if watchlist_count:
        return (
            f"{base} {watchlist_count} exact combinations meet this tier's underlying-leg rules, "
            "but remain watchlist-only until an RFQ supplies an executable combo price."
        )
    return f"{base} None meet this tier's exact listed-contract criteria, so no slip is shown."


def render_quality_panel(status: dict, public_data_gate: dict | None = None) -> str:
    gate = status.get("source_quality_gate") or {}
    public_data_gate = public_data_gate or {}
    slip_counts = gate.get("slip_counts") or status.get("slip_counts") or {}
    data_is_ready = public_data_gate.get("status") == "ready"
    decision_class = "good" if data_is_ready else "warning"
    primary = int(slip_counts.get("primary") or 0)
    leverage = int(slip_counts.get("leverage") or 0)
    all_day = int(slip_counts.get("all_day") or 0)
    research_edge = int(slip_counts.get("research_edge") or 0)
    age = status.get("data_age_seconds")
    if age in {None, ""}:
        age_text = "Fresh"
    else:
        age_seconds = max(0, int(float(age)))
        if age_seconds < 60:
            age_text = f"{age_seconds}s old"
        elif age_seconds < 3600:
            age_text = f"{age_seconds // 60}m old"
        else:
            age_text = f"{age_seconds // 3600}h old"
    public_status = "Fresh data" if data_is_ready else "Review blocked"
    gate_message = str(public_data_gate.get("message") or "Fresh data is required before review.")
    gate_message_html = "" if data_is_ready else f'<p class="status-note">{html.escape(gate_message)}</p>'
    return f"""
    <div class="decision status-decision {decision_class}">
      <div class="status-heading"><strong>{html.escape(public_status)}</strong><span>{html.escape(str(age_text))}</span></div>
      {gate_message_html}
      <div class="metric-strip status-metrics">
        <span><small>80c+</small><strong>{primary}</strong></span>
        <span><small>75c+</small><strong>{leverage}</strong></span>
        <span><small>All-Day</small><strong>{all_day}</strong></span>
        <span><small>Scout</small><strong>{research_edge}</strong></span>
      </div>
    </div>
    """


def render_research_record_panel(record: dict) -> str:
    tracks = record.get("tracks") or []
    track_cards = "".join(render_research_record_track(track) for track in tracks) or """
      <div class="decision warning">
        <strong>No record yet</strong>
        <p>No settled rows are available yet. Keep collecting before showing hit-rate metrics.</p>
      </div>
    """
    status_label = str(record.get("status") or "WATCH")
    decision_class = "good" if status_label == "OK" else "warning"
    return f"""
    <div class="decision record-decision {decision_class}">
      <div class="record-heading"><span class="pill {decision_class}">{html.escape(status_label)}</span><span>Settled + de-duped</span></div>
      <div class="record-grid">{track_cards}</div>
    </div>
    """


def render_research_record_track(track: dict) -> str:
    hit_rate = track.get("observed_hit_rate")
    raw_hit_rate = track.get("observed_hit_rate_raw")
    if hit_rate is not None:
        hit_rate_text = f"{float(hit_rate) * 100:.2f}%"
        hit_rate_status = "Settled sample"
    elif raw_hit_rate is not None:
        hit_rate_text = "Pending"
        hit_rate_status = "More data needed"
    else:
        hit_rate_text = "Unavailable"
        hit_rate_status = "No settled rows"
    return f"""
      <article class="card">
        <div class="card-head">
          <h3>{html.escape(str(track.get("bot_name", "")))}</h3>
          <span class="pill">research</span>
        </div>
        <div class="record-rate"><small>Hit rate</small><strong>{html.escape(hit_rate_text)}</strong><span>{html.escape(hit_rate_status)}</span></div>
        <div class="metric-strip record-metrics">
          <span><small>Valid</small><strong>{int(track.get("valid_rows") or 0)}</strong></span>
          <span><small>Settled</small><strong>{int(track.get("settled_rows") or 0)}</strong></span>
          <span><small>Unique</small><strong>{int(track.get("deduped_settled_exposures") or 0)}</strong></span>
          <span><small>Open</small><strong>{int(track.get("unresolved_rows") or 0)}</strong></span>
        </div>
      </article>
    """


def render_slip_rationale_row(row: dict) -> str:
    combo_probability = row.get("combo_probability")
    combo_text = "n/a" if combo_probability is None else f"{float(combo_probability) * 100:.2f}%"
    min_probability = row.get("min_leg_probability")
    max_probability = row.get("max_leg_probability")
    if min_probability is None:
        floor_text = "dynamic"
    elif max_probability is None:
        floor_text = f"{float(min_probability) * 100:.0f}%+"
    else:
        floor_text = f"{float(min_probability) * 100:.0f}-{float(max_probability) * 100:.0f}%"
    return (
        f"<li><strong>{html.escape(str(row.get('label', 'Slip')))}</strong>: "
        f"{html.escape(str(row.get('action', 'NO_SLIP')))} · "
        f"legs {int(row.get('leg_count') or 0)} · floor {html.escape(floor_text)} · "
        f"combo {html.escape(combo_text)} · skipped overlaps {int(row.get('skipped_overlap_count') or 0)}<br>"
        f"<span class=\"leg-meta\">{html.escape(str(row.get('reason') or 'live filters and overlap control'))}</span></li>"
    )


def render_research_section(research: dict) -> str:
    if not research:
        return """
        <div class="decision warning">
          <strong>RESEARCH PENDING</strong>
          <p>No research summary has been generated yet.</p>
        </div>
        """
    market_scan = research.get("market_scan") or {}
    buckets = market_scan.get("probability_buckets") or {}
    bucket_text = ", ".join(f"{html.escape(str(key))}: {html.escape(str(value))}" for key, value in buckets.items()) or "n/a"
    tiers = "".join(
        f"""
        <li><strong>{html.escape(str(tier.get("name", "")))}</strong><br>
        Action {html.escape(str(tier.get("action", "")))};
        legs {html.escape(str(tier.get("leg_count", 0)))};
        full chance {float(tier.get("full_slip_probability") or 0) * 100:.2f}%;
        payout ${money(tier.get("estimated_payout_if_right"))};
        overlap safe {'yes' if tier.get("overlap_safe") else 'no'} ({tier.get("skipped_overlap_count", 0)} skipped)</li>
        """
        for tier in research.get("slip_tiers") or []
    )
    queue = "".join(
        f"""
        <li><strong>{html.escape(item.get("priority", ""))}: {html.escape(item.get("topic", ""))}</strong><br>
        {html.escape(item.get("why", ""))}
        <span class="leg-meta">{html.escape(item.get("next_step", ""))}</span></li>
        """
        for item in research.get("research_queue") or []
    )
    rules = "".join(f"<li>{html.escape(rule)}</li>" for rule in research.get("accuracy_rules") or [])
    return f"""
    <div class="decision good">
      <strong>{html.escape(research.get("status", "ACTIVE"))}</strong>
      <p>{html.escape(research.get("mission", ""))}</p>
      <div class="prob-grid">
        <span>Last research <strong>{html.escape(str(research.get("last_researched_at", "n/a")))}</strong></span>
        <span>Combo markets <strong>{market_scan.get("combo_markets", 0)}</strong></span>
        <span>Priced legs <strong>{market_scan.get("priced_legs", 0)}</strong></span>
        <span>Tight spreads <strong>{market_scan.get("tight_spread_legs", 0)}</strong></span>
      </div>
      <p class="fine-print">Probability buckets: {bucket_text}</p>
      <h3>Slip Tiers</h3>
      <ul>{tiers}</ul>
      <h3>Research Queue</h3>
      <ul>{queue}</ul>
      <h3>Accuracy Rules</h3>
      <ul>{rules}</ul>
    </div>
    """


def render_public_intel_section(intel: dict) -> str:
    if not intel:
        return """
        <div class="decision warning">
          <strong>INTEL PENDING</strong>
          <p>No public intel summary has been generated yet.</p>
        </div>
        """
    connector_items = "".join(
        f"""
        <li><strong>{html.escape(connector.get("name", ""))}</strong><br>
        {html.escape(connector.get("purpose", ""))}
        <span class="leg-meta">status: {html.escape(connector.get("status", ""))}</span></li>
        """
        for connector in intel.get("connector_plan") or []
    )
    source_items = "".join(
        f"""
        <li><strong>{html.escape(source.get("source", ""))}</strong> on {html.escape(source.get("platform", ""))}<br>
        avg score {money(source.get("average_score"))} &middot; signals {source.get("signal_count", 0)}</li>
        """
        for source in intel.get("top_sources") or []
    ) or "<li>No scored public sources loaded yet.</li>"
    match_items = "".join(
        f"""
        <li><strong>{html.escape(match.get("event", ""))}</strong><br>
        {html.escape(match.get("leg", ""))}
        <span class="leg-meta">{html.escape(match.get("source", ""))} &middot; intel +{money(match.get("intel_score"))} &middot; {html.escape(match.get("url", ""))}</span></li>
        """
        for match in intel.get("top_matches") or []
    ) or "<li>No public signals matched today's legs yet.</li>"
    blocked_items = "".join(
        f"""
        <li><strong>{html.escape(item.get("source", ""))}</strong> on {html.escape(item.get("platform", ""))}<br>
        {html.escape(item.get("reason", ""))}</li>
        """
        for item in intel.get("blocked_reasons") or []
    ) or "<li>No blocked signals.</li>"
    weights = intel.get("signal_weights") or {}
    weight_text = ", ".join(f"{html.escape(str(key))}: {html.escape(str(value))}" for key, value in weights.items())
    impact = intel.get("slip_impact") or {}
    return f"""
    <div class="decision good">
      <strong>{html.escape(intel.get("status", "READY"))}</strong>
      <p>{html.escape(intel.get("strategy", ""))}</p>
      <div class="prob-grid">
        <span>Signals loaded <strong>{intel.get("signals_loaded", 0)}</strong></span>
        <span>Trusted signals <strong>{intel.get("trusted_signal_count", 0)}</strong></span>
        <span>Blocked signals <strong>{intel.get("blocked_signal_count", 0)}</strong></span>
        <span>80% boosted legs <strong>{impact.get("primary_intel_boosted_legs", 0)}</strong></span>
      </div>
      <p class="fine-print">Weights: {weight_text}</p>
      <h3>Connector Strategy</h3>
      <ul>{connector_items}</ul>
      <h3>Top Public Sources</h3>
      <ul>{source_items}</ul>
      <h3>Matched Signals</h3>
      <ul>{match_items}</ul>
      <h3>Compliance Blocks</h3>
      <ul>{blocked_items}</ul>
    </div>
    """


def render_failure_guardrails(summary: dict) -> str:
    if not summary:
        return """
        <div class="decision warning">
          <strong>NO GUARDRAIL SUMMARY</strong>
          <p>No postmortem guardrails have been generated yet.</p>
        </div>
        """
    blocks = "".join(
        f"""
        <li><strong>{html.escape(block.get("flag", ""))}</strong><br>
        {html.escape(block.get("rule", ""))}</li>
        """
        for block in summary.get("active_blocks") or []
    )
    not_fixed = "".join(f"<li>{html.escape(item)}</li>" for item in summary.get("not_fixed_by") or [])
    return f"""
    <div class="decision good">
      <strong>{html.escape(summary.get("status", "ACTIVE"))}</strong>
      <p>{html.escape(summary.get("latest_lesson", ""))}</p>
      <h3>Active Blocks</h3>
      <ul>{blocks}</ul>
      <h3>Not Fixed By</h3>
      <ul>{not_fixed}</ul>
    </div>
    """


def render_leg_detail(leg: dict) -> str:
    probability = leg.get("market_implied_probability")
    probability_text = "n/a" if probability is None else f"{probability * 100:.2f}%"
    ask = money(leg.get("ask_cents"))
    bid = money(leg.get("bid_cents"))
    subtitle = leg.get("subtitle") or leg.get("title") or leg.get("market_ticker", "")
    return (
        f"<li><strong>{html.escape(leg.get('side', '').upper())}</strong> "
        f"{html.escape(subtitle)} "
        f"<span class=\"leg-meta\">implied {probability_text}, bid {bid}c, ask {ask}c</span></li>"
    )


class PaperHandler(BaseHTTPRequestHandler):
    server_version = "HawkNeticResearch"
    sys_version = ""
    data_path = repo_path("data", "today_paper_view.json")
    audit_path = repo_path("data", "refresh_audit.jsonl")
    error_path = repo_path("data", "error_events.jsonl")
    refresh_seconds = 0
    refresh_config: dict = {}
    refresh_lock = threading.Lock()
    last_manual_refresh_at = 0.0
    refresh_status = {
        "state": "idle",
        "message": "Ready. Pulls fresh market data and rebuilds the slips.",
    }

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path == "/login":
            if not user_auth_enabled():
                self.send_error(404)
                return
            body = render_login_page().encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/healthz":
            self.send_json({"status": "ok", "service": "kalshi-research-dashboard"})
            return
        if path == "/readyz":
            readiness = build_service_readiness(load_current_payload(self.data_path))
            self.send_json(readiness, status_code=200 if readiness["status"] == "ready" else 503)
            return
        if path == "/internal/status.json":
            if not self.authorize_request(required_role="admin"):
                return
            self.send_json(build_internal_status())
            return
        if not self.authorize_request(required_role="read_only"):
            return
        if path == "/auth/me":
            self.send_json(
                {
                    "username": self.principal.username,
                    "role": self.principal.role,
                    "auth_method": self.principal.auth_method,
                    "session_expires_at": self.principal.session_expires_at,
                }
            )
            return
        if path == "/ops":
            if not self.require_role("admin"):
                return
            self.send_html(render_operator_page())
            return
        if path == "/internal/operator-messages.json":
            if not self.require_role("admin"):
                return
            inbox = self.operator_inbox
            if inbox is None:
                self.send_json({"error": "operator_inbox_unavailable"}, status_code=503)
                return
            self.send_json({"counts": inbox.counts(), "messages": inbox.list(limit=200)})
            return
        payload = load_current_payload(self.data_path)
        safe_payload = safe_dashboard_payload(payload)
        if path in {"/", "/index.html"}:
            body = render_dashboard(safe_payload, self.refresh_seconds).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/data.json":
            self.send_json(consumer_payload(safe_payload))
            return
        if path == "/api/v1":
            self.send_json(build_data_catalog_payload(safe_payload))
            return
        if path in {"/games.json", "/api/v1/games"}:
            self.send_json(build_detail_collection_payload(safe_payload, "games", query))
            return
        if path in {"/markets.json", "/api/v1/markets"}:
            self.send_json(build_detail_collection_payload(safe_payload, "markets", query))
            return
        if path == "/sports.json":
            board = safe_sports_board()
            self.send_json(
                board if (query.get("detail") or ["full"])[0] == "full" else summarize_sports_board(board)
            )
            return
        if path == "/sports-clv.json":
            self.send_json(safe_sports_clv_report())
            return
        if path == "/review-packets.json":
            if not self.require_role("researcher"):
                return
            self.send_json(build_all_review_packets(safe_payload))
            return
        if path == "/review-packet.json":
            if not self.require_role("researcher"):
                return
            slip_key = (query.get("slip") or ["primary"])[0]
            try:
                packet = build_review_packet(safe_payload, slip_key)
            except ValueError as exc:
                self.send_json({"error": str(exc), "valid_slips": sorted(SLIP_SOURCES)}, status_code=400)
                return
            self.send_json(packet)
            return
        if path == "/review-packet.txt":
            if not self.require_role("researcher"):
                return
            slip_key = (query.get("slip") or ["primary"])[0]
            try:
                packet = build_review_packet(safe_payload, slip_key)
            except ValueError as exc:
                self.send_json({"error": str(exc), "valid_slips": sorted(SLIP_SOURCES)}, status_code=400)
                return
            self.send_text(
                render_review_packet_text(packet),
                filename=safe_review_packet_filename(packet, "txt"),
            )
            return
        if path == "/refresh-status":
            self.send_json(dict(self.refresh_status))
            return
        if path == "/quality.json":
            if not self.require_role("admin"):
                return
            self.send_json(build_quality_status(payload, self.audit_path, self.error_path))
            return
        if path == "/research-record.json":
            if not self.require_role("admin"):
                return
            self.send_json(build_research_record(payload=payload))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/auth/login":
            self.handle_login()
            return
        if not self.authorize_request(required_role="read_only"):
            return
        if path == "/auth/logout":
            self.handle_logout()
            return
        if path == "/internal/operator-messages":
            if not self.require_role("admin"):
                return
            if not self.valid_session_csrf():
                self.send_json({"error": "csrf_validation_failed"}, status_code=403)
                return
            self.handle_operator_message()
            return
        if path == "/refresh":
            if not self.require_role("admin"):
                return
            if not valid_refresh_action(self.headers):
                self.send_json(
                    {"state": "rejected", "message": "Refresh request was rejected."},
                    status_code=403,
                )
                return
            if not self.valid_session_csrf():
                self.send_json(
                    {"state": "rejected", "message": "Session CSRF validation failed."},
                    status_code=403,
                )
                return
            status = self.run_refresh(reason="manual", async_run=True)
            status_code = 202 if status.get("accepted") else int(status.get("status_code", 409))
            self.send_json(status, status_code=status_code)
            return
        self.send_error(404)

    @property
    def auth_store(self) -> LocalAuthStore | None:
        if not user_auth_enabled():
            return None
        try:
            return LocalAuthStore()
        except Exception:
            return None

    @property
    def operator_inbox(self) -> OperatorInbox | None:
        try:
            return OperatorInbox()
        except Exception:
            return None

    def authorize_request(self, *, required_role: str = "read_only") -> bool:
        principal = authenticate_dashboard_request(
            self.headers.get("Authorization"),
            self.headers.get("Cookie"),
            auth_store=self.auth_store,
        )
        if principal is not None and role_allows(principal.role, required_role):
            self.principal = principal
            return True
        if principal is not None:
            self.send_json({"error": "role_forbidden"}, status_code=403)
            return False
        configuration_missing = dashboard_auth_enabled() and not dashboard_auth_configured()
        accepts_html = "text/html" in str(self.headers.get("Accept") or "")
        if user_auth_enabled() and accepts_html and not configuration_missing:
            self.send_response(302)
            self.send_header("Location", "/login")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return False
        body = b"Dashboard authentication is not configured." if configuration_missing else b"Authentication required."
        self.send_response(503 if configuration_missing else 401)
        self.send_header("WWW-Authenticate", 'Basic realm="HawkNetic Research Dashboard"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def require_role(self, required_role: str) -> bool:
        principal = getattr(self, "principal", None)
        if principal is not None and role_allows(principal.role, required_role):
            return True
        self.send_json({"error": "role_forbidden", "required_role": required_role}, status_code=403)
        return False

    def valid_session_csrf(self) -> bool:
        principal = getattr(self, "principal", None)
        if principal is None or principal.auth_method != "session":
            return True
        store = self.auth_store
        token = session_token_from_cookie(self.headers.get("Cookie"))
        return bool(store and store.validate_csrf(token or "", self.headers.get("X-CSRF-Token")))

    def handle_login(self) -> None:
        store = self.auth_store
        if store is None:
            self.send_json({"error": "user_auth_unconfigured"}, status_code=503)
            return
        try:
            content_length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 4096:
            self.send_json({"error": "invalid_login_payload"}, status_code=400)
            return
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self.send_json({"error": "invalid_login_payload"}, status_code=400)
            return
        principal = store.authenticate_password(
            str(payload.get("username") or ""),
            str(payload.get("password") or ""),
            remote_address=self.client_address[0] if self.client_address else None,
            user_agent=self.headers.get("User-Agent"),
            maximum_failures=max(1, _env_int("AUTH_MAX_FAILED_LOGINS", 5)),
            lock_minutes=max(1, _env_int("AUTH_LOCK_MINUTES", 15)),
        )
        if principal is None:
            self.send_json({"error": "invalid_credentials"}, status_code=401)
            return
        session_token, session_principal = store.create_session(
            principal,
            duration_minutes=max(5, _env_int("AUTH_SESSION_MINUTES", 480)),
        )
        self.send_json(
            {
                "username": session_principal.username,
                "role": session_principal.role,
                "csrf_token": session_principal.csrf_token,
                "session_expires_at": session_principal.session_expires_at,
            },
            extra_headers={"Set-Cookie": build_session_cookie(session_token, secure=hosted_runtime())},
        )

    def handle_logout(self) -> None:
        if not self.valid_session_csrf():
            self.send_json({"error": "csrf_validation_failed"}, status_code=403)
            return
        token = session_token_from_cookie(self.headers.get("Cookie"))
        store = self.auth_store
        if token and store:
            store.revoke_session(token)
        self.send_json(
            {"status": "logged_out"},
            extra_headers={"Set-Cookie": clear_session_cookie(secure=hosted_runtime())},
        )

    def handle_operator_message(self) -> None:
        inbox = self.operator_inbox
        if inbox is None:
            self.send_json({"error": "operator_inbox_unavailable"}, status_code=503)
            return
        try:
            content_length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            content_length = 0
        if content_length <= 0 or content_length > 110_000:
            self.send_json({"error": "invalid_operator_message_payload"}, status_code=400)
            return
        try:
            payload = json.loads(self.rfile.read(content_length).decode("utf-8"))
            message = inbox.add(
                title=str(payload.get("title") or ""),
                body=str(payload.get("body") or ""),
                created_by=self.principal.username,
                priority=str(payload.get("priority") or "normal"),
                target=str(payload.get("target") or "codex"),
                source="dashboard",
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self.send_json({"error": str(exc)}, status_code=400)
            return
        self.send_json(
            {
                "message": message,
                "execution_allowed": False,
                "next_action": "manual_agent_review",
            },
            status_code=201,
        )

    def end_headers(self) -> None:
        for name, value in dashboard_security_headers().items():
            self.send_header(name, value)
        super().end_headers()

    def send_json(
        self,
        payload: dict,
        status_code: int = 200,
        extra_headers: Mapping[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, indent=2, default=json_default).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, payload: str, status_code: int = 200, filename: str | None = None) -> None:
        body = payload.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def send_html(self, payload: str, status_code: int = 200) -> None:
        body = payload.encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @classmethod
    def run_refresh(cls, reason: str, async_run: bool) -> dict:
        if not cls.refresh_config:
            status = {
                "state": "error",
                "accepted": False,
                "message": "Refresh config is not ready.",
            }
            cls.refresh_status = status
            return dict(status)
        now = time.time()
        if reason == "manual" and now - cls.last_manual_refresh_at < REFRESH_COOLDOWN_SECONDS:
            wait_seconds = int(REFRESH_COOLDOWN_SECONDS - (now - cls.last_manual_refresh_at))
            return {
                "state": "rate_limited",
                "accepted": False,
                "status_code": 429,
                "message": f"Refresh cooldown active. Try again in {wait_seconds}s.",
                "wait_seconds": wait_seconds,
            }
        if not cls.refresh_lock.acquire(blocking=False):
            status = dict(cls.refresh_status)
            status["accepted"] = False
            status["status_code"] = 409
            status["message"] = "A refresh is already running. Wait for it to finish."
            return status

        started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        if reason == "manual":
            cls.last_manual_refresh_at = now
        cls.refresh_status = {
            "state": "running",
            "accepted": True,
            "reason": reason,
            "started_at": started_at,
            "message": "Refreshing odds, schedules, public inputs, and slip math.",
        }

        def job() -> None:
            try:
                cleanup_result = cleanup_runtime_storage()
                result = refresh_payload(**cls.refresh_config)
                result["runtime_cleanup"] = cleanup_result
                internal_error = str(result.pop("_internal_error", ""))
                finished_at = datetime.now().astimezone().isoformat(timespec="seconds")
                state = "complete" if result.get("ok") else "error"
                cls.refresh_status = {
                    **result,
                    "state": state,
                    "accepted": True,
                    "reason": reason,
                    "started_at": started_at,
                    "finished_at": finished_at,
                }
                audit_event = {
                    "event": "refresh",
                    "ok": bool(result.get("ok")),
                    "reason": reason,
                    "started_at": started_at,
                    "finished_at": finished_at,
                    "date": result.get("date"),
                    "primary_leg_count": result.get("primary_leg_count", 0),
                    "leverage_leg_count": result.get("leverage_leg_count", 0),
                    "all_day_leg_count": result.get("all_day_leg_count", 0),
                    "research_edge_leg_count": result.get("research_edge_leg_count", 0),
                    "ledger_logged_predictions": result.get("ledger_logged_predictions", 0),
                    "ledger_rejected_predictions": result.get("ledger_rejected_predictions", 0),
                    "ledger_duplicate_rows_ignored": result.get("ledger_duplicate_rows_ignored", 0),
                    "ledger_error": result.get("ledger_error", ""),
                    "runtime_cleanup": cleanup_result,
                    "error": internal_error or result.get("error", ""),
                }
                append_jsonl(cls.audit_path, audit_event)
                if not result.get("ok"):
                    append_jsonl(cls.error_path, audit_event)
            finally:
                cls.refresh_lock.release()

        if async_run:
            thread = threading.Thread(target=job, name=f"paper-refresh-{reason}", daemon=True)
            thread.start()
            return dict(cls.refresh_status)

        job()
        return dict(cls.refresh_status)

    def log_message(self, format: str, *args: object) -> None:
        return


def refresh_payload(
    data_path: Path,
    yyyymmdd: str | None,
    target_probability: float,
    min_leg_probability: float | None,
    max_leg_probability: float,
    min_legs: int,
    max_legs: int,
    stake_dollars: float,
    leverage_min_leg_probability: float,
    public_intel_path: str | Path | None,
) -> dict:
    from .kalshi_ingestion import persist_kalshi_snapshot
    from .today import write_today_payload

    try:
        payload = write_today_payload(
            data_path,
            yyyymmdd,
            slip_target_probability=target_probability,
            slip_min_leg_probability=min_leg_probability,
            slip_max_leg_probability=max_leg_probability,
            slip_min_legs=min_legs,
            slip_max_legs=max_legs,
            slip_stake_dollars=stake_dollars,
            leverage_min_leg_probability=leverage_min_leg_probability,
            public_intel_path=public_intel_path,
        )
        slip = payload.get("custom_slip", {})
        leverage_slip = payload.get("leverage_slip", {})
        all_day_slip = payload.get("all_day_slip", {})
        research_edge_slip = payload.get("research_edge_slip", {})
        print(
            f"Refreshed {data_path} at {payload.get('generated_at')} "
            f"with {slip.get('leg_count', 0)} slip legs."
        )
        try:
            source_persistence = persist_kalshi_snapshot(
                payload,
                worker_name="paper-dashboard-refresh",
            )
        except Exception as exc:
            error = f"{type(exc).__name__}: {exc}"
            print(f"Source snapshot persistence failed: {error}")
            return {
                "ok": False,
                "message": "Fresh Kalshi data was collected but could not be committed to PostgreSQL.",
                "error": "postgres_snapshot_persistence_failed",
                "_internal_error": error,
                "generated_at": payload.get("generated_at"),
            }
        try:
            ledger = log_refresh_predictions(payload)
        except Exception as exc:
            ledger = {
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }
            print(f"Refresh ledger logging failed: {ledger['error']}")
        return {
            "ok": True,
            "message": "Slip refreshed from live data. Reloading dashboard.",
            "generated_at": payload.get("generated_at"),
            "date": payload.get("date"),
            "games": len(payload.get("games", [])),
            "markets": len(payload.get("markets", [])),
            "all_day_market_count": payload.get("all_day_market_count", 0),
            "primary_leg_count": slip.get("leg_count", 0),
            "leverage_leg_count": leverage_slip.get("leg_count", 0),
            "all_day_leg_count": all_day_slip.get("leg_count", 0),
            "research_edge_leg_count": research_edge_slip.get("leg_count", 0),
            "source_persistence_ok": source_persistence.get("ok", True),
            "source_persistence_batch_id": source_persistence.get("batch_id"),
            "source_records_received": source_persistence.get("records_received", 0),
            "source_records_accepted": source_persistence.get("records_accepted", 0),
            "source_records_rejected": source_persistence.get("records_rejected", 0),
            "source_records_duplicated": source_persistence.get("records_duplicated", 0),
            "source_persistence_error": source_persistence.get("error", ""),
            "ledger_ok": bool(ledger.get("ok")),
            "ledger_run_id": ledger.get("run_id"),
            "ledger_run_created": ledger.get("run_created", False),
            "ledger_attempted_predictions": ledger.get("attempted_predictions", 0),
            "ledger_logged_predictions": ledger.get("logged_predictions", 0),
            "ledger_rejected_predictions": ledger.get("rejected_predictions", 0),
            "ledger_duplicate_rows_ignored": ledger.get("duplicate_rows_ignored", 0),
            "ledger_rejection_reasons": ledger.get("rejection_reasons", []),
            "ledger_error": ledger.get("error", ""),
        }
    except Exception as exc:
        payload = load_payload(data_path)
        error = f"{type(exc).__name__}: {exc}"
        payload["refresh_error"] = "live_refresh_failed"
        payload["refresh_failed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        write_json_atomic(data_path, payload)
        print(f"Refresh failed: {error}")
        return {
            "ok": False,
            "message": "Live refresh failed. Slips are hidden until fresh data returns.",
            "error": "live_refresh_failed",
            "_internal_error": error,
            "failed_at": payload["refresh_failed_at"],
        }


def start_refresh_thread(refresh_seconds: int) -> None:
    def loop() -> None:
        while True:
            time.sleep(refresh_seconds)
            PaperHandler.run_refresh(reason="auto", async_run=False)

    thread = threading.Thread(target=loop, name="paper-refresh", daemon=True)
    thread.start()


def run_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    data_path: str | Path | None = None,
    refresh_seconds: int = 600,
    yyyymmdd: str | None = None,
    target_probability: float = 0.80,
    min_leg_probability: float | None = None,
    max_leg_probability: float = 0.985,
    min_legs: int = 8,
    max_legs: int = 20,
    stake_dollars: float = 5.0,
    leverage_min_leg_probability: float = 0.75,
    public_intel_path: str | Path | None = None,
) -> None:
    resolved_data_path = Path(data_path) if data_path else repo_path("data", "today_paper_view.json")
    PaperHandler.data_path = resolved_data_path
    PaperHandler.refresh_seconds = max(0, int(refresh_seconds or 0))
    PaperHandler.refresh_config = {
        "data_path": resolved_data_path,
        "yyyymmdd": yyyymmdd,
        "target_probability": target_probability,
        "min_leg_probability": min_leg_probability,
        "max_leg_probability": max_leg_probability,
        "min_legs": min_legs,
        "max_legs": max_legs,
        "stake_dollars": stake_dollars,
        "leverage_min_leg_probability": leverage_min_leg_probability,
        "public_intel_path": public_intel_path,
    }
    server = ThreadingHTTPServer((host, port), PaperHandler)
    if hosted_runtime() and not os.environ.get("DASHBOARD_AUTH_PASSWORD"):
        print("Dashboard locked: set DASHBOARD_AUTH_PASSWORD in the hosted environment.")
    if PaperHandler.refresh_seconds:
        PaperHandler.run_refresh(reason="startup", async_run=True)
        start_refresh_thread(PaperHandler.refresh_seconds)
    print(f"Paper view running at http://{host}:{port}")
    print("Health endpoints: /healthz and /readyz")
    if PaperHandler.refresh_seconds:
        print(f"Auto-refreshing every {PaperHandler.refresh_seconds} seconds.")
    server.serve_forever()


CSS = r"""
/* Production product UI: restrained, operational, and domain-specific. */
:root {
  --background: #0b0f12;
  --surface: #11171b;
  --surface-raised: #151d21;
  --surface-muted: #0f1518;
  --border: #2a363b;
  --border-strong: #405057;
  --text-primary: #edf4f1;
  --text-secondary: #b8c6c1;
  --text-muted: #879893;
  --accent: #29b779;
  --accent-hover: #34c889;
  --success: #29b779;
  --warning: #d99a2b;
  --danger: #e05d50;
  --info: #5d9bc7;
  --focus: #75b9e6;
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;
  --space-1: 4px;
  --space-2: 8px;
  --space-3: 12px;
  --space-4: 16px;
  --space-5: 20px;
  --space-6: 24px;
}
*,
*::before,
*::after {
  box-sizing: border-box;
}
html { scroll-padding-top: 72px; }
h1,
h2,
h3,
p {
  margin: 0;
}
a {
  color: inherit;
}
body {
  background: var(--background) !important;
  color: var(--text-primary);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.45;
}
body::before,
.hero::after,
.panel::after,
.panel::before {
  display: none !important;
}
.skip-link {
  position: fixed;
  left: 12px;
  top: 8px;
  z-index: 100;
  transform: translateY(-140%);
  border: 1px solid var(--focus);
  border-radius: var(--radius-md);
  padding: 8px 10px;
  background: var(--surface-raised);
  color: var(--text-primary);
}
.skip-link:focus { transform: translateY(0); }
.hero,
.quick-nav,
main {
  width: min(1360px, calc(100% - 32px)) !important;
}
.hero {
  grid-template-columns: minmax(0, 1fr) 292px !important;
  gap: var(--space-5);
  margin-top: var(--space-4);
  padding: var(--space-5) var(--space-6);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg) !important;
  background: var(--surface) !important;
  box-shadow: none !important;
}
.eyebrow {
  margin-bottom: var(--space-2);
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.eyebrow::before { display: none; }
h1 {
  margin: 0;
  color: var(--text-primary);
  font-size: clamp(30px, 4vw, 44px);
  line-height: 1.04;
  letter-spacing: 0;
}
h2 {
  color: var(--text-primary);
  font-size: 18px;
  line-height: 1.25;
  letter-spacing: 0;
}
h3 {
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.3;
  letter-spacing: 0;
}
.hero-tagline {
  max-width: 680px;
  margin-top: var(--space-2);
  color: var(--text-secondary);
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0;
}
.hero-meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  margin-top: var(--space-4);
}
.hero-meta > span,
.metric-strip span,
.update-line,
.quote-grid span,
.prob-grid span {
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-muted);
}
.hero-meta > span {
  padding: 7px 9px;
}
.hero-meta small,
.metric-strip small,
.record-rate small,
.packet-note,
.section-kicker,
.league-title span,
.leg-details dt {
  color: var(--text-muted);
  font-size: 10px;
  font-weight: 800;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.hero-meta strong,
.metric-strip strong,
.update-line strong {
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}
.refresh-box {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: var(--space-2);
  align-items: center;
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg) !important;
  background: var(--surface-muted) !important;
  box-shadow: none !important;
}
.live-badge {
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 700;
}
.live-badge i {
  background: var(--success);
  box-shadow: none;
}
.live-badge.blocked {
  color: var(--warning);
}
.live-badge.blocked i {
  background: var(--warning);
}
#refresh-slip {
  min-height: 44px;
  min-width: 104px;
}
#refresh-status {
  grid-column: 1 / -1;
  color: var(--text-muted);
  text-align: left;
}
#refresh-status.good { color: var(--success); }
#refresh-status.warning { color: var(--warning); }
#refresh-status.bad { color: var(--danger); }
.data-state-message {
  grid-column: 1 / -1;
  color: var(--text-secondary);
  font-size: 12px;
}
button,
.packet-download {
  min-height: 44px;
  border-radius: var(--radius-md) !important;
  font: inherit;
  font-weight: 750;
}
button:not(.ghost):not(.compact-copy),
.primary-copy {
  border: 1px solid var(--accent);
  background: var(--accent) !important;
  color: #06100c !important;
  box-shadow: none !important;
}
button:hover,
.packet-download:hover,
.quick-nav a:hover {
  transform: none !important;
}
button:not(.ghost):not(.compact-copy):hover,
.primary-copy:hover {
  background: var(--accent-hover) !important;
}
button.copy,
.compact-copy,
.packet-download {
  border: 1px solid var(--border);
  background: var(--surface-muted) !important;
  color: var(--text-primary) !important;
}
button:focus-visible,
a:focus-visible,
summary:focus-visible,
input:focus-visible,
select:focus-visible,
textarea:focus-visible {
  outline: 2px solid var(--focus);
  outline-offset: 2px;
}
.quick-nav {
  position: sticky;
  top: 0;
  z-index: 10;
  display: flex !important;
  width: min(1360px, calc(100% - 32px)) !important;
  gap: 0;
  margin-top: var(--space-3);
  padding: 0;
  overflow-x: auto !important;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg) !important;
  background: #0d1316 !important;
  box-shadow: none !important;
}
.quick-nav a {
  display: grid;
  align-items: center;
  flex: 0 0 auto;
  min-height: 44px;
  min-width: 92px;
  border-right: 1px solid var(--border);
  border-radius: 0 !important;
  padding: 10px 12px;
  color: var(--text-secondary);
  font-size: 12px;
  font-weight: 750;
  text-align: center;
  text-decoration: none;
}
.quick-nav a:last-child { border-right: 0; }
.quick-nav a:hover {
  background: var(--surface-raised);
  color: var(--text-primary);
}
.quick-nav a[aria-current="location"] {
  background: var(--surface-raised);
  box-shadow: inset 0 -2px 0 var(--accent);
  color: var(--text-primary);
}
main {
  display: grid;
  gap: var(--space-4);
  padding: var(--space-4) 0 var(--space-6);
}
.panel,
.card,
.decision,
.slip-card,
.league-block,
.map-card,
.slip-summary {
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  background: var(--surface) !important;
  box-shadow: none !important;
  clip-path: none !important;
  backdrop-filter: none !important;
}
.panel {
  padding: var(--space-5);
  overflow: visible;
}
.section-head {
  display: flex;
  gap: var(--space-4);
  justify-content: space-between;
  align-items: baseline;
  margin-bottom: var(--space-4);
  padding-bottom: var(--space-3);
  border-bottom: 1px solid var(--border);
}
.section-head p {
  max-width: 520px;
  color: var(--text-muted);
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0;
  text-align: right;
  text-transform: none;
}
.slip-map {
  display: grid;
  grid-template-columns: 220px minmax(0, 1fr);
  gap: var(--space-3);
  align-items: stretch;
}
.slip-summary {
  display: grid;
  align-content: start;
  gap: var(--space-2);
  padding: var(--space-4);
}
.slip-summary span,
.map-card-head span {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.slip-summary strong {
  color: var(--text-primary);
  font-size: 42px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
}
.slip-summary small {
  color: var(--text-secondary);
}
.map-panel {
  display: grid;
  gap: var(--space-3);
}
.map-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-3);
}
.map-card {
  display: grid;
  gap: var(--space-3);
  min-height: 128px;
  padding: var(--space-4);
}
.map-card-head {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  align-items: center;
}
.map-card-head strong {
  color: var(--success);
  font-size: 11px;
  font-weight: 800;
}
.map-count {
  display: flex !important;
  gap: var(--space-2) !important;
  justify-content: flex-start !important;
  align-items: baseline;
}
.map-count strong {
  color: var(--text-primary);
  font-size: 34px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}
.map-count em {
  color: var(--text-muted);
  font-size: 11px;
  font-style: normal;
  font-weight: 800;
  text-transform: uppercase;
}
.map-meta {
  display: grid !important;
  gap: 2px !important;
  color: var(--text-secondary) !important;
}
.map-meta small {
  color: var(--text-secondary);
  font-size: 11px;
}
.update-line {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3);
}
.decision {
  padding: var(--space-4);
}
.decision.good { border-color: color-mix(in srgb, var(--success) 40%, var(--border)) !important; }
.decision.warning { border-color: color-mix(in srgb, var(--warning) 48%, var(--border)) !important; }
.status-heading,
.record-heading {
  display: flex;
  justify-content: space-between;
  gap: var(--space-3);
  align-items: center;
}
.status-heading strong,
.record-rate strong {
  color: var(--text-primary);
  font-size: 24px;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}
.status-heading span,
.record-heading > span:last-child,
.record-rate span {
  color: var(--text-muted);
}
.status-note {
  max-width: 760px;
  margin-top: var(--space-2);
  color: var(--text-secondary);
  font-size: 12px;
}
.metric-strip {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: var(--space-2);
  margin: var(--space-3) 0;
}
.metric-strip span {
  padding: var(--space-3);
}
.metric-strip strong {
  display: block;
  margin-top: 3px;
  font-size: 17px;
  letter-spacing: 0;
}
.record-grid,
.cards {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 320px), 1fr));
  gap: var(--space-3);
}
.card {
  padding: var(--space-4);
}
.pill {
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  padding: 3px 7px;
  background: var(--surface-muted);
  color: var(--text-secondary);
  font-size: 11px;
  font-weight: 750;
}
.pill.good { color: var(--success); border-color: color-mix(in srgb, var(--success) 42%, var(--border)); }
.pill.warning { color: var(--warning); border-color: color-mix(in srgb, var(--warning) 48%, var(--border)); }
.slip-card {
  padding: var(--space-4);
}
.slip-card.empty strong {
  color: var(--warning);
  font-size: 20px;
}
.slip-topline {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: var(--space-4);
  align-items: start;
}
.section-kicker {
  display: block;
  color: var(--text-muted);
}
.slip-count {
  display: flex;
  gap: var(--space-2);
  align-items: baseline;
  margin-top: 6px;
}
.slip-count strong {
  margin: 0;
  color: var(--text-primary);
  font-size: 36px;
  line-height: 1;
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
}
.slip-count span {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 800;
  text-transform: uppercase;
}
.slip-review-state {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-2);
  align-items: center;
  margin-top: var(--space-2);
  color: var(--text-secondary);
  font-size: 12px;
}
.packet-actions {
  display: grid;
  grid-template-columns: repeat(4, minmax(72px, 1fr));
  gap: var(--space-2);
  min-width: 420px;
}
.packet-actions button,
.packet-download {
  display: grid;
  place-items: center;
  text-align: center;
  text-decoration: none;
}
.packet-note {
  margin: var(--space-3) 0 0;
  color: var(--text-muted);
  letter-spacing: .03em;
}
.slip-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 340px), 1fr));
  gap: var(--space-3);
}
.league-block {
  padding: var(--space-3);
  background: var(--surface-muted) !important;
}
.league-title {
  display: flex;
  justify-content: space-between;
  gap: var(--space-2);
  align-items: baseline;
  margin-bottom: var(--space-2);
}
.league-title h3 {
  font-size: 14px;
}
.slip-list {
  display: grid;
  gap: var(--space-2);
  margin: 0;
  padding: 0;
  list-style: none;
}
.slip-leg {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 92px;
  gap: var(--space-2) var(--space-3);
  align-items: start;
  padding: var(--space-3);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: var(--radius-md) !important;
  background: var(--surface);
}
.leg-copy strong {
  display: block;
  color: var(--text-primary);
  font-size: 13px;
  line-height: 1.3;
}
.leg-copy > span {
  display: block;
  margin-top: 3px;
  color: var(--text-secondary);
  font-size: 12px;
}
.leg-chips {
  display: flex;
  flex-wrap: wrap;
  gap: var(--space-1);
  margin-top: var(--space-2);
}
.leg-chips time,
.leg-chips span {
  display: inline-flex;
  margin: 0;
  padding: 3px 6px;
  border: 1px solid var(--border);
  border-radius: var(--radius-sm);
  background: var(--surface-muted);
  color: var(--text-secondary);
  font-size: 10px;
  font-weight: 750;
}
.leg-chips time {
  color: var(--text-primary);
  border-color: var(--border-strong);
}
.leg-metrics {
  min-width: 0;
  text-align: right;
}
.leg-metrics b {
  color: var(--text-primary);
  font-size: 16px;
  font-variant-numeric: tabular-nums;
}
.leg-metrics small {
  color: var(--text-muted);
  font-size: 10px;
}
.leg-details {
  grid-column: 1 / -1;
  padding-top: var(--space-2);
  border-top: 1px solid var(--border);
}
.leg-details summary {
  color: var(--text-muted);
  cursor: pointer;
  font-size: 11px;
  font-weight: 750;
}
.leg-details[open] summary {
  color: var(--info);
}
.leg-details code {
  display: block;
  margin-top: var(--space-2);
  color: var(--text-secondary);
  font-size: 11px;
  overflow-wrap: anywhere;
}
.leg-details dl {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(90px, 1fr));
  gap: var(--space-2);
  margin: var(--space-2) 0 0;
}
.leg-details dl div {
  padding: var(--space-2);
  border: 1px solid var(--border);
  border-radius: var(--radius-md);
  background: var(--surface-muted);
}
.leg-details dd {
  margin: 2px 0 0;
  color: var(--text-secondary);
  font-size: 11px;
}
table {
  width: 100%;
  border-collapse: collapse;
  font-variant-numeric: tabular-nums;
}
th,
td {
  border-bottom: 1px solid var(--border);
  padding: 9px 10px;
  text-align: left;
  vertical-align: top;
}
th {
  color: var(--text-muted);
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .05em;
  text-transform: uppercase;
}
td {
  color: var(--text-secondary);
}
@media (prefers-reduced-motion: reduce) {
  *,
  *::before,
  *::after {
    scroll-behavior: auto !important;
    transition: none !important;
  }
}
@media (max-width: 1100px) {
  .slip-map {
    grid-template-columns: 1fr;
  }
  .map-cards {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .packet-actions {
    min-width: 0;
  }
}
@media (max-width: 760px) {
  .hero,
  .quick-nav,
  main {
    width: calc(100% - 20px) !important;
  }
  .hero {
    grid-template-columns: 1fr !important;
    gap: var(--space-4);
    padding: var(--space-4);
  }
  .refresh-box {
    grid-template-columns: 1fr;
  }
  #refresh-slip {
    width: 100%;
  }
  .quick-nav a {
    min-width: 84px;
    padding: 9px 10px;
  }
  .panel {
    padding: var(--space-4);
  }
  .section-head {
    display: grid;
    gap: var(--space-1);
  }
  .section-head p {
    text-align: left;
  }
  .map-cards,
  .metric-strip,
  .record-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .slip-topline {
    grid-template-columns: 1fr;
  }
  .packet-actions {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .slip-leg {
    grid-template-columns: minmax(0, 1fr);
  }
  .leg-metrics {
    text-align: left;
  }
}
@media (max-width: 430px) {
  .hero,
  .quick-nav,
  main {
    width: calc(100% - 12px) !important;
  }
  h1 {
    font-size: 28px;
  }
  .map-cards,
  .metric-strip,
  .record-metrics,
  .packet-actions {
    grid-template-columns: 1fr;
  }
  .map-card,
  .slip-summary,
  .slip-card,
  .panel {
    padding: var(--space-3);
  }
}

/* Hawknetic Predictions vision shell. The existing report components remain
   source-backed; these rules compose them into the product interface. */
:root {
  --background: #05090c;
  --surface: #0a1115;
  --surface-raised: #0e171c;
  --surface-muted: #081014;
  --surface-soft: #111c22;
  --border: #1d2a30;
  --border-strong: #304149;
  --text-primary: #f2f8f5;
  --text-secondary: #afbeb8;
  --text-muted: #70817a;
  --accent: #00e676;
  --accent-deep: #00c853;
  --accent-hover: #31ee91;
  --purple: #7c4dff;
  --amber: #ffb300;
  --danger: #ff5252;
  --info: #2196f3;
  --focus: #66f2a7;
  --radius-sm: 6px;
  --radius-md: 10px;
  --radius-lg: 14px;
  --shadow-panel: 0 18px 55px rgba(0, 0, 0, .22);
}
html {
  scroll-behavior: smooth;
  scroll-padding-top: 84px;
}
body.product-shell {
  min-width: 320px;
  min-height: 100vh;
  margin: 0;
  background:
    radial-gradient(circle at 78% -10%, rgba(0, 230, 118, .075), transparent 27rem),
    radial-gradient(circle at 20% 35%, rgba(124, 77, 255, .035), transparent 30rem),
    var(--background) !important;
  color: var(--text-primary);
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
.app-topbar {
  position: sticky;
  top: 0;
  z-index: 50;
  display: grid;
  grid-template-columns: 245px minmax(360px, 1fr) auto;
  align-items: center;
  min-height: 66px;
  padding: 0 18px;
  border-bottom: 1px solid var(--border);
  background: rgba(5, 9, 12, .94);
  box-shadow: 0 12px 32px rgba(0, 0, 0, .2);
  backdrop-filter: blur(18px);
}
.brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  width: max-content;
  color: var(--text-primary);
  font-size: 18px;
  font-weight: 720;
  letter-spacing: -.045em;
  text-decoration: none;
}
.brand strong {
  color: var(--accent);
  font-weight: 720;
}
.brand-mark {
  width: 35px;
  height: 35px;
  overflow: visible;
  fill: var(--accent);
  filter: drop-shadow(0 0 13px rgba(0, 230, 118, .25));
}
.brand-eye { fill: #04110a; }
.product-shell .top-navigation {
  position: static;
  display: flex !important;
  justify-content: center;
  width: auto !important;
  margin: 0 !important;
  overflow: visible !important;
  border: 0;
  border-radius: 0 !important;
  background: transparent !important;
}
.product-shell .top-navigation a {
  position: relative;
  min-width: auto;
  min-height: 66px;
  border: 0;
  padding: 0 17px;
  color: #899892;
  font-size: 13px;
  font-weight: 650;
}
.product-shell .top-navigation a:hover,
.product-shell .top-navigation a[aria-current="location"] {
  background: transparent;
  color: var(--text-primary);
  box-shadow: none;
}
.product-shell .top-navigation a::after {
  position: absolute;
  right: 17px;
  bottom: 0;
  left: 17px;
  height: 2px;
  border-radius: 999px 999px 0 0;
  background: var(--accent);
  content: "";
  opacity: 0;
  transform: scaleX(.4);
  transition: opacity .18s ease, transform .18s ease;
}
.product-shell .top-navigation a:hover::after,
.product-shell .top-navigation a[aria-current="location"]::after {
  opacity: 1;
  transform: scaleX(1);
}
.topbar-actions {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  gap: 12px;
}
.research-only-badge {
  display: inline-flex;
  align-items: center;
  gap: 7px;
  min-height: 34px;
  border: 1px solid rgba(0, 230, 118, .32);
  border-radius: 9px;
  padding: 0 11px;
  background: rgba(0, 230, 118, .055);
  color: #a7efc8;
  font-size: 11px;
  font-weight: 760;
  letter-spacing: .035em;
  text-transform: uppercase;
}
.research-only-badge i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 10px rgba(0, 230, 118, .7);
}
.refresh-control {
  display: grid;
  grid-template-columns: auto;
  justify-items: end;
}
.refresh-control #refresh-slip {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  gap: 7px;
  min-width: 104px;
  min-height: 38px;
  border-radius: 9px !important;
  font-size: 12px;
}
.refresh-control #refresh-status {
  position: absolute;
  top: 49px;
  color: var(--text-muted);
  font-size: 9px;
}
.mobile-menu-toggle {
  display: none;
  width: 40px;
  height: 40px;
  min-height: 40px;
  border: 1px solid var(--border) !important;
  border-radius: 9px !important;
  padding: 9px !important;
  background: var(--surface) !important;
}
.mobile-menu-toggle > span:not(.sr-only) {
  display: block;
  width: 18px;
  height: 1px;
  margin: 4px auto;
  background: var(--text-secondary);
}
.app-frame {
  display: grid;
  grid-template-columns: 210px minmax(560px, 1fr) 350px;
  gap: 14px;
  width: min(1920px, 100%);
  margin: 0 auto;
  padding: 14px;
  align-items: start;
}
.app-sidebar,
.prediction-drawer {
  position: sticky;
  top: 80px;
  max-height: calc(100vh - 94px);
  overflow: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border-strong) transparent;
}
.app-sidebar {
  display: grid;
  gap: 18px;
  padding: 13px;
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  background: rgba(8, 16, 20, .9);
  box-shadow: var(--shadow-panel);
}
.sidebar-section {
  display: grid;
  gap: 7px;
}
.sidebar-section + .sidebar-section {
  padding-top: 14px;
  border-top: 1px solid var(--border);
}
.sidebar-label,
.section-label {
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 820;
  letter-spacing: .115em;
  text-transform: uppercase;
}
.sidebar-label { padding: 0 9px 4px; }
.side-navigation {
  display: grid;
  gap: 3px;
}
.side-navigation a {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  align-items: center;
  min-height: 39px;
  border: 1px solid transparent;
  border-radius: 9px;
  padding: 0 9px;
  color: #93a39c;
  font-size: 12px;
  font-weight: 620;
  text-decoration: none;
}
.side-navigation a > span {
  color: #84938d;
  font-size: 15px;
}
.side-navigation a b {
  min-width: 20px;
  border-radius: 999px;
  padding: 2px 6px;
  background: var(--surface-soft);
  color: var(--text-muted);
  font-size: 9px;
  text-align: center;
}
.side-navigation a:hover,
.side-navigation a.active {
  border-color: rgba(0, 230, 118, .18);
  background: linear-gradient(90deg, rgba(0, 230, 118, .12), rgba(0, 230, 118, .025));
  color: var(--text-primary);
}
.side-navigation a:hover > span,
.side-navigation a.active > span { color: var(--accent); }
.sidebar-live-card,
.sidebar-disclaimer {
  display: grid;
  gap: 7px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px;
  background: var(--surface-muted);
}
.sidebar-live-card[data-state="ready"] { border-color: rgba(0, 230, 118, .24); }
.sidebar-live-card strong { font-size: 11px; }
.sidebar-live-card small,
.sidebar-disclaimer p {
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.5;
}
.sidebar-live-card .data-state-message {
  color: var(--text-muted);
  font-size: 10px;
}
.sidebar-disclaimer strong {
  color: var(--text-secondary);
  font-size: 10px;
  text-transform: uppercase;
}
.product-shell main.workspace {
  display: grid;
  gap: 14px;
  width: auto !important;
  min-width: 0;
  padding: 0 0 34px;
}
.workspace-hero,
.product-shell .panel,
.prediction-drawer {
  border: 1px solid var(--border) !important;
  border-radius: var(--radius-lg) !important;
  background: linear-gradient(145deg, rgba(14, 23, 28, .96), rgba(7, 14, 18, .98)) !important;
  box-shadow: var(--shadow-panel) !important;
}
.workspace-hero {
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 16px 22px;
  padding: 22px;
  overflow: hidden;
}
.workspace-hero h1 {
  max-width: 780px;
  margin-top: 4px;
  font-size: clamp(27px, 3.2vw, 46px);
  letter-spacing: -.04em;
}
.workspace-hero h1::after {
  color: var(--accent);
  content: "";
}
.workspace-hero .hero-tagline {
  margin-top: 9px;
  color: var(--text-secondary);
  font-size: 13px;
}
.workspace-meta {
  display: grid;
  grid-template-columns: repeat(2, minmax(118px, 1fr));
  gap: 8px;
  align-self: start;
}
.workspace-meta span,
.builder-stat-grid span,
.drawer-metrics span {
  border: 1px solid var(--border);
  border-radius: 10px;
  background: rgba(4, 10, 13, .7);
}
.workspace-meta span { padding: 9px 11px; }
.workspace-meta small,
.builder-stat-grid small,
.drawer-metrics small {
  display: block;
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 760;
  letter-spacing: .06em;
  text-transform: uppercase;
}
.workspace-meta strong {
  display: block;
  margin-top: 3px;
  color: var(--text-secondary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
}
.source-alert {
  grid-column: 1 / -1;
  display: flex;
  gap: 11px;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 10px 12px;
  background: rgba(0, 0, 0, .13);
}
.source-alert.ready { border-color: rgba(0, 230, 118, .24); }
.source-alert.blocked { border-color: rgba(255, 179, 0, .35); }
.source-alert-icon {
  display: grid;
  place-items: center;
  flex: 0 0 27px;
  height: 27px;
  border-radius: 50%;
  background: rgba(0, 230, 118, .12);
  color: var(--accent);
  font-weight: 900;
}
.source-alert.blocked .source-alert-icon {
  background: rgba(255, 179, 0, .12);
  color: var(--amber);
}
.source-alert strong { font-size: 12px; }
.source-alert p {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 10px;
}
.builder-stat-grid {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 8px;
}
.builder-stat-grid span { padding: 12px; }
.builder-stat-grid strong {
  display: block;
  margin-top: 5px;
  color: var(--text-primary);
  font-size: 22px;
  font-variant-numeric: tabular-nums;
  letter-spacing: -.035em;
}
.product-shell .panel {
  padding: 17px;
  overflow: hidden;
}
.product-shell .section-head {
  align-items: center;
  margin-bottom: 14px;
  padding-bottom: 13px;
  border-color: var(--border);
}
.product-shell .section-head > div { display: grid; gap: 4px; }
.product-shell .section-head h2 {
  font-size: 18px;
  letter-spacing: -.018em;
}
.product-shell .section-head p {
  color: var(--text-muted);
  font-size: 10px;
}
.product-shell .slip-map {
  grid-template-columns: 190px minmax(0, 1fr);
  gap: 10px;
}
.product-shell .slip-summary,
.product-shell .map-card,
.product-shell .update-line {
  background: rgba(6, 13, 16, .78) !important;
}
.product-shell .slip-summary {
  border-color: rgba(0, 230, 118, .2) !important;
}
.product-shell .slip-summary strong { color: var(--accent); }
.product-shell .map-cards { gap: 8px; }
.product-shell .map-card {
  min-height: 114px;
  border-color: var(--border) !important;
  padding: 13px;
}
.product-shell .map-card-head strong { color: var(--accent); }
.product-shell .map-count strong { font-size: 29px; }
.market-browser-list {
  display: grid;
  gap: 8px;
}
.market-browser-row {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) repeat(3, minmax(72px, .32fr)) auto;
  gap: 12px;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px;
  background: rgba(5, 12, 15, .72);
  transition: border-color .16s ease, background .16s ease;
}
.market-browser-row:hover {
  border-color: rgba(0, 230, 118, .28);
  background: rgba(8, 17, 20, .95);
}
.market-browser-heading {
  display: flex;
  gap: 10px;
  min-width: 0;
  align-items: center;
}
.contract-orb {
  flex: 0 0 28px;
  width: 28px;
  height: 28px;
  border: 1px solid rgba(0, 230, 118, .38);
  border-radius: 50%;
  background: radial-gradient(circle, rgba(0, 230, 118, .45) 0 16%, rgba(0, 230, 118, .08) 18% 100%);
  box-shadow: inset 0 0 12px rgba(0, 230, 118, .08);
}
.market-browser-heading div { min-width: 0; }
.market-browser-heading strong {
  display: block;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-browser-heading small {
  display: block;
  margin-top: 3px;
  overflow: hidden;
  color: var(--text-muted);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-quote-cell { text-align: right; }
.market-quote-cell small {
  display: block;
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 760;
  text-transform: uppercase;
}
.market-quote-cell strong {
  color: var(--text-secondary);
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.market-browser-details {
  grid-column: 1 / -1;
  border-top: 1px solid var(--border);
  padding-top: 8px;
}
.market-browser-details summary {
  width: max-content;
  color: var(--accent);
  font-size: 10px;
  font-weight: 700;
  cursor: pointer;
}
.market-browser-details ul {
  display: grid;
  gap: 5px;
  margin: 9px 0 0;
  padding: 0;
  list-style: none;
}
.market-browser-details li {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border-radius: 7px;
  padding: 8px 9px;
  background: var(--surface-muted);
}
.market-browser-details li span { min-width: 0; }
.market-browser-details li strong,
.market-browser-details li small { display: block; }
.market-browser-details li strong {
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.market-browser-details li small {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 9px;
}
.market-browser-details li b {
  color: var(--accent);
  font-size: 11px;
}
.market-browser-details > p {
  margin-top: 8px;
  color: var(--text-muted);
  font-size: 9px;
}
.sports-board-list {
  display: grid;
  gap: 8px;
}
.sports-event {
  display: grid;
  gap: 10px;
  border: 1px solid var(--border);
  border-radius: 11px;
  padding: 12px;
  background: rgba(5, 12, 15, .72);
  transition: border-color .16s ease, background .16s ease;
}
.sports-event:hover {
  border-color: rgba(0, 230, 118, .28);
  background: rgba(8, 17, 20, .95);
}
.sports-event-heading {
  display: flex;
  gap: 10px;
  min-width: 0;
  align-items: center;
}
.sports-event-heading div { min-width: 0; }
.sports-event-heading strong {
  display: block;
  overflow: hidden;
  color: var(--text-primary);
  font-size: 12px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sports-event-heading small {
  display: block;
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 9px;
}
.sports-market-list {
  display: grid;
  gap: 7px;
}
.sports-market {
  border-radius: 8px;
  padding: 8px 9px;
  background: var(--surface-muted);
}
.sports-market-head {
  display: flex;
  gap: 10px;
  justify-content: space-between;
  align-items: baseline;
}
.sports-market-head strong {
  color: var(--text-secondary);
  font-size: 10px;
}
.sports-market-head small {
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 760;
  text-transform: uppercase;
}
.sports-selection-list {
  display: grid;
  gap: 4px;
  margin-top: 7px;
}
.sports-selection {
  display: grid;
  grid-template-columns: minmax(90px, 1fr) minmax(52px, auto) minmax(62px, auto) minmax(62px, auto) auto;
  gap: 9px;
  align-items: center;
}
.sports-selection-name {
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sports-selection-odds {
  color: var(--text-primary);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  font-weight: 760;
  text-align: right;
}
.sports-selection-book {
  color: var(--text-muted);
  font-size: 9px;
  text-align: right;
}
.sports-selection-fair { text-align: right; }
.sports-selection-fair small {
  display: block;
  color: var(--text-muted);
  font-size: 8px;
  font-weight: 760;
  text-transform: uppercase;
}
.sports-selection-fair b {
  color: var(--text-secondary);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}
.sports-shop-pill { justify-self: end; }
.sports-state-reason {
  color: var(--text-muted);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 9px;
}
@media (max-width: 640px) {
  .sports-selection {
    grid-template-columns: minmax(0, 1fr) auto auto;
  }
  .sports-selection-book { display: none; }
}

.product-empty-state,
.drawer-empty-state {
  display: grid;
  place-items: center;
  gap: 7px;
  min-height: 190px;
  border: 1px dashed var(--border-strong);
  border-radius: 12px;
  padding: 22px;
  background: rgba(5, 12, 15, .52);
  text-align: center;
}
.product-empty-state .empty-state-icon {
  display: grid;
  place-items: center;
  width: 46px;
  height: 46px;
  border-radius: 50%;
  background: rgba(0, 230, 118, .09);
  color: var(--accent);
  font-size: 25px;
}
.product-empty-state strong,
.drawer-empty-state strong { font-size: 14px; }
.product-empty-state p,
.drawer-empty-state p,
.drawer-empty-state small {
  max-width: 560px;
  color: var(--text-muted);
  font-size: 10px;
  line-height: 1.55;
}
.prediction-drawer {
  display: grid;
  gap: 13px;
  padding: 15px;
}
.drawer-header {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  align-items: center;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}
.drawer-header > div { display: grid; gap: 3px; }
.drawer-header h2 {
  font-size: 18px;
  letter-spacing: -.025em;
}
.drawer-header > a {
  display: grid;
  place-items: center;
  width: 34px;
  height: 34px;
  border: 1px solid var(--border);
  border-radius: 9px;
  color: var(--text-secondary);
  text-decoration: none;
}
.drawer-slip-state {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 6px 9px;
  align-items: center;
}
.drawer-slip-state .pill { grid-row: 1 / span 2; }
.drawer-slip-state strong { font-size: 12px; }
.drawer-slip-state small { color: var(--text-muted); font-size: 9px; }
.drawer-alert {
  display: flex;
  gap: 9px;
  border: 1px solid rgba(255, 179, 0, .3);
  border-radius: 10px;
  padding: 10px;
  background: rgba(255, 179, 0, .055);
}
.drawer-alert > span { color: var(--amber); font-size: 17px; }
.drawer-alert p {
  color: #c3b791;
  font-size: 9px;
  line-height: 1.5;
}
.drawer-metrics {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 7px;
}
.drawer-metrics span { padding: 9px; }
.drawer-metrics strong {
  display: block;
  margin-top: 4px;
  color: var(--text-primary);
  font-size: 14px;
  font-variant-numeric: tabular-nums;
}
.drawer-leg-list {
  display: grid;
  gap: 4px;
  max-height: 390px;
  margin: 0;
  padding: 0;
  overflow: auto;
  list-style: none;
}
.drawer-leg-list li {
  display: grid;
  grid-template-columns: 8px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: start;
  border-bottom: 1px solid rgba(29, 42, 48, .72);
  padding: 8px 3px;
}
.leg-status-dot {
  width: 7px;
  height: 7px;
  margin-top: 5px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 8px rgba(0, 230, 118, .45);
}
.drawer-leg-list strong,
.drawer-leg-list small,
.drawer-leg-list time { display: block; }
.drawer-leg-list strong {
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 10px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.drawer-leg-list small,
.drawer-leg-list time {
  margin-top: 2px;
  color: var(--text-muted);
  font-size: 8px;
}
.drawer-leg-list b {
  color: var(--accent);
  font-size: 10px;
  font-variant-numeric: tabular-nums;
}
.drawer-more {
  color: var(--text-muted);
  font-size: 9px;
  text-align: center;
}
.prediction-drawer button.copy.drawer-primary-action {
  width: 100%;
  min-height: 45px;
  border: 0 !important;
  border-radius: 10px !important;
  background: linear-gradient(100deg, var(--accent-deep), #42eca0) !important;
  color: #03120a !important;
}
.drawer-action-row {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 7px;
}
.drawer-action-row a,
.drawer-secondary-action {
  display: grid;
  place-items: center;
  min-height: 38px;
  border: 1px solid var(--border);
  border-radius: 9px;
  background: var(--surface-muted);
  color: var(--text-secondary);
  font-size: 9px;
  font-weight: 700;
  text-align: center;
  text-decoration: none;
}
.drawer-trust-card {
  display: flex;
  gap: 9px;
  border: 1px solid rgba(124, 77, 255, .23);
  border-radius: 10px;
  padding: 10px;
  background: rgba(124, 77, 255, .045);
}
.drawer-trust-card > span {
  display: grid;
  place-items: center;
  flex: 0 0 25px;
  height: 25px;
  border-radius: 50%;
  background: rgba(124, 77, 255, .14);
  color: #aa8dff;
}
.drawer-trust-card strong { font-size: 10px; }
.drawer-trust-card p {
  margin-top: 3px;
  color: var(--text-muted);
  font-size: 9px;
  line-height: 1.45;
}
.drawer-warning {
  display: grid;
  place-items: center;
  width: 43px;
  height: 43px;
  border-radius: 50%;
  background: rgba(255, 179, 0, .1);
  color: var(--amber);
  font-size: 20px;
  font-weight: 900;
}
.product-shell .decision,
.product-shell .slip-card,
.product-shell .league-block,
.product-shell .card {
  border-color: var(--border) !important;
  background: rgba(6, 13, 16, .72) !important;
}
.product-shell .decision.good { border-color: rgba(0, 230, 118, .26) !important; }
.product-shell .decision.warning { border-color: rgba(255, 179, 0, .3) !important; }
.product-shell .metric-strip span,
.product-shell .prob-grid span,
.product-shell .quote-grid span {
  border-color: var(--border);
  background: var(--surface-muted);
}
.product-shell .slip-card { padding: 15px; }
.product-shell .slip-count strong { color: var(--accent); }
.product-shell .packet-note {
  margin: 11px 0;
  border-left: 2px solid var(--amber);
  padding-left: 9px;
  color: #a99870;
}
.product-shell .league-block { padding: 10px; }
.product-shell .slip-leg {
  border-color: var(--border);
  border-left-color: var(--accent);
  background: var(--surface-muted);
}
.product-shell .leg-metrics b { color: var(--accent); }
.product-shell .pill.good {
  border-color: rgba(0, 230, 118, .3);
  background: rgba(0, 230, 118, .07);
  color: var(--accent);
}
.product-shell .pill.warning {
  border-color: rgba(255, 179, 0, .34);
  background: rgba(255, 179, 0, .065);
  color: var(--amber);
}
.sport-filter-list {
  display: grid;
  gap: 4px;
}
.sport-filter {
  display: grid;
  grid-template-columns: 22px minmax(0, 1fr) auto;
  gap: 7px;
  align-items: center;
  width: 100%;
  min-height: 40px;
  border: 1px solid transparent !important;
  border-radius: 9px !important;
  padding: 0 9px !important;
  background: transparent !important;
  color: #93a39c !important;
  font-size: 12px !important;
  font-weight: 620 !important;
  text-align: left;
  cursor: pointer;
}
.sport-filter span { color: #84938d; font-size: 15px; }
.sport-filter b {
  min-width: 22px;
  border-radius: 999px;
  padding: 2px 6px;
  background: var(--surface-soft);
  color: var(--text-muted);
  font-size: 9px;
  text-align: center;
}
.sport-filter:hover,
.sport-filter.active {
  border-color: rgba(0, 230, 118, .2) !important;
  background: linear-gradient(90deg, rgba(0, 230, 118, .14), rgba(0, 230, 118, .025)) !important;
  color: var(--text-primary) !important;
}
.sport-filter.active span { color: var(--accent); }
.sidebar-select {
  display: grid;
  gap: 5px;
  color: var(--text-muted);
  font-size: 9px;
  font-weight: 750;
  text-transform: uppercase;
}
.sidebar-select select {
  width: 100%;
  min-height: 38px;
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 0 9px;
  background: var(--surface-muted);
  color: var(--text-secondary);
  font: inherit;
  font-size: 11px;
  text-transform: none;
}
.workspace-hero {
  padding: 18px 19px;
}
.workspace-hero h1 {
  font-size: clamp(24px, 2.3vw, 34px);
}
.builder-toolbar {
  grid-column: 1 / -1;
  display: grid;
  grid-template-columns: minmax(220px, 1fr) auto auto;
  gap: 9px;
  align-items: center;
  border-top: 1px solid var(--border);
  padding-top: 14px;
}
.builder-search {
  display: grid;
  grid-template-columns: auto minmax(0, 1fr);
  gap: 9px;
  align-items: center;
  min-height: 42px;
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 0 12px;
  background: rgba(4, 10, 13, .78);
  color: var(--text-muted);
}
.builder-search:focus-within { border-color: rgba(0, 230, 118, .52); }
.builder-search input {
  min-width: 0;
  border: 0;
  outline: 0;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 12px;
}
.builder-search input::placeholder { color: var(--text-muted); }
.date-tabs {
  display: flex;
  gap: 4px;
  min-height: 42px;
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 4px;
  background: rgba(4, 10, 13, .78);
}
.date-tabs button {
  min-height: 32px;
  border: 0 !important;
  border-radius: 7px !important;
  padding: 0 11px !important;
  background: transparent !important;
  color: var(--text-muted) !important;
  font-size: 10px !important;
}
.date-tabs button.active {
  background: rgba(0, 230, 118, .12) !important;
  color: var(--accent) !important;
}
.toolbar-live {
  display: inline-flex;
  gap: 7px;
  align-items: center;
  color: var(--text-muted);
  font-size: 10px;
  white-space: nowrap;
}
.toolbar-live i {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--accent);
  box-shadow: 0 0 9px rgba(0, 230, 118, .65);
}
.builder-board-panel .sports-board-list { gap: 9px; }
.builder-board-panel .sports-event {
  grid-template-columns: minmax(180px, .42fr) minmax(0, 1fr);
  align-items: start;
  padding: 13px;
}
.builder-board-panel .sports-market-list {
  grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
}
.builder-board-panel .sports-market { min-width: 0; }
.builder-board-panel .sports-selection {
  grid-template-columns: minmax(0, 1fr) auto;
  gap: 7px;
}
.builder-board-panel .sports-selection-book,
.builder-board-panel .sports-selection-fair,
.builder-board-panel .sports-shop-pill { display: none; }
.drawer-watchlist-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding-top: 2px;
}
.drawer-watchlist-head strong { color: var(--text-secondary); font-size: 11px; }
.drawer-watchlist-head span { color: var(--text-muted); font-size: 9px; }
.drawer-watchlist {
  display: grid;
  gap: 5px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.drawer-watchlist li {
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) auto;
  gap: 8px;
  align-items: center;
  border: 1px solid var(--border);
  border-radius: 9px;
  padding: 9px;
  background: var(--surface-muted);
}
.drawer-watchlist .contract-orb { width: 25px; height: 25px; }
.drawer-watchlist li > div { min-width: 0; }
.drawer-watchlist li strong,
.drawer-watchlist li small { display: block; }
.drawer-watchlist li strong {
  overflow: hidden;
  color: var(--text-secondary);
  font-size: 9px;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.drawer-watchlist li small { margin-top: 3px; color: var(--text-muted); font-size: 8px; }
.drawer-watch-state { display: grid; justify-items: end; gap: 4px; }
.drawer-watch-state b { color: var(--accent); font-size: 10px; }
.drawer-watch-state .pill { padding: 2px 5px; font-size: 7px; white-space: nowrap; }
.drawer-source-context {
  border-left: 2px solid var(--purple);
  padding-left: 9px;
  color: var(--text-muted);
  font-size: 9px;
  line-height: 1.5;
}
.drawer-primary-link {
  display: flex;
  justify-content: center;
  gap: 8px;
  align-items: center;
  min-height: 43px;
  border-radius: 9px;
  background: linear-gradient(100deg, var(--accent-deep), #42eca0);
  color: #03120a;
  font-size: 10px;
  font-weight: 800;
  text-decoration: none;
}
.mobile-bottom-nav { display: none; }

@media (max-width: 1450px) {
  .app-frame { grid-template-columns: 190px minmax(510px, 1fr) 326px; }
  .market-browser-row { grid-template-columns: minmax(230px, 1fr) repeat(3, minmax(62px, .26fr)) auto; }
  .workspace-meta { grid-template-columns: 1fr; }
}
@media (max-width: 1180px) {
  .app-topbar { grid-template-columns: auto minmax(300px, 1fr) auto; }
  .mobile-menu-toggle { display: block; margin-right: 10px; }
  .brand { grid-column: 2; }
  .product-shell .top-navigation { display: none !important; }
  .app-frame { grid-template-columns: minmax(0, 1fr) 330px; }
  .app-sidebar {
    position: fixed;
    top: 76px;
    bottom: 12px;
    left: 12px;
    z-index: 60;
    width: 224px;
    max-height: none;
    transform: translateX(calc(-100% - 22px));
    transition: transform .2s ease;
  }
  .app-sidebar.open { transform: translateX(0); }
  .product-shell .map-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 900px) {
  .app-frame { grid-template-columns: minmax(0, 1fr); }
  .prediction-drawer {
    position: static;
    grid-row: 1;
    max-height: none;
  }
  .workspace { grid-row: 2; }
  .drawer-leg-list { max-height: 300px; }
  .workspace-hero { grid-template-columns: 1fr; }
  .workspace-meta { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .builder-toolbar { grid-template-columns: minmax(0, 1fr) auto; }
  .toolbar-live { display: none; }
  .market-browser-row { grid-template-columns: minmax(220px, 1fr) repeat(3, minmax(62px, .3fr)) auto; }
}
@media (max-width: 680px) {
  body.product-shell { padding-bottom: 69px; }
  .app-topbar {
    grid-template-columns: auto minmax(0, 1fr) auto;
    min-height: 58px;
    padding: 0 9px;
  }
  .brand { justify-self: center; font-size: 15px; }
  .brand-mark { width: 29px; height: 29px; }
  .research-only-badge { display: none; }
  .refresh-control #refresh-slip {
    min-width: 40px;
    width: 40px;
    min-height: 40px;
    padding: 0;
    font-size: 0;
  }
  .refresh-control #refresh-slip .refresh-icon {
    display: inline-grid;
    place-items: center;
    font-size: 18px;
  }
  .refresh-control #refresh-slip .refresh-label { display: none; }
  .refresh-control #refresh-status { display: none; }
  .app-frame { gap: 8px; padding: 8px; }
  .app-sidebar { top: 66px; left: 8px; bottom: 76px; }
  .workspace-hero,
  .product-shell .panel,
  .prediction-drawer {
    border-radius: 12px !important;
    box-shadow: none !important;
  }
  .workspace-hero { padding: 16px; }
  .workspace-hero h1 { font-size: 28px; }
  .workspace-meta { grid-template-columns: 1fr 1fr; }
  .builder-stat-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .builder-toolbar { grid-template-columns: 1fr; }
  .date-tabs { overflow-x: auto; }
  .product-shell .panel { padding: 13px; }
  .product-shell .section-head {
    display: grid;
    gap: 5px;
    align-items: start;
  }
  .product-shell .section-head p { text-align: left; }
  .product-shell .slip-map { grid-template-columns: 1fr; }
  .product-shell .map-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .product-shell .map-card { min-height: 105px; }
  .market-browser-row {
    grid-template-columns: minmax(0, 1fr) auto;
    gap: 8px;
  }
  .market-browser-heading { grid-column: 1 / -1; }
  .market-quote-cell { text-align: left; }
  .market-browser-row > .market-quote-cell:nth-of-type(3) { display: none; }
  .market-browser-row > .pill { justify-self: end; }
  .builder-board-panel .sports-event { grid-template-columns: 1fr; }
  .builder-board-panel .sports-market-list { grid-template-columns: 1fr; }
  .prediction-drawer { padding: 13px; }
  .drawer-metrics { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .drawer-metrics span { padding: 8px; }
  .drawer-metrics strong { font-size: 12px; }
  .product-shell .slip-topline { grid-template-columns: 1fr; }
  .product-shell .packet-actions { grid-template-columns: 1fr 1fr; min-width: 0; }
  .product-shell .slip-groups { grid-template-columns: 1fr; }
  .product-shell .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .mobile-bottom-nav {
    position: fixed;
    right: 0;
    bottom: 0;
    left: 0;
    z-index: 70;
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    min-height: 62px;
    border-top: 1px solid var(--border);
    padding: 6px max(7px, env(safe-area-inset-right)) max(6px, env(safe-area-inset-bottom)) max(7px, env(safe-area-inset-left));
    background: rgba(5, 9, 12, .97);
    backdrop-filter: blur(18px);
  }
  .mobile-bottom-nav a {
    display: grid;
    place-items: center;
    gap: 1px;
    color: var(--text-muted);
    font-size: 8px;
    font-weight: 690;
    text-decoration: none;
  }
  .mobile-bottom-nav a span { color: var(--text-secondary); font-size: 17px; }
  .mobile-bottom-nav a:first-child,
  .mobile-bottom-nav a:first-child span { color: var(--accent); }
}
@media (max-width: 410px) {
  .brand span { font-size: 14px; }
  .brand-mark { width: 26px; height: 26px; }
  .workspace-hero h1 { font-size: 25px; }
  .workspace-meta,
  .builder-stat-grid,
  .product-shell .map-cards,
  .drawer-action-row { grid-template-columns: 1fr; }
  .drawer-metrics { grid-template-columns: 1fr 1fr 1fr; }
  .product-shell .packet-actions { grid-template-columns: 1fr; }
}
"""


JS = r"""
const legs = document.querySelector("#legs");
const target = document.querySelector("#target");
const penalty = document.querySelector("#penalty");
const combined = document.querySelector("#combined");
const adjusted = document.querySelector("#adjusted");
const statusText = document.querySelector("#status");
const refreshButton = document.querySelector("#refresh-slip");
const refreshStatus = document.querySelector("#refresh-status");
let refreshPollTimer = null;
let liveDataPollTimer = null;
const liveDataGeneratedAt = window.PAPER_DATA?.generated_at || "";
function researchActionHeaders() {
  const csrfToken = sessionStorage.getItem("research_csrf_token") || "";
  const headers = { "X-Research-Action": "refresh-dashboard" };
  if (csrfToken) headers["X-CSRF-Token"] = csrfToken;
  return headers;
}
const LIVE_DATA_POLL_SECONDS = 60;
const LIVE_DATA_STALE_SECONDS = 300;

function formatTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function formatEventTime(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Time TBD";
  const now = new Date();
  const dateKey = new Date(date.getFullYear(), date.getMonth(), date.getDate());
  const todayKey = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const dayDelta = Math.round((dateKey - todayKey) / 86400000);
  const dayText = dayDelta === 0
    ? "Today"
    : dayDelta === 1
      ? "Tomorrow"
      : date.toLocaleDateString([], { month: "short", day: "numeric" });
  const timeText = date.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return `${dayText} · ${timeText}`;
}

document.querySelectorAll("time[datetime]").forEach(element => {
  element.textContent = formatEventTime(element.dateTime);
});

function setRefreshStatus(status) {
  if (!refreshStatus || !refreshButton) return;
  const state = status?.state || "idle";
  const refreshLabel = refreshButton.querySelector(".refresh-label");
  refreshStatus.className = "";
  if (state === "running") {
    refreshButton.disabled = true;
    if (refreshLabel) refreshLabel.textContent = "Refreshing…";
    refreshStatus.classList.add("warning");
    refreshStatus.textContent = "Updating";
    return;
  }
  refreshButton.disabled = false;
  if (refreshLabel) refreshLabel.textContent = "Refresh";
  if (state === "complete") {
    refreshStatus.classList.add("good");
    refreshStatus.textContent = `Live · ${formatTimestamp(status.generated_at)}`;
    return;
  }
  if (state === "error") {
    refreshStatus.classList.add("bad");
    refreshStatus.textContent = status.error || status.message || "Refresh failed.";
    return;
  }
  refreshStatus.textContent = "Ready";
}

async function fetchRefreshStatus() {
  const response = await fetch("/refresh-status", { cache: "no-store" });
  return response.json();
}

async function pollRefreshStatus() {
  try {
    const status = await fetchRefreshStatus();
    setRefreshStatus(status);
    if (status.state === "running") {
      refreshPollTimer = setTimeout(pollRefreshStatus, 2000);
      return;
    }
    if (status.state === "complete") {
      setTimeout(() => window.location.reload(), 900);
    }
  } catch (error) {
    setRefreshStatus({ state: "error", error: `Refresh status check failed: ${error.message}` });
  }
}

async function triggerSlipRefresh() {
  if (!refreshButton) return;
  clearTimeout(refreshPollTimer);
  setRefreshStatus({ state: "running" });
  try {
    const response = await fetch("/refresh", {
      method: "POST",
      cache: "no-store",
      headers: researchActionHeaders(),
    });
    const status = await response.json();
    setRefreshStatus(status);
    if (status.state === "running") {
      refreshPollTimer = setTimeout(pollRefreshStatus, 2000);
    }
    if (!response.ok && status.state !== "running") {
      setRefreshStatus({ state: "error", error: status.message || "Refresh request was rejected." });
    }
  } catch (error) {
    setRefreshStatus({ state: "error", error: `Refresh request failed: ${error.message}` });
  }
}

async function pollLiveDataFreshness() {
  try {
    const response = await fetch("/quality.json", { cache: "no-store" });
    const quality = await response.json();
    if (quality.generated_at && liveDataGeneratedAt && quality.generated_at !== liveDataGeneratedAt) {
      window.location.reload();
      return;
    }
    if (Number(quality.data_age_seconds || 0) > LIVE_DATA_STALE_SECONDS) {
      const status = await fetchRefreshStatus().catch(() => ({}));
      if (status.state !== "running") {
        const refreshResponse = await fetch("/refresh", {
          method: "POST",
          cache: "no-store",
          headers: researchActionHeaders(),
        });
        const refreshPayload = await refreshResponse.json().catch(() => ({}));
        setRefreshStatus(refreshPayload);
        if (refreshPayload.state === "running") {
          refreshPollTimer = setTimeout(pollRefreshStatus, 2000);
        }
      }
    }
  } catch (error) {
    setRefreshStatus({ state: "error", error: `Live freshness check failed: ${error.message}` });
  } finally {
    liveDataPollTimer = setTimeout(pollLiveDataFreshness, LIVE_DATA_POLL_SECONDS * 1000);
  }
}

function addLeg(label = "", probability = "") {
  const row = document.createElement("div");
  row.className = "leg-row";
  row.innerHTML = `
    <label>Leg label<input class="label" value="${label}" placeholder="MLB over 8.5 runs"></label>
    <label>Probability %<input class="prob" type="number" min="1" max="99.9" step="0.1" value="${probability}"></label>
    <label>Entry cents<input class="price" type="number" min="0" max="100" step="0.1"></label>
    <button type="button" class="remove">x</button>
  `;
  row.querySelector(".remove").addEventListener("click", () => {
    row.remove();
    recalc();
  });
  row.querySelectorAll("input").forEach(input => input.addEventListener("input", recalc));
  legs.appendChild(row);
  recalc();
}

function recalc() {
  if (!legs || !target || !penalty || !combined || !adjusted || !statusText) {
    return;
  }
  const probs = [...document.querySelectorAll(".prob")]
    .map(input => Number(input.value) / 100)
    .filter(value => value > 0 && value <= 1);
  if (!probs.length) {
    combined.textContent = "0.00%";
    adjusted.textContent = "0.00%";
    statusText.textContent = "Add legs";
    return;
  }
  const raw = probs.reduce((acc, value) => acc * value, 1);
  const adj = raw * (1 - Number(penalty.value || 0) / 100);
  const targetValue = Number(target.value || 80) / 100;
  combined.textContent = `${(raw * 100).toFixed(2)}%`;
  adjusted.textContent = `${(adj * 100).toFixed(2)}%`;
  statusText.textContent = adj >= targetValue ? "Meets target" : "Below target";
  statusText.style.color = adj >= targetValue ? "var(--accent)" : "var(--bad)";
}

const addLegButton = document.querySelector("#add-leg");
const clearLegsButton = document.querySelector("#clear-legs");
if (addLegButton) addLegButton.addEventListener("click", () => addLeg());
if (clearLegsButton && legs) {
  clearLegsButton.addEventListener("click", () => {
    legs.innerHTML = "";
    recalc();
  });
}
document.querySelectorAll(".copy").forEach(button => {
  const originalText = button.textContent;
  button.addEventListener("click", async () => {
    const text = button.dataset.copy || button.dataset.title || "";
    await navigator.clipboard.writeText(text);
    button.textContent = "Copied";
    setTimeout(() => button.textContent = originalText, 900);
  });
});
const sectionLinks = [...document.querySelectorAll('.quick-nav a[href^="#"], .mobile-bottom-nav a[href^="#"], .side-navigation a[href^="#"]')];
const linkedSections = [...new Set(sectionLinks
  .map(link => document.querySelector(link.getAttribute("href")))
  .filter(Boolean))];
function setCurrentSection(sectionId) {
  sectionLinks.forEach(link => {
    if (link.getAttribute("href") === `#${sectionId}`) {
      link.setAttribute("aria-current", "location");
    } else {
      link.removeAttribute("aria-current");
    }
  });
}
if (sectionLinks.length) {
  const initialSectionId = window.location.hash.slice(1) || linkedSections[0]?.id;
  if (initialSectionId) setCurrentSection(initialSectionId);
  sectionLinks.forEach(link => link.addEventListener("click", () => {
    setCurrentSection(link.getAttribute("href").slice(1));
  }));
}
if ("IntersectionObserver" in window && linkedSections.length) {
  const sectionObserver = new IntersectionObserver(entries => {
    const visibleSection = entries
      .filter(entry => entry.isIntersecting)
      .sort((left, right) => right.intersectionRatio - left.intersectionRatio)[0];
    if (visibleSection) setCurrentSection(visibleSection.target.id);
  }, { rootMargin: "-20% 0px -65% 0px", threshold: [0.01, 0.25, 0.6] });
  linkedSections.forEach(section => sectionObserver.observe(section));
}
if (target) target.addEventListener("input", recalc);
if (penalty) penalty.addEventListener("input", recalc);
if (refreshButton) {
  refreshButton.addEventListener("click", triggerSlipRefresh);
  fetchRefreshStatus().then(status => {
    setRefreshStatus(status);
    if (status.state === "running") {
      refreshPollTimer = setTimeout(pollRefreshStatus, 2000);
    }
  }).catch(() => {});
}
const mobileMenuToggle = document.querySelector("#mobile-menu-toggle");
const appSidebar = document.querySelector("#app-sidebar");
function setMobileMenu(open) {
  if (!mobileMenuToggle || !appSidebar) return;
  appSidebar.classList.toggle("open", open);
  mobileMenuToggle.setAttribute("aria-expanded", String(open));
}
if (mobileMenuToggle && appSidebar) {
  mobileMenuToggle.addEventListener("click", () => {
    setMobileMenu(!appSidebar.classList.contains("open"));
  });
  appSidebar.querySelectorAll('a[href^="#"]').forEach(link => {
    link.addEventListener("click", () => setMobileMenu(false));
  });
  document.addEventListener("keydown", event => {
    if (event.key === "Escape") setMobileMenu(false);
  });
}
const sportFilters = [...document.querySelectorAll(".sport-filter")];
const marketSearch = document.querySelector("#market-search");
let activeLeague = "all";
function applyMarketFilters() {
  const query = (marketSearch?.value || "").trim().toLowerCase();
  document.querySelectorAll(".sports-event").forEach(event => {
    const leagueMatch = activeLeague === "all" || event.dataset.league === activeLeague;
    const searchMatch = !query || (event.dataset.search || "").includes(query);
    event.hidden = !(leagueMatch && searchMatch);
  });
  document.querySelectorAll(".market-browser-row").forEach(row => {
    row.hidden = Boolean(query) && !(row.dataset.search || "").includes(query);
  });
}
sportFilters.forEach(button => {
  button.addEventListener("click", () => {
    activeLeague = button.dataset.league || "all";
    sportFilters.forEach(item => item.classList.toggle("active", item === button));
    applyMarketFilters();
    if (window.innerWidth <= 1180) setMobileMenu(false);
  });
});
if (marketSearch) marketSearch.addEventListener("input", applyMarketFilters);
document.querySelectorAll(".date-tabs button").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".date-tabs button").forEach(item => item.classList.toggle("active", item === button));
  });
});
liveDataPollTimer = setTimeout(pollLiveDataFreshness, LIVE_DATA_POLL_SECONDS * 1000);
recalc();
"""
