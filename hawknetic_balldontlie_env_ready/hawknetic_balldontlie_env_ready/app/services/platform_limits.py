"""Usage limits, rate limiting, and saved-slip run-by-id orchestration.

Centralizes:
  * Plan-based daily slip-run limits (free=3, pro=50, premium=250).
  * Per-route, per-IP rate limiting (login/signup/algorithm).
  * Saved slip lookup → analyze → result persistence.
  * Live-readiness hard-block check (returns blocked result instead of running MC).
"""
from __future__ import annotations

import json
import os
import time
from datetime import date, datetime, timezone
from typing import Any

from fastapi import HTTPException

from app.database import execute, get_connection
from app.services.billing import PLAN_RUN_LIMITS


# -----------------------------------------------------------------------------
# Usage limits
# -----------------------------------------------------------------------------

def _today_iso() -> str:
    return date.today().isoformat()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_user_plan(user_id: int) -> str:
    with get_connection() as conn:
        row = execute(conn, "SELECT plan FROM users WHERE id = ?", (user_id,)).fetchone()
    if not row:
        return "free"
    return (dict(row).get("plan") or "free").lower()


def usage_for_user_today(user_id: int) -> dict[str, int | str]:
    plan = get_user_plan(user_id)
    max_runs = PLAN_RUN_LIMITS.get(plan, 3)
    today = _today_iso()
    with get_connection() as conn:
        row = execute(conn, "SELECT slip_runs_used FROM usage_limits WHERE user_id = ? AND date = ?", (user_id, today)).fetchone()
    used = int(dict(row).get("slip_runs_used", 0)) if row else 0
    return {"plan": plan, "date": today, "used": used, "limit": max_runs, "remaining": max(0, max_runs - used)}


def assert_can_run(user_id: int) -> dict[str, int | str]:
    """Raises 403 if the user has hit their plan's daily run limit."""
    usage = usage_for_user_today(user_id)
    if usage["used"] >= usage["limit"]:
        raise HTTPException(
            status_code=403,
            detail=f"Daily algorithm run limit reached for your {usage['plan']} plan ({usage['used']}/{usage['limit']}). Upgrade to keep running today's slips.",
        )
    return usage


def increment_usage(user_id: int) -> None:
    """Atomic upsert of today's run count. Only called AFTER a successful run."""
    plan = get_user_plan(user_id)
    max_runs = PLAN_RUN_LIMITS.get(plan, 3)
    today = _today_iso()
    with get_connection() as conn:
        existing = execute(conn, "SELECT id, slip_runs_used FROM usage_limits WHERE user_id = ? AND date = ?", (user_id, today)).fetchone()
        if existing:
            execute(conn, """
                UPDATE usage_limits SET slip_runs_used = slip_runs_used + 1, plan = ?, max_slip_runs = ?, updated_at = ?
                WHERE user_id = ? AND date = ?
            """, (plan, max_runs, _now_iso(), user_id, today))
        else:
            execute(conn, """
                INSERT INTO usage_limits(user_id, date, slip_runs_used, max_slip_runs, plan, created_at, updated_at)
                VALUES(?, ?, 1, ?, ?, ?, ?)
            """, (user_id, today, max_runs, plan, _now_iso(), _now_iso()))


# -----------------------------------------------------------------------------
# Rate limiting (in-memory sliding window per process)
# -----------------------------------------------------------------------------

_RATE_BUCKETS: dict[str, list[float]] = {}


def rate_limit(bucket: str, max_hits: int, window_seconds: float) -> None:
    """Raises 429 if `bucket` has exceeded `max_hits` within `window_seconds`."""
    now = time.time()
    cutoff = now - window_seconds
    hits = _RATE_BUCKETS.setdefault(bucket, [])
    # Drop expired
    while hits and hits[0] < cutoff:
        hits.pop(0)
    if len(hits) >= max_hits:
        raise HTTPException(status_code=429, detail="Too many requests. Slow down and try again shortly.")
    hits.append(now)


def reset_rate_limit(bucket: str) -> None:
    _RATE_BUCKETS.pop(bucket, None)


# -----------------------------------------------------------------------------
# Saved slip → analyze → persist
# -----------------------------------------------------------------------------

def run_saved_slip(*, slip_id: int, user_id: int, stake: float = 10.0, runs: int = 10000) -> dict[str, Any]:
    from app.services.slip_analysis import analyze_slip as analyze_slip_request

    with get_connection() as conn:
        slip = execute(conn, "SELECT id, user_id, name, sport FROM parlays WHERE id = ?", (slip_id,)).fetchone()
        if not slip or int(dict(slip).get("user_id") or 0) != user_id:
            raise HTTPException(status_code=404, detail="Slip not found.")
        legs_rows = execute(conn, """
            SELECT id, label, market_type, odds_value, line, probability, leg_order, game_id, player_id, team_id, notes
            FROM parlay_legs WHERE parlay_id = ? ORDER BY leg_order ASC
        """, (slip_id,)).fetchall()

    legs_payload = []
    for row in legs_rows:
        d = dict(row)
        legs_payload.append({
            "id": str(d["id"]),
            "sport": dict(slip).get("sport") or "NBA",
            "bookmaker": "consensus",
            "gameId": d.get("game_id") or "",
            "eventLabel": d.get("notes") or d.get("label") or "Saved leg",
            "marketType": d.get("market_type") or "player_prop",
            "selection": d.get("label") or "",
            "line": d.get("line"),
            "oddsAmerican": int(d["odds_value"]) if d.get("odds_value") is not None else 0,
            "playerId": str(d["player_id"]) if d.get("player_id") else None,
            "teamId": str(d["team_id"]) if d.get("team_id") else None,
        })

    if not legs_payload:
        raise HTTPException(status_code=400, detail="Saved slip has no legs to run.")

    request = {"bookmaker": "consensus", "stake": stake, "legs": legs_payload, "runs": runs}
    result = analyze_slip_request(request)
    persist_slip_result(slip_id=slip_id, user_id=user_id, sport=dict(slip).get("sport"), result=result)
    return result


