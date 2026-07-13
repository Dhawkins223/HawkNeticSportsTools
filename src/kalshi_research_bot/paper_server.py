from __future__ import annotations

import base64
import html
import json
import os
import secrets
import sqlite3
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
from .database import database_startup_status, production_safety_status
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
from .storage import ResearchStore


REFRESH_COOLDOWN_SECONDS = 60
DEFAULT_KALSHI_RUN_ID = "stage3a_20260703_170707"
DEFAULT_REFRESH_LEDGER_MAX_PAYLOAD_AGE_SECONDS = 1800
DEFAULT_DASHBOARD_MAX_SLIP_AGE_SECONDS = 1800
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
    return any(str(values.get(name) or "").strip() for name in HOSTED_RUNTIME_ENV_KEYS)


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
    return bool(values.get("DASHBOARD_AUTH_PASSWORD")) or user_auth_enabled(values) or not dashboard_auth_enabled(dict(values))


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
            role = "admin"
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
  <title>Research Dashboard Sign In</title>
  <style>
    :root { color-scheme: dark; font-family: Inter, ui-sans-serif, system-ui, sans-serif; --bg:#0b0f12; --surface:#11171b; --muted:#879893; --text:#edf4f1; --border:#2a363b; --accent:#29b779; --danger:#e05d50; }
    * { box-sizing: border-box; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; padding: 20px; background: var(--bg); color: var(--text); }
    main { width: min(100%, 420px); padding: 24px; border: 1px solid var(--border); border-radius: 8px; background: var(--surface); }
    h1 { margin: 0 0 8px; font-size: 30px; line-height: 1.1; letter-spacing: 0; }
    p { color: #b8c6c1; line-height: 1.5; }
    main > p:first-child { margin: 0 0 8px; color: var(--muted); font-size: 11px; font-weight: 800; letter-spacing: .08em; text-transform: uppercase; }
    label { display: grid; gap: 7px; margin: 16px 0; color: #b8c6c1; font-size: 13px; font-weight: 750; }
    input { width: 100%; min-height: 44px; border: 1px solid var(--border); border-radius: 6px; padding: 10px 12px; background: #0f1518; color: var(--text); font: inherit; }
    input:focus-visible { outline: 2px solid #75b9e6; outline-offset: 2px; }
    button { width: 100%; min-height: 44px; border: 1px solid var(--accent); border-radius: 6px; background: var(--accent); color: #06100c; font: inherit; font-weight: 800; cursor: pointer; }
    #login-status { min-height: 24px; color: var(--danger); }
  </style>
</head>
<body>
  <main>
    <p>Private research platform</p>
    <h1>Sign in</h1>
    <p>Use your local research account. Live trading and account order controls are not available.</p>
    <form id="login-form">
      <label>Username<input name="username" autocomplete="username" required></label>
      <label>Password<input name="password" type="password" autocomplete="current-password" required></label>
      <button type="submit">Sign in</button>
      <p id="login-status" role="status" aria-live="polite"></p>
    </form>
  </main>
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
    ready = gate["status"] == "ready" and bool(database.get("ready")) and safety["ready"]
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
        "production_safety": safety,
    }


def _paper_run_exists(store: ResearchStore, run_id: str) -> bool:
    store.initialize()
    with store.connect() as connection:
        row = connection.execute(
            "SELECT 1 FROM paper_test_runs WHERE run_id = ? LIMIT 1",
            (run_id,),
        ).fetchone()
    return bool(row)


def _ensure_paper_run(store: ResearchStore, run_id: str) -> bool:
    if _paper_run_exists(store, run_id):
        return False
    from .evaluation.paper_live import start_paper_test_run

    try:
        start_paper_test_run(store, run_id=run_id)
        return True
    except sqlite3.IntegrityError:
        return False


def log_refresh_predictions(payload: dict, *, db_path: str | Path | None = None) -> dict:
    from .evaluation.paper_live import log_forward_predictions

    run_id = os.environ.get("KALSHI_RUN_ID") or DEFAULT_KALSHI_RUN_ID
    max_payload_age_seconds = _env_int(
        "KALSHI_PAPER_MAX_PAYLOAD_AGE_SECONDS",
        DEFAULT_REFRESH_LEDGER_MAX_PAYLOAD_AGE_SECONDS,
    )
    store = ResearchStore(db_path or repo_path("data", "evaluation.sqlite"))
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
        "db_path": str(store.path),
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
        stamp = stamp.astimezone()
        today = datetime.now().astimezone().date()
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
    payload_json = json.dumps(
        {
            "generated_at": payload.get("generated_at"),
            "public_data_gate": payload.get("public_data_gate"),
        }
    ).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>Kalshi Research Slips</title>
  <style>{CSS}</style>
</head>
<body>
  <a class="skip-link" href="#primary">Skip to slips</a>
  <header class="hero">
    <div class="hero-copy">
      <p class="eyebrow">Private Research Dashboard</p>
      <h1>Kalshi Slip Desk</h1>
      <p class="hero-tagline">Fresh market data, manual review packets, no account automation.</p>
      <div class="hero-meta">
        <span><small>Updated</small><strong>{html.escape(display_generated_at)}</strong></span>
        <span><small>Refresh</small><strong>{html.escape(refresh_label)}</strong></span>
      </div>
      {refresh_error_html}
    </div>
    <div class="refresh-box" data-state="{data_state}">
      <div class="live-badge {data_state}" role="status"><i aria-hidden="true"></i><span>{data_label}</span></div>
      <button id="refresh-slip" type="button">Refresh</button>
      <span id="refresh-status" aria-live="polite">Ready</span>
      {data_message_html}
    </div>
  </header>

  <nav class="quick-nav" aria-label="Dashboard sections">
    <a href="#map">Summary</a>
    <a href="#quality">Live</a>
    <a href="#record">Record</a>
    <a href="#primary">80c+</a>
    <a href="#leverage">75c+</a>
    <a href="#all-day">All-Day</a>
    <a href="#research-edge">Scout</a>
  </nav>

  <main>
    <section class="panel" id="map">
      <div class="section-head">
        <h2>Today's Slips</h2>
        <p>Manual-entry readiness by tier</p>
      </div>
      {render_visual_section(payload)}
    </section>

    <section class="panel" id="quality">
      <div class="section-head">
        <h2>Live Status</h2>
        <p>Fresh source data required</p>
      </div>
      {render_quality_panel(quality_status, public_data_gate)}
    </section>

    <section class="panel" id="record">
      <div class="section-head">
        <h2>Track Record</h2>
        <p>Settled rows only</p>
      </div>
      {render_research_record_panel(research_record)}
    </section>

    <section class="panel" id="primary">
      <div class="section-head">
        <h2>80c+ Market Tier</h2>
        <p>Higher-price legs</p>
      </div>
      {render_slip_section(primary_slip, "80c+ MARKET TIER", "primary", payload)}
    </section>

    <section class="panel" id="leverage">
      <div class="section-head">
        <h2>75c+ Market Tier</h2>
        <p>More variance</p>
      </div>
      {render_slip_section(leverage_slip, "75c+ MARKET TIER", "leverage", payload)}
    </section>

    <section class="panel" id="all-day">
      <div class="section-head">
        <h2>All-Day 75-85c Tier</h2>
        <p>Compatible only</p>
      </div>
      {render_slip_section(all_day_slip, "ALL-DAY 75-85c TIER", "all_day", payload)}
    </section>

    <section class="panel" id="research-edge">
      <div class="section-head">
        <h2>Research Scout Slip</h2>
        <p>Research only</p>
      </div>
      {render_slip_section(research_edge_slip, "RESEARCH SCOUT SLIP", "research_edge", payload)}
    </section>
  </main>
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
        return f"""
        <div class="decision {action_class}">
          <strong>{html.escape(action)}</strong>
          <p>{reason}</p>
          <p>Tradable combos scanned: {pick.get("tradable_combo_count", 0)}</p>
        </div>
        """
    best = candidates[0]
    legs = "".join(render_leg_detail(leg) for leg in best.get("legs", []))
    return f"""
    <div class="decision {action_class}">
      <strong>{html.escape(action)}</strong>
      <p>{reason}</p>
      <div class="prob-grid">
        <span>YES ask <strong>{money(best.get("yes_ask_cents"))}c</strong></span>
        <span>Adjusted probability <strong>{float(best.get("adjusted_probability") or 0) * 100:.2f}%</strong></span>
        <span>Estimated edge <strong>{money(best.get("edge_cents"))}c</strong></span>
        <span>Legs <strong>{best.get("leg_count", 0)}</strong></span>
      </div>
      <h3>{html.escape(best.get("ticker", ""))}</h3>
      <ul>{legs}</ul>
      <button type="button" class="copy" data-title="{html.escape(best.get("title", ""), quote=True)}">Copy bet legs</button>
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
        return f"""
        <div class="slip-card empty">
          <strong>No Slip</strong>
          <p>{html.escape(slip.get("reason", "The engine did not find enough clean legs."))}</p>
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
    auth_db_path = repo_path("data", "evaluation.sqlite")
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
            readiness = build_service_readiness(load_payload(self.data_path))
            self.send_json(readiness, status_code=200 if readiness["status"] == "ready" else 503)
            return
        if path == "/internal/status.json":
            if not self.authorize_request(required_role="admin"):
                return
            self.send_json(build_internal_status(self.auth_db_path))
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
        payload = load_payload(self.data_path)
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
            return LocalAuthStore(os.environ.get("AUTH_DB_PATH") or self.auth_db_path)
        except Exception:
            return None

    @property
    def operator_inbox(self) -> OperatorInbox | None:
        try:
            return OperatorInbox(os.environ.get("OPERATOR_INBOX_DB_PATH") or self.auth_db_path)
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
        body = json.dumps(payload, indent=2).encode("utf-8")
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
  refreshStatus.className = "";
  if (state === "running") {
    refreshButton.disabled = true;
    refreshButton.textContent = "Refreshing…";
    refreshStatus.classList.add("warning");
    refreshStatus.textContent = "Updating";
    return;
  }
  refreshButton.disabled = false;
  refreshButton.textContent = "Refresh";
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
const sectionLinks = [...document.querySelectorAll('.quick-nav a[href^="#"]')];
const linkedSections = sectionLinks
  .map(link => document.querySelector(link.getAttribute("href")))
  .filter(Boolean);
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
liveDataPollTimer = setTimeout(pollLiveDataFreshness, LIVE_DATA_POLL_SECONDS * 1000);
recalc();
"""
