from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


DEFAULT_MAX_SLIP_AGE_SECONDS = 30 * 60
SLIP_PAYLOAD_KEYS = (
    "custom_slip",
    "leverage_slip",
    "all_day_slip",
    "research_edge_slip",
)


def slip_payload_gate(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_SLIP_AGE_SECONDS,
) -> dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    if payload.get("refresh_error"):
        return _blocked_gate(
            "blocked_refresh_failed",
            "The latest live refresh failed. Slips are hidden until a fresh refresh succeeds.",
        )

    source_cache_status = payload.get("source_cache_status") or {}
    stale_fallback_count = int(source_cache_status.get("stale_fallback_count") or 0)
    if stale_fallback_count:
        return _blocked_gate(
            "blocked_stale_source",
            "Fresh source data is unavailable. Slips are hidden until a live refresh succeeds.",
            stale_fallback_count=stale_fallback_count,
        )

    generated_at = _parse_timestamp(payload.get("generated_at"))
    if generated_at is None:
        return _blocked_gate(
            "blocked_missing_generated_at",
            "The live data timestamp is unavailable. Slips are hidden until the next valid refresh.",
        )

    age_seconds = int((now - generated_at.astimezone(timezone.utc)).total_seconds())
    if age_seconds < -300:
        return _blocked_gate(
            "blocked_invalid_generated_at",
            "The live data timestamp is invalid. Slips are hidden until the next valid refresh.",
            data_age_seconds=age_seconds,
        )
    if age_seconds > max(0, int(max_age_seconds)):
        return _blocked_gate(
            "blocked_stale_payload",
            "Live data is too old. Slips are hidden until a fresh refresh succeeds.",
            data_age_seconds=age_seconds,
        )
    return {
        "status": "ready",
        "code": "fresh_data_ready",
        "message": "Live data is fresh enough for manual review.",
        "data_age_seconds": max(0, age_seconds),
        "stale_fallback_count": 0,
    }


def gate_slip_payload(
    payload: dict[str, Any],
    *,
    now: datetime | None = None,
    max_age_seconds: int = DEFAULT_MAX_SLIP_AGE_SECONDS,
) -> dict[str, Any]:
    gated = dict(payload)
    gate = slip_payload_gate(payload, now=now, max_age_seconds=max_age_seconds)
    gated["public_data_gate"] = gate
    if gate["status"] == "ready":
        return gated

    for key in SLIP_PAYLOAD_KEYS:
        previous = payload.get(key) or {}
        gated[key] = {
            "action": "NO_SLIP",
            "reason": gate["message"],
            "source_gate_status": gate["code"],
            "eligible_leg_count": 0,
            "blocked_previous_leg_count": int(previous.get("leg_count") or 0),
            "leg_count": 0,
            "legs": [],
        }
    gated["pick_summary"] = {
        "action": "NO_BET",
        "reason": gate["message"],
        "source_gate_status": gate["code"],
        "candidates": [],
        "watchlist": [],
    }
    return gated


def consumer_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        key: payload.get(key)
        for key in (
            "date",
            "generated_at",
            "generated_at_note",
            "safety_note",
            "public_data_gate",
            "custom_slip",
            "leverage_slip",
            "all_day_slip",
            "research_edge_slip",
        )
    }


def _blocked_gate(code: str, message: str, **details: Any) -> dict[str, Any]:
    return {
        "status": "blocked",
        "code": code,
        "message": message,
        "data_age_seconds": details.pop("data_age_seconds", None),
        "stale_fallback_count": details.pop("stale_fallback_count", 0),
        **details,
    }


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp
