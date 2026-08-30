from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from .combo_safety import combo_leg_signature


BROWSER_FIXTURE_STATES = ("live", "empty", "stale", "error", "loading")
SLIP_KEYS = ("custom_slip", "leverage_slip", "all_day_slip", "research_edge_slip")


FIXTURE_COMBO_TICKERS = {
    "custom_slip": "KXMVE-FIXTURE-PRIMARY",
    "leverage_slip": "KXMVE-FIXTURE-LEVERAGE",
    "all_day_slip": "KXMVE-FIXTURE-ALLDAY",
    "research_edge_slip": "KXMVE-FIXTURE-SCOUT",
}


def _fixture_leg(
    *,
    event: str,
    side: str,
    market_ticker: str,
    event_ticker: str,
    title: str,
    probability: float,
    ask_cents: float,
    sport: str,
    start_time: datetime,
    quoted_at: datetime,
) -> dict[str, Any]:
    """One priced leg, carrying what the slip-arithmetic engine requires.

    `api_fetched_at` and a non-stale freshness state are not decoration: without
    them every leg is dropped as unquoted and the whole analysis block renders
    as unavailable, which is what a fixture is least useful for. `event_ticker`
    is passed in rather than derived from the market ticker so two unrelated
    games cannot collide onto one event id -- the correlation model keys off it,
    and a collision would score independent games as same-event correlated.
    """
    return {
        "market_ticker": market_ticker,
        "event_ticker": event_ticker,
        "display_event": event,
        "title": title,
        "subtitle": title,
        "selection": title,
        "side": side,
        "sport": sport,
        "combo_category": sport,
        "probability": probability,
        "market_implied_probability": probability,
        "required_probability": 0.80,
        "ask_cents": ask_cents,
        "bid_cents": max(0.0, ask_cents - 2),
        "status": "active",
        "event_start_time": start_time.isoformat(),
        "market_close_time": start_time.isoformat(),
        # Freshness inputs for the slip-arithmetic engine.
        "api_fetched_at": quoted_at.isoformat(),
        "source_freshness_state": "fresh",
        "game_date": start_time.date().isoformat(),
    }


def _attach_combo_evidence(legs: list[dict[str, Any]], combo_ticker: str, fetched_at: datetime) -> list[dict[str, Any]]:
    """Stamp the exact-listed-combo evidence every display gate requires.

    The leg signature is derived from the legs themselves, so a caller cannot
    add or drop a leg and still look verified.
    """
    signature = combo_leg_signature(legs)
    for leg in legs:
        leg.update(
            {
                "combo_eligible": True,
                "combo_evidence_status": "listed_kalshi_mve_market",
                "combo_source": "kalshi_public_mve_market",
                "combo_market_ticker": combo_ticker,
                "combo_market_status": "active",
                "combo_market_fetched_at": fetched_at.isoformat(),
                "combo_market_snapshot_hash": f"sha256:fixture-{combo_ticker.lower()}",
                "combo_market_leg_signature": signature,
                "combo_exact_leg_count": len(legs),
                "combo_market_yes_ask_cents": 62.0,
            }
        )
    return legs


def _fixture_slip(
    legs: list[dict[str, Any]],
    *,
    combo_ticker: str,
    price_cents: float,
    adjusted_probability: float,
    payout_dollars: float,
) -> dict[str, Any]:
    return {
        "action": "BUILD_SLIP",
        "legs": legs,
        "leg_count": len(legs),
        "eligible_leg_count": len(legs),
        "min_leg_probability": 0.80,
        "estimated_combo_price_cents": price_cents,
        "adjusted_probability": adjusted_probability,
        "estimated_payout_if_right": payout_dollars,
        "manual_entry_ready": True,
        "listed_combo_market_ticker": combo_ticker,
        "combo_compatibility": {
            "status": "compatible",
            "exact_listed_combo": True,
            "manual_entry_ready": True,
            "categories": ["MLB"],
        },
        "sports": ["MLB"],
    }


