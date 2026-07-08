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
from urllib.parse import parse_qs, urlparse

from .config import repo_path
from .review_packet import (
    SLIP_SOURCES,
    build_all_review_packets,
    build_review_packet,
    render_review_packet_text,
    safe_review_packet_filename,
)
from .research_record import build_research_record
from .source_quality import build_dashboard_quality_gate
from .storage import ResearchStore


REFRESH_COOLDOWN_SECONDS = 60
DEFAULT_KALSHI_RUN_ID = "stage3a_20260703_170707"
DEFAULT_REFRESH_LEDGER_MAX_PAYLOAD_AGE_SECONDS = 1800


def dashboard_auth_enabled(env: dict[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    explicit = str(values.get("DASHBOARD_AUTH_ENABLED", "")).strip().lower()
    return explicit in {"1", "true", "yes", "on"} or bool(values.get("DASHBOARD_AUTH_PASSWORD"))


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
            "api": "/data.json, /refresh-status, /quality.json, /research-record.json, /review-packet.json, /review-packet.txt, POST /refresh",
            "cache": "short-lived file cache for public API responses",
            "rate_limit": f"manual refresh cooldown {REFRESH_COOLDOWN_SECONDS}s plus no-overlap lock",
            "audit": str(audit_path),
            "error_tracking": str(error_path),
            "security": "local/LAN manual dashboard; no automatic trade execution",
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
        stamp = datetime.fromisoformat(str(value))
    except ValueError:
        return html.escape(str(value))
    return stamp.strftime("%b %d, %I:%M %p").replace(" 0", " ").replace(", 0", ", ")


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
            lines.append(f"{index}. {event} — {side} {label_text} (model {probability}, Kalshi {kalshi}, ±{margin}, {evidence_count} sources)")
        else:
            lines.append(f"{index}. {event} — {side} {label_text} ({probability})")
    return "\n".join(lines)


def render_dashboard(payload: dict, refresh_seconds: int = 0) -> str:
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
    refresh_label = f"Auto-refresh: {refresh_seconds // 60} min" if refresh_seconds else "Auto-refresh off"
    refresh_error = payload.get("refresh_error")
    refresh_error_html = (
        f'<p class="subtle strong-note">Last refresh issue: {html.escape(str(refresh_error))}</p>'
        if refresh_error
        else ""
    )
    quality_status = build_quality_status(
        payload,
        repo_path("data", "refresh_audit.jsonl"),
        repo_path("data", "error_events.jsonl"),
    )
    research_record = build_research_record(payload=payload)
    payload_json = json.dumps(payload).replace("</", "<\\/")
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  {refresh_meta}
  <title>Kalshi Slip Engine</title>
  <style>{CSS}</style>
</head>
<body>
  <header class="hero">
    <div class="hero-copy">
      <p class="eyebrow">Live Slip Engine</p>
      <h1>Kalshi Sports Combos</h1>
      <p class="subtle">Fresh scrape. Clean slips. Manual entry only.</p>
      <p class="subtle">Updated {html.escape(display_generated_at)} · {html.escape(refresh_label)}</p>
      {refresh_error_html}
    </div>
    <div class="stat">
      <span>Card Date</span>
      <strong>{html.escape(payload.get("date", ""))}</strong>
    </div>
    <div class="stat">
      <span>80% Legs</span>
      <strong>{primary_slip.get("leg_count", 0)}</strong>
    </div>
    <div class="stat">
      <span>75% Legs</span>
      <strong>{leverage_slip.get("leg_count", 0)}</strong>
    </div>
    <div class="stat">
      <span>All-Day Legs</span>
      <strong>{all_day_slip.get("leg_count", 0)}</strong>
    </div>
    <div class="stat">
      <span>Research Legs</span>
      <strong>{research_edge_slip.get("leg_count", 0)}</strong>
    </div>
    <div class="refresh-box">
      <button id="refresh-slip" type="button">Refresh Slip Now</button>
      <span id="refresh-status">Ready. Re-scrapes odds, schedules, public inputs, and slip math.</span>
    </div>
  </header>

  <nav class="quick-nav" aria-label="Dashboard sections">
    <a href="#map">Slip Map</a>
    <a href="#quality">Quality</a>
    <a href="#record">Record</a>
    <a href="#primary">80% Slip</a>
    <a href="#leverage">75% Slip</a>
    <a href="#all-day">All-Day</a>
    <a href="#research-edge">Research Edge</a>
  </nav>

  <main>
    <section class="panel" id="map">
      <div class="section-head">
        <h2>Slip Map</h2>
        <p>Live slip builds. Left side uses higher leg floors; right side takes more payout variance.</p>
      </div>
      {render_visual_section(payload)}
    </section>

    <section class="panel" id="quality">
      <div class="section-head">
        <h2>Data Quality Gate</h2>
        <p>Freshness, timestamp proof, source health, and metric-contamination guardrails.</p>
      </div>
      {render_quality_panel(quality_status)}
    </section>

    <section class="panel" id="record">
      <div class="section-head">
        <h2>Research Record</h2>
        <p>Settled-only record keeping. Unresolved, rejected, invalid, and duplicate exposure rows cannot inflate the hit-rate view.</p>
      </div>
      {render_research_record_panel(research_record)}
    </section>

    <section class="panel" id="primary">
      <div class="section-head">
        <h2>80% Slip</h2>
        <p>Every listed leg clears the 80% threshold before it enters the combo.</p>
      </div>
      {render_slip_section(primary_slip, "80% SLIP", "primary", payload)}
    </section>

    <section class="panel" id="leverage">
      <div class="section-head">
        <h2>75% Leverage Slip</h2>
        <p>Lower leg threshold. Bigger payout. More variance.</p>
      </div>
      {render_slip_section(leverage_slip, "75% LEVERAGE SLIP", "leverage", payload)}
    </section>

    <section class="panel" id="all-day">
      <div class="section-head">
        <h2>All-Day 75–85% Slip</h2>
        <p>Same-day Kalshi markets across sports, crypto, finance, weather, politics, and anything else closing today.</p>
      </div>
      {render_slip_section(all_day_slip, "ALL-DAY 75–85% SLIP", "all_day", payload)}
    </section>

    <section class="panel" id="research-edge">
      <div class="section-head">
        <h2>Research Edge Slip</h2>
        <p>Hopeful edge model. Uses outside sources when loaded; otherwise runs a market-only scout model with margin-of-error penalties.</p>
      </div>
      {render_slip_section(research_edge_slip, "RESEARCH EDGE SLIP", "research_edge", payload)}
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
    sports_count = len(slip.get("sports") or [])
    max_leg_probability = slip.get("max_leg_probability")
    leg_probability_label = "Leg Range" if max_leg_probability is not None else "Leg Floor"
    leg_probability_value = (
        f"{float(slip.get('min_leg_probability') or 0) * 100:.0f}–{float(max_leg_probability) * 100:.0f}%"
        if max_leg_probability is not None
        else f"{float(slip.get('min_leg_probability') or 0) * 100:.0f}%"
    )
    return f"""
    <div class="slip-card">
      <div class="slip-topline">
        <div>
          <span class="section-kicker">{html.escape(label)}</span>
          <strong>${money(slip.get("estimated_payout_if_right"))}</strong>
          <p>$5 estimated payout if every leg hits</p>
        </div>
        <div class="packet-actions">
          <button type="button" class="copy primary-copy" data-copy="{review_copy_text}">Copy Fast Packet</button>
          <button type="button" class="copy compact-copy" data-copy="{ticker_copy_text}">Copy Tickers + Sides</button>
          <a class="packet-download" href="{packet_href}" download>Text Packet</a>
          <a class="packet-download" href="{packet_json_href}" download>JSON</a>
        </div>
      </div>
      <p class="packet-note">Manual review packet only. No account upload, no order creation, no auto-bet.</p>
      <div class="metric-strip">
        <span><small>{leg_probability_label}</small><strong>{leg_probability_value}</strong></span>
        <span><small>Legs</small><strong>{slip.get("leg_count", 0)}</strong></span>
        <span><small>Sports</small><strong>{sports_count}</strong></span>
        <span><small>Combo Price</small><strong>{money(slip.get("estimated_combo_price_cents"))}c</strong></span>
        <span><small>Combo Chance</small><strong>{float(slip.get("adjusted_probability") or 0) * 100:.2f}%</strong></span>
      </div>
      <div class="slip-groups">{''.join(sections)}</div>
    </div>
    """


def render_slip_leg(leg: dict) -> str:
    label = leg.get("subtitle") or leg.get("title") or leg.get("market_ticker", "")
    event = leg.get("display_event") or leg.get("event_ticker") or ""
    probability = float(leg.get("probability") or 0) * 100.0
    required = float(leg.get("required_probability") or 0) * 100.0
    side = html.escape(leg.get("side", "").upper())
    ask = money(leg.get("ask_cents"))
    if leg.get("research_probability") is not None:
        margin = float(leg.get("margin_of_error") or 0) * 100.0
        kalshi = float(leg.get("kalshi_probability") or 0) * 100.0
        evidence_count = int(leg.get("evidence_count") or 0)
        meta = f"model {probability:.1f}% · Kalshi {kalshi:.1f}% · ±{margin:.1f}% · {evidence_count} sources"
    else:
        meta = f"floor {required:.0f}% · ask {ask}c"
    return (
        f"<li class=\"slip-leg\">"
        f"<div><strong>{html.escape(event)}</strong><span>{side} · {html.escape(label)}</span></div>"
        f"<div class=\"leg-metrics\"><b>{probability:.1f}%</b><small>{meta}</small></div>"
        f"</li>"
    )


def render_visual_section(payload: dict) -> str:
    tiers = [
        ("80% Slip", payload.get("custom_slip") or {}, "#25f4a8"),
        ("75% Leverage", payload.get("leverage_slip") or {}, "#ffd36a"),
        ("All-Day 75–85", payload.get("all_day_slip") or {}, "#6ee7ff"),
        ("Research Edge", payload.get("research_edge_slip") or {}, "#c084fc"),
    ]
    cards = []
    for index, (name, slip, color) in enumerate(tiers):
        is_built = slip.get("action") == "BUILD_SLIP"
        chance = float(slip.get("adjusted_probability") or 0) * 100.0 if is_built else 0.0
        payout = float(slip.get("estimated_payout_if_right") or 0) if is_built else 0.0
        legs = int(slip.get("leg_count") or 0) if is_built else 0
        headline = f"${money(payout)}" if is_built else "No Slip"
        subline = f"{chance:.2f}% combo" if is_built else "needs data"
        cards.append(
            f"""
            <article class="map-card" style="--tier-color:{color};">
              <span>{html.escape(name)}</span>
              <strong>{headline}</strong>
              <div>
                <small>{legs} legs</small>
                <small>{subline}</small>
              </div>
            </article>
            """
        )
    generated_at = payload.get("generated_at") or "pending"
    display_generated_at = display_timestamp(generated_at)
    return f"""
    <div class="slip-map">
      <div class="holo-stage" aria-label="Slip comparison model">
        <div class="holo-orbit orbit-one"></div>
        <div class="holo-orbit orbit-two"></div>
        <div class="holo-core">
          <span>SLIP</span>
          <strong>MAP</strong>
        </div>
        <div class="holo-chip chip-primary">80%</div>
        <div class="holo-chip chip-leverage">75%</div>
        <div class="holo-chip chip-all-day">ALL</div>
        <div class="holo-chip chip-research">EDGE</div>
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


def render_quality_panel(status: dict) -> str:
    gate = status.get("source_quality_gate") or {}
    slip_counts = gate.get("slip_counts") or status.get("slip_counts") or {}
    warnings = status.get("warnings") or []
    warning_items = "".join(f"<li>{html.escape(str(item))}</li>" for item in warnings) or "<li>No active dashboard warnings.</li>"
    metric_checks = status.get("metric_contamination_checks") or {}
    metric_items = "".join(
        f"<li><strong>{html.escape(str(key))}</strong>: {html.escape(str(value))}</li>"
        for key, value in metric_checks.items()
    )
    status_label = str(status.get("status") or gate.get("status") or "UNKNOWN")
    decision_class = "good" if status_label == "OK" else "warning"
    primary = int(slip_counts.get("primary") or 0)
    leverage = int(slip_counts.get("leverage") or 0)
    all_day = int(slip_counts.get("all_day") or 0)
    research_edge = int(slip_counts.get("research_edge") or 0)
    return f"""
    <div class="decision {decision_class}">
      <strong>{html.escape(status_label)}</strong>
      <p>Quality score {html.escape(str(gate.get("score", "n/a")))} Â· data age {html.escape(str(status.get("data_age_seconds")))}s Â· audit events {html.escape(str(status.get("audit_events", 0)))}</p>
      <div class="metric-strip">
        <span><small>Primary</small><strong>{primary}</strong></span>
        <span><small>Leverage</small><strong>{leverage}</strong></span>
        <span><small>All-Day</small><strong>{all_day}</strong></span>
        <span><small>Research</small><strong>{research_edge}</strong></span>
      </div>
      <h3>Warnings</h3>
      <ul>{warning_items}</ul>
      <h3>Metric Guardrails</h3>
      <ul>{metric_items}</ul>
      <p class="fine-print">Local research only. Connector failures and blocked sources do not enter prediction metrics.</p>
    </div>
    """


def render_research_record_panel(record: dict) -> str:
    tracks = record.get("tracks") or []
    track_cards = "".join(render_research_record_track(track) for track in tracks) or """
      <div class="decision warning">
        <strong>No record yet</strong>
        <p>No evaluation rows are available yet. Keep collecting and settling before showing hit-rate metrics.</p>
      </div>
    """
    rationale_rows = "".join(render_slip_rationale_row(row) for row in record.get("current_slip_rationale") or [])
    if not rationale_rows:
        rationale_rows = "<li>No current slip rationale available yet.</li>"
    status_label = str(record.get("status") or "WATCH")
    decision_class = "good" if status_label == "OK" else "warning"
    return f"""
    <div class="decision {decision_class}">
      <strong>{html.escape(status_label)}</strong>
      <p>{html.escape(str(record.get("metric_policy", "")))}</p>
      <div class="record-grid">{track_cards}</div>
      <h3>Why Today's Slips Exist</h3>
      <ul>{rationale_rows}</ul>
      <p class="fine-print">Next: {html.escape(str(record.get("next_action") or "keep collecting and settling"))}</p>
    </div>
    """


def render_research_record_track(track: dict) -> str:
    hit_rate = track.get("observed_hit_rate")
    raw_hit_rate = track.get("observed_hit_rate_raw")
    if hit_rate is not None:
        hit_rate_text = f"{float(hit_rate) * 100:.2f}%"
    elif raw_hit_rate is not None:
        hit_rate_text = f"withheld ({float(raw_hit_rate) * 100:.2f}% raw)"
    else:
        hit_rate_text = "unavailable"
    top_reasons = track.get("rejection_reasons") or {}
    reason_text = ", ".join(
        f"{html.escape(str(reason))}: {html.escape(str(count))}"
        for reason, count in list(top_reasons.items())[:3]
    ) or "none"
    return f"""
      <article class="card">
        <div class="card-head">
          <h3>{html.escape(str(track.get("bot_name", "")))}</h3>
          <span class="pill good">research-only</span>
        </div>
        <div class="metric-strip">
          <span><small>Valid</small><strong>{int(track.get("valid_rows") or 0)}</strong></span>
          <span><small>Settled</small><strong>{int(track.get("settled_rows") or 0)}</strong></span>
          <span><small>Deduped</small><strong>{int(track.get("deduped_settled_exposures") or 0)}</strong></span>
          <span><small>Unresolved</small><strong>{int(track.get("unresolved_rows") or 0)}</strong></span>
        </div>
        <div class="prob-grid">
          <span>Wins <strong>{int(track.get("wins") or 0)}</strong></span>
          <span>Losses <strong>{int(track.get("losses") or 0)}</strong></span>
          <span>Push/no-edge/void <strong>{int(track.get("push_no_edge_or_void") or 0)}</strong></span>
          <span>Rejected <strong>{int(track.get("rejected_rows") or 0)}</strong></span>
        </div>
        <p><strong>Hit rate:</strong> {html.escape(hit_rate_text)} · {html.escape(str(track.get("hit_rate_status", "")))}</p>
        <p><strong>Top rejections:</strong> {reason_text}</p>
        <p class="fine-print">Dedupe: {html.escape(str(track.get("dedupe_policy", "")))}. {html.escape(str(track.get("metric_guardrail", "")))}</p>
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
    data_path = repo_path("data", "today_paper_view.json")
    audit_path = repo_path("data", "refresh_audit.jsonl")
    error_path = repo_path("data", "error_events.jsonl")
    refresh_seconds = 0
    refresh_config: dict = {}
    refresh_lock = threading.Lock()
    last_manual_refresh_at = 0.0
    refresh_status = {
        "state": "idle",
        "message": "Ready. Re-scrapes odds, schedules, public inputs, and slip math.",
    }

    def do_GET(self) -> None:
        if not self.authorize_request():
            return
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        if path in {"/", "/index.html"}:
            body = render_dashboard(load_payload(self.data_path), self.refresh_seconds).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/data.json":
            body = json.dumps(load_payload(self.data_path), indent=2).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path == "/review-packets.json":
            self.send_json(build_all_review_packets(load_payload(self.data_path)))
            return
        if path == "/review-packet.json":
            slip_key = (query.get("slip") or ["primary"])[0]
            try:
                packet = build_review_packet(load_payload(self.data_path), slip_key)
            except ValueError as exc:
                self.send_json({"error": str(exc), "valid_slips": sorted(SLIP_SOURCES)}, status_code=400)
                return
            self.send_json(packet)
            return
        if path == "/review-packet.txt":
            slip_key = (query.get("slip") or ["primary"])[0]
            try:
                packet = build_review_packet(load_payload(self.data_path), slip_key)
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
            self.send_json(build_quality_status(load_payload(self.data_path), self.audit_path, self.error_path))
            return
        if path == "/research-record.json":
            self.send_json(build_research_record(payload=load_payload(self.data_path)))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        if not self.authorize_request():
            return
        path = urlparse(self.path).path
        if path == "/refresh":
            status = self.run_refresh(reason="manual", async_run=True)
            status_code = 202 if status.get("accepted") else int(status.get("status_code", 409))
            self.send_json(status, status_code=status_code)
            return
        self.send_error(404)

    def authorize_request(self) -> bool:
        if valid_dashboard_auth(self.headers.get("Authorization")):
            return True
        body = b"Authentication required."
        self.send_response(401)
        self.send_header("WWW-Authenticate", 'Basic realm="HawkNetic Research Dashboard"')
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        return False

    def send_json(self, payload: dict, status_code: int = 200) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
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
                result = refresh_payload(**cls.refresh_config)
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
                    "error": result.get("error", ""),
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
        payload["refresh_error"] = error
        payload["refresh_failed_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        write_json_atomic(data_path, payload)
        print(f"Refresh failed: {error}")
        return {
            "ok": False,
            "message": "Refresh failed. Keeping the last loaded slip visible.",
            "error": error,
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
    if PaperHandler.refresh_seconds:
        PaperHandler.run_refresh(reason="startup", async_run=True)
        start_refresh_thread(PaperHandler.refresh_seconds)
    print(f"Paper view running at http://{host}:{port}")
    if PaperHandler.refresh_seconds:
        print(f"Auto-refreshing every {PaperHandler.refresh_seconds} seconds.")
    server.serve_forever()


CSS = r"""
:root {
  color-scheme: dark;
  --bg: #0c0f12;
  --panel: #151a1f;
  --panel-2: #1d242b;
  --text: #edf3f1;
  --muted: #9aa8a4;
  --line: #2a343d;
  --accent: #23c483;
  --warn: #f3b34c;
  --bad: #ff6b6b;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--bg);
  color: var(--text);
  font-family: Arial, Helvetica, sans-serif;
}
header {
  display: grid;
  grid-template-columns: 1fr repeat(3, minmax(110px, 150px));
  gap: 12px;
  align-items: end;
  padding: 22px;
  border-bottom: 1px solid var(--line);
}
h1, h2, h3, p { margin: 0; }
h1 { font-size: 28px; }
h2 { font-size: 20px; }
h3 { font-size: 13px; overflow-wrap: anywhere; }
main { display: grid; gap: 16px; padding: 16px; }
.eyebrow { color: var(--accent); font-size: 12px; text-transform: uppercase; letter-spacing: .08em; margin-bottom: 5px; }
.subtle, .section-head p { color: var(--muted); margin-top: 6px; line-height: 1.4; }
.strong-note { color: var(--warn); }
.stat, .panel, .card {
  border: 1px solid var(--line);
  background: var(--panel);
  border-radius: 8px;
}
.stat { padding: 12px; }
.stat span { display: block; color: var(--muted); font-size: 12px; }
.stat strong { display: block; margin-top: 4px; font-size: 18px; }
.panel { padding: 16px; }
.decision {
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 14px;
  background: var(--panel-2);
}
.decision > strong { display: block; font-size: 24px; margin-bottom: 8px; }
.decision.good > strong { color: var(--accent); }
.decision.warning > strong { color: var(--warn); }
.section-head { display: flex; justify-content: space-between; gap: 12px; align-items: start; margin-bottom: 12px; }
.visual-wrap {
  display: grid;
  grid-template-columns: minmax(260px, 1fr) minmax(220px, 320px);
  gap: 14px;
  align-items: stretch;
}
.risk-space {
  position: relative;
  min-height: 300px;
  border: 1px solid var(--line);
  border-radius: 12px;
  background:
    linear-gradient(90deg, rgb(255 255 255 / 5%) 1px, transparent 1px),
    linear-gradient(0deg, rgb(255 255 255 / 5%) 1px, transparent 1px),
    radial-gradient(circle at 80% 20%, rgb(35 196 131 / 20%), transparent 30%),
    #10161b;
  background-size: 34px 34px, 34px 34px, 100% 100%, 100% 100%;
  overflow: visible;
  perspective: 900px;
  transform-style: preserve-3d;
}
.risk-space::before {
  content: "";
  position: absolute;
  inset: 48px 28px 42px 42px;
  border-left: 2px solid rgb(35 196 131 / 45%);
  border-bottom: 2px solid rgb(35 196 131 / 45%);
  transform: rotateX(58deg) rotateZ(-35deg);
  transform-origin: center;
}
.axis {
  position: absolute;
  color: var(--muted);
  font-size: 12px;
  letter-spacing: .04em;
  text-transform: uppercase;
}
.x-axis { right: 18px; bottom: 18px; }
.y-axis { left: 14px; top: 18px; }
.z-axis { right: 20px; top: 18px; color: var(--warn); }
.risk-card {
  position: absolute;
  left: var(--x);
  bottom: var(--y);
  width: min(210px, 42vw);
  border: 1px solid color-mix(in srgb, var(--tier-color) 70%, var(--line));
  border-radius: 12px;
  padding: 12px;
  background: linear-gradient(145deg, color-mix(in srgb, var(--tier-color) 18%, #11171b), #11171b);
  box-shadow: 0 18px 35px rgb(0 0 0 / 45%), 0 0 28px color-mix(in srgb, var(--tier-color) 22%, transparent);
  transform: translate(-50%, 40%) translateZ(var(--z)) rotateX(0deg);
  transform-style: preserve-3d;
}
.risk-card strong { display: block; color: var(--tier-color); font-size: 16px; margin-bottom: 6px; }
.risk-card span { display: block; color: var(--text); font-size: 13px; line-height: 1.35; }
.time-ribbon {
  border: 1px solid var(--line);
  border-radius: 12px;
  background: linear-gradient(180deg, #151d22, #101419);
  padding: 14px;
}
.time-ribbon span { display: block; color: var(--accent); text-transform: uppercase; font-size: 12px; letter-spacing: .08em; }
.time-ribbon strong { display: block; margin-top: 8px; font-size: 18px; overflow-wrap: anywhere; }
.time-ribbon em { display: block; margin-top: 10px; color: var(--muted); font-style: normal; line-height: 1.4; }
.builder-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(160px, 1fr)) repeat(2, max-content);
  gap: 10px;
  align-items: end;
}
label { color: var(--muted); font-size: 12px; }
input {
  width: 100%;
  margin-top: 6px;
  border: 1px solid var(--line);
  background: #0f1418;
  color: var(--text);
  border-radius: 6px;
  padding: 10px;
}
button {
  border: 0;
  border-radius: 6px;
  background: var(--accent);
  color: #06100c;
  padding: 10px 12px;
  font-weight: 700;
  cursor: pointer;
}
button.ghost, button.copy { background: var(--panel-2); color: var(--text); border: 1px solid var(--line); }
#legs { display: grid; gap: 8px; margin-top: 12px; }
.leg-row {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 36px;
  gap: 8px;
  align-items: end;
}
.result-bar {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  margin-top: 14px;
}
.result-bar div {
  background: var(--panel-2);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 12px;
}
.result-bar span { display: block; color: var(--muted); font-size: 12px; }
.result-bar strong { display: block; margin-top: 4px; font-size: 20px; }
.cards, .record-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 12px; }
.card { padding: 14px; background: var(--panel-2); }
.card-head { display: flex; justify-content: space-between; gap: 8px; align-items: start; }
.card ul { padding-left: 18px; color: var(--text); line-height: 1.45; }
.quote-grid, .prob-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; margin: 12px 0; }
.quote-grid span, .prob-grid span {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--muted);
  background: #11171b;
  border: 1px solid var(--line);
  border-radius: 6px;
  padding: 8px;
}
.quote-grid strong, .prob-grid strong { color: var(--text); }
.quote-grid .warning { color: var(--warn); }
.leg-meta { display: block; color: var(--muted); font-size: 12px; margin-top: 3px; }
.fine-print { color: var(--muted); font-size: 12px; line-height: 1.35; }
.pill {
  display: inline-block;
  border: 1px solid var(--line);
  border-radius: 999px;
  color: var(--muted);
  padding: 3px 8px;
  font-size: 12px;
  white-space: nowrap;
}
.pill.good { color: var(--accent); }
.pill.warning { color: var(--warn); }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
th, td { border-bottom: 1px solid var(--line); text-align: left; padding: 10px; vertical-align: top; }
th { color: var(--muted); font-size: 12px; text-transform: uppercase; }
@media (max-width: 800px) {
  header, .builder-grid, .result-bar, .leg-row, .visual-wrap { grid-template-columns: 1fr; }
  .risk-space { min-height: 260px; overflow: hidden; }
  .risk-card { width: 190px; }
}

/* Cinematic free-tier frontend pass: no external assets, no paid connector dependency. */
:root {
  --bg: #030607;
  --panel: rgb(9 18 16 / 82%);
  --panel-2: rgb(13 28 24 / 86%);
  --text: #f1fbf7;
  --muted: #9db5ad;
  --line: rgb(159 255 217 / 14%);
  --accent: #25f4a8;
  --accent-2: #6ee7ff;
  --warn: #ffd36a;
  --bad: #ff677d;
  --glass: rgb(255 255 255 / 6%);
  --shadow: 0 26px 80px rgb(0 0 0 / 42%);
}
html { scroll-behavior: smooth; }
body {
  min-height: 100vh;
  background:
    radial-gradient(circle at 15% -5%, rgb(37 244 168 / 22%), transparent 34rem),
    radial-gradient(circle at 95% 10%, rgb(110 231 255 / 16%), transparent 34rem),
    radial-gradient(circle at 50% 100%, rgb(255 211 106 / 9%), transparent 34rem),
    linear-gradient(180deg, #030607 0%, #07100d 52%, #020403 100%);
  font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", Arial, sans-serif;
}
body::before {
  content: "";
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgb(255 255 255 / 3%) 1px, transparent 1px),
    linear-gradient(90deg, rgb(255 255 255 / 3%) 1px, transparent 1px);
  background-size: 48px 48px;
  mask-image: linear-gradient(180deg, rgb(0 0 0 / 65%), transparent 76%);
}
.hero, .quick-nav, main {
  width: min(1440px, calc(100% - 28px));
  margin-left: auto;
  margin-right: auto;
}
.hero {
  grid-template-columns: minmax(320px, 1fr) repeat(3, minmax(110px, 150px)) minmax(190px, 240px);
  align-items: stretch;
  position: relative;
  overflow: hidden;
  margin-top: 14px;
  padding: clamp(18px, 3vw, 34px);
  border: 1px solid rgb(159 255 217 / 18%);
  border-radius: 28px;
  background:
    linear-gradient(135deg, rgb(255 255 255 / 10%), transparent 42%),
    linear-gradient(180deg, rgb(12 27 23 / 90%), rgb(5 12 10 / 90%));
  box-shadow: var(--shadow), inset 0 1px 0 rgb(255 255 255 / 12%);
}
.hero::after {
  content: "";
  position: absolute;
  right: -12%;
  top: -42%;
  width: 42rem;
  height: 42rem;
  border-radius: 50%;
  background: radial-gradient(circle, rgb(37 244 168 / 22%), transparent 62%);
  filter: blur(4px);
}
.hero > * { position: relative; z-index: 1; }
h1 {
  max-width: 820px;
  font-size: clamp(34px, 7vw, 82px);
  line-height: .9;
  letter-spacing: -.065em;
}
h2 { font-size: clamp(20px, 2vw, 28px); letter-spacing: -.025em; }
h3 { font-size: 14px; line-height: 1.2; }
.eyebrow {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--accent);
  font-weight: 800;
}
.eyebrow::before {
  content: "";
  width: 8px;
  height: 8px;
  border-radius: 999px;
  background: var(--accent);
  box-shadow: 0 0 18px var(--accent);
}
.subtle, .section-head p { max-width: 860px; }
.strong-note {
  display: inline-block;
  color: #0c120f;
  background: linear-gradient(90deg, var(--warn), #fff2bc);
  border-radius: 999px;
  padding: 5px 10px;
  font-weight: 800;
}
.stat, .panel, .card, .decision, .result-bar div, .quote-grid span, .prob-grid span, .time-ribbon {
  border-color: rgb(159 255 217 / 16%);
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 8%);
  backdrop-filter: blur(18px);
}
.stat {
  min-height: 88px;
  border-radius: 20px;
  background: linear-gradient(180deg, rgb(255 255 255 / 9%), rgb(255 255 255 / 3%));
}
.stat strong { color: var(--accent); font-size: 24px; letter-spacing: -.03em; }
.refresh-box {
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 9px;
  min-height: 88px;
  padding: 12px;
  border: 1px solid rgb(159 255 217 / 16%);
  border-radius: 20px;
  background:
    radial-gradient(circle at 100% 0%, rgb(37 244 168 / 18%), transparent 12rem),
    linear-gradient(180deg, rgb(255 255 255 / 9%), rgb(255 255 255 / 3%));
  box-shadow: inset 0 1px 0 rgb(255 255 255 / 8%);
  backdrop-filter: blur(18px);
}
#refresh-slip {
  width: 100%;
  min-height: 44px;
}
#refresh-status {
  color: var(--muted);
  font-size: 12px;
  line-height: 1.3;
}
#refresh-status.good { color: var(--accent); }
#refresh-status.warning { color: var(--warn); }
#refresh-status.bad { color: var(--bad); }
.quick-nav {
  position: sticky;
  top: 8px;
  z-index: 10;
  display: flex;
  gap: 8px;
  padding: 10px;
  margin-top: 12px;
  overflow-x: auto;
  border: 1px solid rgb(159 255 217 / 13%);
  border-radius: 999px;
  background: rgb(4 11 9 / 78%);
  box-shadow: 0 18px 45px rgb(0 0 0 / 28%);
  backdrop-filter: blur(22px);
}
.quick-nav a {
  flex: 0 0 auto;
  color: var(--text);
  text-decoration: none;
  border: 1px solid rgb(255 255 255 / 10%);
  border-radius: 999px;
  padding: 9px 13px;
  font-size: 13px;
  font-weight: 800;
  background: rgb(255 255 255 / 5%);
}
.quick-nav a:hover { border-color: var(--accent); color: var(--accent); }
main { gap: 18px; padding: 18px 0 32px; }
.panel {
  position: relative;
  overflow: hidden;
  border-radius: 26px;
  padding: clamp(16px, 2.2vw, 26px);
  background:
    linear-gradient(135deg, rgb(255 255 255 / 8%), transparent 34%),
    linear-gradient(180deg, rgb(9 21 18 / 88%), rgb(5 11 10 / 88%));
  box-shadow: var(--shadow);
}
.panel::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background: radial-gradient(circle at 94% 0%, rgb(37 244 168 / 10%), transparent 24rem);
}
.panel > * { position: relative; z-index: 1; }
.section-head {
  padding-bottom: 12px;
  border-bottom: 1px solid rgb(159 255 217 / 12%);
}
.decision {
  border-radius: 22px;
  background:
    linear-gradient(135deg, rgb(37 244 168 / 10%), transparent 40%),
    rgb(10 20 18 / 86%);
}
.decision > strong { font-size: clamp(24px, 4vw, 42px); letter-spacing: -.05em; }
.decision.good { border-color: rgb(37 244 168 / 34%); }
.decision.warning { border-color: rgb(255 211 106 / 34%); }
.visual-wrap { grid-template-columns: minmax(320px, 1fr) minmax(260px, 360px); }
.risk-space {
  min-height: 420px;
  border-radius: 26px;
  border-color: rgb(110 231 255 / 18%);
  background:
    radial-gradient(circle at 20% 20%, rgb(37 244 168 / 18%), transparent 18rem),
    radial-gradient(circle at 84% 24%, rgb(110 231 255 / 15%), transparent 20rem),
    linear-gradient(90deg, rgb(255 255 255 / 5%) 1px, transparent 1px),
    linear-gradient(0deg, rgb(255 255 255 / 5%) 1px, transparent 1px),
    #06100e;
  background-size: auto, auto, 42px 42px, 42px 42px, auto;
  box-shadow: inset 0 0 80px rgb(0 0 0 / 40%);
}
.risk-space::before {
  border-left-color: rgb(37 244 168 / 54%);
  border-bottom-color: rgb(110 231 255 / 42%);
  filter: drop-shadow(0 0 20px rgb(37 244 168 / 22%));
}
.axis {
  padding: 5px 8px;
  border: 1px solid rgb(255 255 255 / 8%);
  border-radius: 999px;
  background: rgb(0 0 0 / 24%);
}
.risk-card {
  border-radius: 18px;
  background:
    linear-gradient(135deg, color-mix(in srgb, var(--tier-color) 22%, transparent), transparent 55%),
    rgb(7 15 13 / 92%);
  box-shadow: 0 28px 70px rgb(0 0 0 / 52%), 0 0 44px color-mix(in srgb, var(--tier-color) 28%, transparent);
}
.risk-card strong { font-size: 18px; }
.time-ribbon {
  border-radius: 24px;
  background:
    radial-gradient(circle at 100% 0%, rgb(255 211 106 / 16%), transparent 16rem),
    rgb(10 21 18 / 88%);
}
.time-ribbon strong { font-size: 22px; letter-spacing: -.035em; }
.builder-grid {
  grid-template-columns: repeat(2, minmax(180px, 1fr)) repeat(2, max-content);
  padding: 14px;
  border: 1px solid rgb(159 255 217 / 12%);
  border-radius: 22px;
  background: rgb(255 255 255 / 4%);
}
label { color: #b7c9c3; font-weight: 750; }
input {
  border-radius: 14px;
  border-color: rgb(159 255 217 / 16%);
  background: rgb(2 7 6 / 72%);
  outline: none;
}
input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgb(37 244 168 / 14%);
}
button {
  border-radius: 14px;
  background: linear-gradient(135deg, var(--accent), #83ffd5);
  box-shadow: 0 12px 28px rgb(37 244 168 / 18%);
}
button:hover { transform: translateY(-1px); }
button:disabled {
  cursor: wait;
  opacity: .68;
  transform: none;
}
button.ghost, button.copy {
  background: rgb(255 255 255 / 7%);
  color: var(--text);
}
.leg-row {
  padding: 10px;
  border: 1px solid rgb(159 255 217 / 10%);
  border-radius: 18px;
  background: rgb(255 255 255 / 4%);
}
.result-bar div { border-radius: 18px; background: rgb(255 255 255 / 6%); }
.result-bar strong { color: var(--accent); letter-spacing: -.03em; }
.cards, .record-grid { grid-template-columns: repeat(auto-fit, minmax(min(100%, 360px), 1fr)); gap: 14px; }
.card {
  border-radius: 22px;
  padding: 16px;
  background:
    linear-gradient(135deg, rgb(255 255 255 / 7%), transparent 36%),
    rgb(10 21 18 / 86%);
}
.card:hover {
  border-color: rgb(37 244 168 / 30%);
  transform: translateY(-2px);
}
.quote-grid span, .prob-grid span {
  border-radius: 14px;
  background: rgb(2 8 7 / 62%);
}
.quote-grid strong, .prob-grid strong { color: var(--accent-2); }
.leg-meta { color: #8fa69e; line-height: 1.35; }
.fine-print { color: #91aaa2; }
.pill {
  border-color: rgb(255 255 255 / 13%);
  background: rgb(255 255 255 / 6%);
  font-weight: 800;
}
.pill.good {
  border-color: rgb(37 244 168 / 32%);
  color: var(--accent);
}
.pill.warning {
  border-color: rgb(255 211 106 / 32%);
  color: var(--warn);
}
.table-wrap {
  border: 1px solid rgb(159 255 217 / 12%);
  border-radius: 20px;
  overflow: auto;
}
table { min-width: 720px; }
th {
  background: rgb(255 255 255 / 5%);
  color: #b8ccc5;
}
td { color: #dbe8e4; }
@media (prefers-reduced-motion: no-preference) {
  .panel, .card, button, .quick-nav a { transition: transform .18s ease, border-color .18s ease, color .18s ease; }
}
@media (max-width: 900px) {
  .hero, .quick-nav, main { width: min(100% - 18px, 1440px); }
  .hero { grid-template-columns: 1fr; border-radius: 22px; }
  .section-head { display: block; }
  .quick-nav { border-radius: 18px; }
  .builder-grid, .result-bar, .leg-row, .visual-wrap { grid-template-columns: 1fr; }
  .risk-space { min-height: 320px; overflow: hidden; }
  .risk-card { width: min(230px, 58vw); }
}

/* Product UI pass: only show the slip map and copy-ready slips. */
body {
  background:
    radial-gradient(circle at 16% -10%, rgb(37 244 168 / 18%), transparent 30rem),
    radial-gradient(circle at 88% 0%, rgb(110 231 255 / 12%), transparent 32rem),
    linear-gradient(180deg, #020504 0%, #07100e 54%, #020403 100%);
}
.hero {
  grid-template-columns: minmax(340px, 1fr) repeat(5, minmax(96px, 132px)) minmax(210px, 260px);
  gap: 10px;
  border-radius: 24px;
  border-color: rgb(255 255 255 / 8%);
  background: linear-gradient(135deg, rgb(255 255 255 / 9%), rgb(255 255 255 / 3%));
}
.hero-copy { align-self: center; }
h1 { font-size: clamp(38px, 6vw, 74px); }
.subtle { color: #adc0ba; }
.strong-note {
  border-radius: 12px;
  color: var(--warn);
  background: rgb(255 211 106 / 10%);
  border: 1px solid rgb(255 211 106 / 18%);
}
.stat, .refresh-box {
  border-color: rgb(255 255 255 / 8%);
  background: rgb(255 255 255 / 5%);
}
.stat span, #refresh-status { color: #92a8a0; }
.stat strong { font-size: 26px; color: #f6fffb; }
.quick-nav {
  width: fit-content;
  max-width: calc(100% - 28px);
  border-radius: 16px;
  border-color: rgb(255 255 255 / 8%);
  background: rgb(2 8 7 / 78%);
}
.quick-nav a {
  border: 0;
  background: transparent;
  color: #b9cbc5;
  padding: 9px 14px;
}
.quick-nav a:hover {
  background: rgb(37 244 168 / 12%);
  color: var(--accent);
}
main {
  grid-template-columns: 1fr;
  gap: 16px;
}
.panel {
  border-radius: 24px;
  border-color: rgb(255 255 255 / 8%);
  background: linear-gradient(180deg, rgb(255 255 255 / 6%), rgb(255 255 255 / 3%));
}
.section-head {
  align-items: end;
  border-bottom-color: rgb(255 255 255 / 8%);
}
.section-head p {
  max-width: 560px;
  text-align: right;
  color: #93aaa2;
}
.slip-map {
  display: grid;
  grid-template-columns: minmax(300px, 460px) 1fr;
  gap: 16px;
  align-items: stretch;
}
.holo-stage {
  position: relative;
  min-height: 280px;
  overflow: hidden;
  border: 1px solid rgb(255 255 255 / 8%);
  border-radius: 24px;
  background:
    radial-gradient(circle at 50% 42%, rgb(37 244 168 / 24%), transparent 9rem),
    linear-gradient(180deg, rgb(255 255 255 / 7%), rgb(255 255 255 / 3%));
}
.holo-stage::before {
  content: "";
  position: absolute;
  inset: 48px 42px 36px;
  border-radius: 50%;
  border: 1px solid rgb(110 231 255 / 22%);
  transform: perspective(560px) rotateX(64deg);
  box-shadow: 0 0 40px rgb(37 244 168 / 18%), inset 0 0 34px rgb(110 231 255 / 10%);
}
.holo-stage::after {
  content: "";
  position: absolute;
  left: 12%;
  right: 12%;
  bottom: 34px;
  height: 1px;
  background: linear-gradient(90deg, transparent, rgb(37 244 168 / 60%), transparent);
}
.holo-orbit {
  position: absolute;
  left: 50%;
  top: 50%;
  border: 1px solid rgb(255 255 255 / 16%);
  border-radius: 50%;
  transform: translate(-50%, -50%) rotateX(64deg) rotateZ(-18deg);
}
.orbit-one { width: 270px; height: 112px; }
.orbit-two { width: 190px; height: 78px; transform: translate(-50%, -50%) rotateX(64deg) rotateZ(24deg); }
.holo-core {
  position: absolute;
  left: 50%;
  top: 46%;
  display: grid;
  place-items: center;
  width: 118px;
  height: 118px;
  border-radius: 32px;
  border: 1px solid rgb(37 244 168 / 28%);
  background: linear-gradient(145deg, rgb(37 244 168 / 22%), rgb(110 231 255 / 10%));
  box-shadow: 0 24px 70px rgb(37 244 168 / 20%);
  transform: translate(-50%, -50%) rotateX(8deg) rotateZ(-8deg);
}
.holo-core span { color: #9db5ad; font-size: 11px; font-weight: 900; letter-spacing: .16em; }
.holo-core strong { margin-top: -22px; font-size: 34px; letter-spacing: -.08em; }
.holo-chip {
  position: absolute;
  min-width: 68px;
  border-radius: 999px;
  padding: 8px 12px;
  text-align: center;
  font-weight: 950;
  background: rgb(2 8 7 / 72%);
  border: 1px solid rgb(255 255 255 / 12%);
}
.chip-primary { left: 18%; top: 24%; color: var(--accent); }
.chip-leverage { right: 18%; bottom: 23%; color: var(--warn); }
.chip-all-day { right: 16%; top: 24%; color: var(--accent-2); }
.chip-research { left: 14%; bottom: 22%; color: #c084fc; }
.map-panel {
  display: grid;
  grid-template-rows: 1fr auto;
  gap: 12px;
}
.map-cards {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 12px;
}
.map-card {
  min-height: 188px;
  display: grid;
  align-content: space-between;
  border: 1px solid color-mix(in srgb, var(--tier-color) 28%, rgb(255 255 255 / 8%));
  border-radius: 24px;
  padding: 18px;
  background:
    radial-gradient(circle at 100% 0%, color-mix(in srgb, var(--tier-color) 18%, transparent), transparent 13rem),
    rgb(255 255 255 / 5%);
}
.map-card > span {
  color: var(--tier-color);
  font-size: 13px;
  font-weight: 950;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.map-card > strong {
  font-size: clamp(38px, 6vw, 72px);
  line-height: .88;
  letter-spacing: -.075em;
}
.map-card div {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  color: #a9bcb6;
}
.update-line {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  border: 1px solid rgb(255 255 255 / 8%);
  border-radius: 18px;
  padding: 12px 14px;
  background: rgb(255 255 255 / 4%);
}
.update-line span { color: #91aaa2; }
.update-line strong {
  color: #eef8f4;
  font-size: 13px;
  overflow-wrap: anywhere;
  text-align: right;
}
.slip-card {
  border: 1px solid rgb(255 255 255 / 8%);
  border-radius: 24px;
  padding: 16px;
  background: rgb(255 255 255 / 4%);
}
.slip-card.empty strong {
  display: block;
  color: var(--warn);
  font-size: 30px;
}
.slip-topline {
  display: grid;
  grid-template-columns: 1fr max-content;
  gap: 14px;
  align-items: center;
}
.section-kicker {
  display: block;
  color: var(--accent);
  font-size: 12px;
  font-weight: 950;
  letter-spacing: .14em;
}
.slip-topline strong {
  display: block;
  margin-top: 5px;
  font-size: clamp(46px, 8vw, 84px);
  line-height: .88;
  letter-spacing: -.075em;
}
.slip-topline p { color: #91aaa2; margin-top: 8px; }
.primary-copy {
  min-width: 134px;
  min-height: 52px;
}
.packet-actions {
  display: grid;
  grid-template-columns: repeat(2, minmax(130px, 1fr));
  gap: 8px;
  min-width: min(100%, 340px);
}
.packet-actions button,
.packet-download {
  min-height: 44px;
  display: grid;
  place-items: center;
  border-radius: 14px;
  font-size: 13px;
  font-weight: 850;
  text-align: center;
  text-decoration: none;
}
.compact-copy,
.packet-download {
  border: 1px solid rgb(255 255 255 / 10%);
  background: rgb(255 255 255 / 7%);
  color: var(--text);
  box-shadow: none;
}
.packet-download:hover {
  border-color: var(--accent);
  color: var(--accent);
  transform: translateY(-1px);
}
.packet-note {
  margin: 10px 0 0;
  color: #9cb2ab;
  font-size: 12px;
}
.metric-strip {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 8px;
  margin: 16px 0;
}
.metric-strip span {
  border: 1px solid rgb(255 255 255 / 8%);
  border-radius: 16px;
  padding: 11px;
  background: rgb(2 8 7 / 38%);
}
.metric-strip small {
  display: block;
  color: #81978f;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: .08em;
}
.metric-strip strong {
  display: block;
  margin-top: 5px;
  font-size: 22px;
  letter-spacing: -.035em;
}
.slip-groups {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 420px), 1fr));
  gap: 12px;
}
.league-block {
  border: 1px solid rgb(255 255 255 / 8%);
  border-radius: 20px;
  padding: 12px;
  background: rgb(2 8 7 / 36%);
}
.league-title {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: center;
  margin-bottom: 10px;
}
.league-title h3 {
  font-size: 15px;
  color: #f1fbf7;
}
.league-title span {
  color: #8ca39b;
  font-size: 12px;
}
.slip-list {
  display: grid;
  gap: 8px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.slip-leg {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  align-items: center;
  border-radius: 14px;
  padding: 10px;
  background: rgb(255 255 255 / 4%);
}
.slip-leg strong {
  display: block;
  font-size: 14px;
  color: #f2fbf8;
}
.slip-leg span {
  display: block;
  margin-top: 4px;
  color: #a4b8b1;
  font-size: 13px;
  line-height: 1.3;
}
.leg-metrics {
  min-width: 88px;
  text-align: right;
}
.leg-metrics b {
  display: block;
  color: var(--accent);
  font-size: 18px;
}
.leg-metrics small {
  display: block;
  color: #849a92;
  font-size: 11px;
  line-height: 1.25;
}
@media (max-width: 1050px) {
  .hero { grid-template-columns: repeat(3, minmax(0, 1fr)); }
  .hero-copy { grid-column: 1 / -1; }
  .refresh-box { grid-column: 1 / -1; }
  .slip-map, .slip-topline { grid-template-columns: 1fr; }
  .map-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .map-card { min-height: 154px; }
  .section-head p { text-align: left; }
  .metric-strip { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .holo-stage { min-height: 220px; }
}
@media (max-width: 620px) {
  .hero, .map-cards { grid-template-columns: 1fr; }
  .hero-copy, .refresh-box { grid-column: auto; }
  .metric-strip { grid-template-columns: 1fr; }
  .slip-leg { grid-template-columns: 1fr; }
  .leg-metrics { text-align: left; }
  .slip-topline strong, .map-card > strong { font-size: 44px; }
  .holo-stage { min-height: 190px; }
}
@media (min-width: 1051px) and (max-width: 1179px) {
  .hero {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    align-items: start;
    border-radius: 20px;
    padding: 20px;
  }
  .stat, .refresh-box {
    align-self: start;
    min-height: auto;
  }
  .hero-copy { grid-column: 1 / -1; }
  .refresh-box { grid-column: span 2; }
  .slip-map { grid-template-columns: minmax(280px, 360px) 1fr; }
  .map-cards { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .slip-groups { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (min-width: 1180px) {
  .hero, .quick-nav, main {
    width: min(1760px, calc(100% - 48px));
  }
  .hero {
    grid-template-columns: minmax(420px, 1.2fr) repeat(5, minmax(88px, 112px)) minmax(210px, 260px);
    align-items: start;
    gap: 8px;
    margin-top: 16px;
    padding: 22px;
    border-radius: 18px;
    background:
      linear-gradient(135deg, rgb(255 255 255 / 8%), rgb(255 255 255 / 2%)),
      rgb(5 13 11 / 86%);
  }
  .hero::after {
    right: -8%;
    top: -54%;
    width: 34rem;
    height: 34rem;
  }
  .hero-copy { padding-right: 14px; }
  h1 {
    max-width: 720px;
    font-size: clamp(48px, 4.2vw, 70px);
  }
  .subtle {
    max-width: 680px;
    font-size: 15px;
  }
  .strong-note { border-radius: 10px; }
  .stat, .refresh-box {
    align-self: start;
    min-width: 0;
    min-height: auto;
    border-radius: 14px;
    padding: 10px;
  }
  .stat span { font-size: 11px; }
  .stat strong {
    font-size: clamp(16px, 1vw, 20px);
    line-height: 1.05;
    overflow: hidden;
    text-overflow: clip;
    white-space: nowrap;
  }
  #refresh-slip { min-height: 40px; }
  .quick-nav {
    width: min(1760px, calc(100% - 48px));
    max-width: none;
    justify-content: center;
    margin-top: 10px;
    padding: 7px;
    border-radius: 14px;
  }
  .quick-nav a {
    border-radius: 10px;
    padding: 8px 12px;
  }
  main {
    gap: 14px;
    padding-top: 14px;
  }
  .panel {
    border-radius: 18px;
    padding: 20px;
  }
  .section-head { padding-bottom: 10px; }
  .slip-map {
    grid-template-columns: minmax(320px, 390px) minmax(0, 1fr);
    gap: 14px;
  }
  .holo-stage {
    min-height: 250px;
    border-radius: 18px;
  }
  .holo-stage::before { inset: 44px 36px 34px; }
  .orbit-one { width: 244px; height: 102px; }
  .orbit-two { width: 172px; height: 72px; }
  .holo-core {
    width: 104px;
    height: 104px;
    border-radius: 24px;
  }
  .holo-core strong { font-size: 30px; }
  .holo-chip {
    min-width: 62px;
    padding: 7px 10px;
  }
  .map-panel { gap: 10px; }
  .map-cards {
    grid-template-columns: repeat(4, minmax(0, 1fr));
    gap: 10px;
  }
  .map-card {
    container-type: inline-size;
    min-height: 154px;
    overflow: hidden;
    border-radius: 16px;
    padding: 16px;
  }
  .map-card > strong {
    max-width: 100%;
    overflow: hidden;
    font-size: clamp(30px, 15cqw, 56px);
    white-space: nowrap;
  }
  .update-line { border-radius: 14px; }
  .slip-card {
    border-radius: 18px;
    padding: 18px;
  }
  .slip-topline strong {
    font-size: clamp(50px, 4vw, 72px);
  }
  .metric-strip {
    gap: 10px;
    margin: 14px 0;
  }
  .metric-strip span {
    border-radius: 12px;
    padding: 10px 12px;
  }
  .slip-groups {
    grid-template-columns: repeat(3, minmax(300px, 1fr));
    gap: 10px;
  }
  .league-block {
    border-radius: 14px;
    padding: 11px;
  }
  .slip-leg {
    grid-template-columns: minmax(0, 1fr) 116px;
    border-radius: 10px;
  }
  .leg-metrics { min-width: 104px; }
  button { border-radius: 10px; }
}
@media (min-width: 1500px) {
  .slip-map { grid-template-columns: 390px minmax(0, 1fr); }
  .map-card { min-height: 154px; }
  .holo-stage { min-height: 250px; }
  .slip-groups { grid-template-columns: repeat(4, minmax(300px, 1fr)); }
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
const LIVE_DATA_POLL_SECONDS = 60;
const LIVE_DATA_STALE_SECONDS = 300;

function formatTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString([], { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

function setRefreshStatus(status) {
  if (!refreshStatus || !refreshButton) return;
  const state = status?.state || "idle";
  refreshStatus.className = "";
  if (state === "running") {
    refreshButton.disabled = true;
    refreshButton.textContent = "Refreshing...";
    refreshStatus.classList.add("warning");
    refreshStatus.textContent = status.message || "Refreshing odds, schedules, public inputs, and slip math.";
    return;
  }
  refreshButton.disabled = false;
  refreshButton.textContent = "Refresh Slip Now";
  if (state === "complete") {
    refreshStatus.classList.add("good");
    refreshStatus.textContent = `Updated ${formatTimestamp(status.generated_at)} · 80%: ${status.primary_leg_count ?? "n/a"} · All-day: ${status.all_day_leg_count ?? "n/a"} · Edge: ${status.research_edge_leg_count ?? "n/a"}`;
    return;
  }
  if (state === "error") {
    refreshStatus.classList.add("bad");
    refreshStatus.textContent = status.error || status.message || "Refresh failed.";
    return;
  }
  refreshStatus.textContent = status?.message || "Ready. Re-scrapes odds, schedules, public inputs, and slip math.";
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
  setRefreshStatus({ state: "running", message: "Refreshing live data and slip math." });
  try {
    const response = await fetch("/refresh", { method: "POST", cache: "no-store" });
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
        const refreshResponse = await fetch("/refresh", { method: "POST", cache: "no-store" });
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
