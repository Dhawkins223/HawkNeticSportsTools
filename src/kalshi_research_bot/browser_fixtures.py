from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


BROWSER_FIXTURE_STATES = ("live", "empty", "stale", "error", "loading")
SLIP_KEYS = ("custom_slip", "leverage_slip", "all_day_slip", "research_edge_slip")


def build_browser_fixture_payload(payload: Mapping[str, Any], state: str) -> dict[str, Any]:
    if state not in BROWSER_FIXTURE_STATES:
        raise ValueError("invalid_browser_fixture_state")
    fixture = deepcopy(dict(payload))
    if state == "empty":
        fixture["games"] = []
        fixture["markets"] = []
        fixture["all_day_market_count"] = 0
        fixture["pick_summary"] = {
            "action": "NO_BET",
            "reason": "browser_fixture_empty_state",
            "candidates": [],
            "watchlist": [],
            "tradable_combo_count": 0,
        }
        for key in SLIP_KEYS:
            slip = dict(fixture.get(key) or {})
            slip.update(
                {
                    "action": "NO_BET",
                    "legs": [],
                    "leg_count": 0,
                    "eligible_leg_count": 0,
                    "manual_entry_ready": False,
                    "note": "No qualifying rows in the browser validation fixture.",
                }
            )
            fixture[key] = slip
    elif state in {"stale", "error"}:
        fixture["generated_at"] = "2000-01-01T00:00:00+00:00"
        fixture["generated_at_note"] = "Intentionally stale browser validation fixture."
        if state == "error":
            fixture["refresh_error"] = "browser_fixture_source_failed"
            fixture["refresh_failed_at"] = "2000-01-01T00:00:00+00:00"
    return fixture


def browser_fixture_refresh_status(state: str) -> dict[str, Any]:
    if state not in BROWSER_FIXTURE_STATES:
        raise ValueError("invalid_browser_fixture_state")
    if state == "loading":
        return {
            "state": "running",
            "accepted": True,
            "message": "Browser validation refresh is running.",
        }
    if state == "error":
        return {
            "state": "error",
            "accepted": False,
            "message": "Browser validation source failed.",
            "error": "browser_fixture_source_failed",
        }
    return {
        "state": "idle",
        "accepted": False,
        "message": "Browser fixture refresh is intentionally disabled.",
    }