def make_verified_fixture_payload(*, now: datetime | None = None) -> dict[str, Any]:
    """Build a dashboard payload that survives the freshness and combo gates.

    Rendering the populated dashboard requires per-leg exact-contract evidence
    whose signature hashes the legs it describes, which is too intricate to
    reproduce correctly in each test or preview script. This helper is the one
    place that knows how to assemble it, so tests, golden renders, and
    `scripts/browser_validation_server.py` all exercise the same shape the
    collector produces.
    """
    now = now or datetime.now(timezone.utc)
    generated_at = now - timedelta(minutes=4)

    primary_legs = _attach_combo_evidence(
        [
            _fixture_leg(
                event="NYY @ BOS",
                side="yes",
                market_ticker="KXMLBGAME-FIXTURE-NYY",
                event_ticker="KXMLBGAME-26AUG31-NYYBOS",
                title="Yankees win",
                probability=0.86,
                ask_cents=84.0,
                sport="MLB",
                start_time=now + timedelta(hours=3.5),
                quoted_at=generated_at,
            ),
            _fixture_leg(
                event="LAD @ SD",
                side="yes",
                market_ticker="KXMLBGAME-FIXTURE-LAD",
                event_ticker="KXMLBGAME-26AUG31-LADSD",
                title="Dodgers win",
                probability=0.84,
                ask_cents=83.0,
                sport="MLB",
                start_time=now + timedelta(hours=5),
                quoted_at=generated_at,
            ),
            _fixture_leg(
                event="KC @ BAL",
                side="no",
                market_ticker="KXMLBTOTAL-FIXTURE-KCBAL",
                event_ticker="KXMLBTOTAL-26AUG31-KCBAL",
                title="Over 9.5 runs",
                probability=0.82,
                ask_cents=81.0,
                sport="MLB",
                start_time=now + timedelta(hours=2),
                quoted_at=generated_at,
            ),
        ],
        FIXTURE_COMBO_TICKERS["custom_slip"],
        generated_at,
    )
    leverage_legs = _attach_combo_evidence(
        [
            _fixture_leg(
                event="PHI @ ATL",
                side="yes",
                market_ticker="KXMLBGAME-FIXTURE-PHI",
                event_ticker="KXMLBGAME-26AUG31-PHIATL",
                title="Phillies win",
                probability=0.78,
                ask_cents=77.0,
                sport="MLB",
                start_time=now + timedelta(hours=4),
                quoted_at=generated_at,
            ),
            _fixture_leg(
                event="SEA @ HOU",
                side="yes",
                market_ticker="KXMLBGAME-FIXTURE-HOU",
                event_ticker="KXMLBGAME-26AUG31-SEAHOU",
                title="Astros win",
                probability=0.76,
                ask_cents=76.0,
                sport="MLB",
                start_time=now + timedelta(hours=6.5),
                quoted_at=generated_at,
            ),
        ],
        FIXTURE_COMBO_TICKERS["leverage_slip"],
        generated_at,
    )

    markets = [
        {
            "ticker": FIXTURE_COMBO_TICKERS["custom_slip"],
            "title": "Yankees + Dodgers + Under combo",
            "close_time": (now + timedelta(hours=2)).isoformat(),
            "yes_ask_cents": 62.0,
            "yes_bid_cents": 60.0,
            "no_ask_cents": 42.0,
            "volume_24h": "1204",
            "real_data_ready": True,
            "real_data_warning": "",
            "leg_details": [
                {
                    "display_event": leg["display_event"],
                    "side": leg["side"],
                    "subtitle": leg["subtitle"],
                    "market_ticker": leg["market_ticker"],
                    "market_implied_probability": leg["probability"],
                    "ask_cents": leg["ask_cents"],
                    "bid_cents": leg["bid_cents"],
                }
                for leg in primary_legs
            ],
        },
        {
            "ticker": FIXTURE_COMBO_TICKERS["leverage_slip"],
            "title": "Phillies + Astros double",
            "close_time": (now + timedelta(hours=4)).isoformat(),
            "yes_ask_cents": 58.0,
            "yes_bid_cents": 56.0,
            "no_ask_cents": 46.0,
            "volume_24h": "988",
            "real_data_ready": True,
            "real_data_warning": "",
            "leg_details": [
                {
                    "display_event": leg["display_event"],
                    "side": leg["side"],
                    "subtitle": leg["subtitle"],
                    "market_ticker": leg["market_ticker"],
                    "market_implied_probability": leg["probability"],
                    "ask_cents": leg["ask_cents"],
                    "bid_cents": leg["bid_cents"],
                }
                for leg in leverage_legs
            ],
        },
    ]

    return {
        "date": generated_at.date().isoformat(),
        "generated_at": generated_at.isoformat(),
        "games": [{"id": f"fixture-game-{index}"} for index in range(11)],
        "markets": markets,
        "custom_slip": _fixture_slip(
            primary_legs,
            combo_ticker=FIXTURE_COMBO_TICKERS["custom_slip"],
            price_cents=61.0,
            adjusted_probability=0.593,
            payout_dollars=8.20,
        ),
        "leverage_slip": _fixture_slip(
            leverage_legs,
            combo_ticker=FIXTURE_COMBO_TICKERS["leverage_slip"],
            price_cents=58.0,
            adjusted_probability=0.5928,
            payout_dollars=8.62,
        ),
        "all_day_slip": {
            "action": "NO_SLIP",
            "reason": "No verified all-day combo meets the 75-85c window in this fixture.",
            "eligible_leg_count": 0,
        },
        "research_edge_slip": {
            "action": "NO_SLIP",
            "reason": "The research scout found no listed combo with enough source evidence.",
            "eligible_leg_count": 0,
        },
        "combo_source_summary": {
            "active_kxmve_market_count": 14,
            "verified_current_day_contract_count": 9,
            "tiers": {
                "primary": {"eligible_exact_combo_count": 1},
                "leverage": {"eligible_exact_combo_count": 1},
                "all_day": {"eligible_exact_combo_count": 0},
                "research_edge": {"eligible_exact_combo_count": 0},
            },
        },
        "dashboard_snapshot": {"source": "postgres"},
    }


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