def persist_slip_result(*, slip_id: int, user_id: int, sport: str | None, result: dict[str, Any]) -> int:
    blocked = 1 if result.get("status") == "blocked" else 0
    with get_connection() as conn:
        cur = execute(conn, """
            INSERT INTO slip_results(slip_id, user_id, sport, result_json, classification, recommended_action,
                parlay_probability, parlay_ev, confidence_score, simulation_runs, blocked, blocking_reasons, created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            slip_id, user_id, sport,
            json.dumps(result, default=str),
            result.get("parlayClassification") or result.get("recommendation"),
            result.get("summary"),
            result.get("parlayProbability"),
            result.get("parlayEv"),
            result.get("parlayConfidenceScore"),
            result.get("simulationRuns"),
            blocked,
            json.dumps(result.get("readiness", {}).get("blocking_reasons", [])),
            _now_iso(),
        ))
        # Update slip summary fields
        execute(conn, """
            UPDATE parlays SET win_probability = ?, loss_probability = ?, estimated_odds = ?,
                confidence_tier = ?, correlation_warning = ?, updated_at = ?
            WHERE id = ?
        """, (
            result.get("parlayProbability"),
            (1 - result.get("parlayProbability", 0)) if result.get("parlayProbability") is not None else None,
            result.get("parlayAmericanOdds"),
            result.get("confidenceTier"),
            result.get("correlationWarning"),
            _now_iso(),
            slip_id,
        ))
        return int(cur.lastrowid)


def list_slip_results(*, slip_id: int, user_id: int, limit: int = 25) -> list[dict[str, Any]]:
    with get_connection() as conn:
        slip = execute(conn, "SELECT user_id FROM parlays WHERE id = ?", (slip_id,)).fetchone()
        if not slip or int(dict(slip).get("user_id") or 0) != user_id:
            raise HTTPException(status_code=404, detail="Slip not found.")
        rows = execute(conn, """
            SELECT id, sport, classification, recommended_action, parlay_probability, parlay_ev,
                confidence_score, simulation_runs, blocked, blocking_reasons, created_at
            FROM slip_results WHERE slip_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?
        """, (slip_id, user_id, limit)).fetchall()
    return [dict(r) for r in rows]


# -----------------------------------------------------------------------------
# Reorder
# -----------------------------------------------------------------------------

def reorder_slip(*, slip_id: int, user_id: int, leg_order: list[dict[str, Any]]) -> dict[str, Any]:
    if not leg_order:
        raise HTTPException(status_code=400, detail="leg_order must contain at least one entry.")
    with get_connection() as conn:
        slip = execute(conn, "SELECT id, user_id FROM parlays WHERE id = ?", (slip_id,)).fetchone()
        if not slip or int(dict(slip).get("user_id") or 0) != user_id:
            raise HTTPException(status_code=404, detail="Slip not found.")
        existing_ids = {int(dict(r)["id"]) for r in execute(conn, "SELECT id FROM parlay_legs WHERE parlay_id = ?", (slip_id,)).fetchall()}
        sent_ids = [int(item["leg_id"]) for item in leg_order]
        if set(sent_ids) - existing_ids:
            raise HTTPException(status_code=400, detail="One or more leg_ids do not belong to this slip.")
        for item in leg_order:
            execute(conn, "UPDATE parlay_legs SET leg_order = ? WHERE id = ? AND parlay_id = ?", (int(item["position"]), int(item["leg_id"]), slip_id))
        execute(conn, "UPDATE parlays SET updated_at = ? WHERE id = ?", (_now_iso(), slip_id))
    return {"ok": True, "slip_id": slip_id, "legs": len(leg_order)}


# -----------------------------------------------------------------------------
# Readiness hard-block
# -----------------------------------------------------------------------------

def blocked_result(readiness: dict[str, Any], stake: float, leg_count: int) -> dict[str, Any]:
    """Returned in place of a Monte Carlo run when readiness has blocking reasons."""
    return {
        "ok": True,
        "status": "blocked",
        "stake": stake,
        "legCount": leg_count,
        "recommendation": "INSUFFICIENT_DATA",
        "parlayClassification": "Blocked",
        "summary": "Live data is not ready. Algorithm run blocked.",
        "warnings": readiness.get("warnings", []),
        "legAnalyses": [],
        "betterAlternatives": [],
        "modelWinProbability": None,
        "impliedProbability": None,
        "parlayProbability": None,
        "parlayEv": None,
        "parlayEdge": None,
        "edgePct": None,
        "expectedValue": None,
        "fairAmericanOdds": None,
        "parlayAmericanOdds": None,
        "confidenceTier": "INSUFFICIENT_DATA",
        "blocking_reasons": readiness.get("blocking_reasons", []),
        "readiness": readiness,
        "simulationRuns": 0,
        "trapLegs": [],
        "correlationMatrix": [],
        "correlationWarning": None,
    }


def is_production() -> bool:
    return (os.environ.get("HAWKNETIC_ENV") or "").lower() == "production"
