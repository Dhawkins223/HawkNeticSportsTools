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



# ── panels the composed dashboard reads from the database ───────────────────
#
# `render_dashboard` does not take the sports board, the closing-line report or
# the research record from its payload; it calls `safe_sports_board()`,
# `safe_sports_clv_report()` and `build_research_record()` itself. In a test
# without PostgreSQL all three return their empty forms, so the golden render
# exercised the slip cards and nothing else -- four panels went unrendered in
# every test, screenshot and local preview.
#
# That is not hypothetical. A change to `render_sports_event` once made the
# whole board raise NameError and no test noticed, because no test had ever
# rendered a board with an event in it.
#
# Every key below was read off the real producers rather than inferred from the
# renderers, and `test_fixture_contracts` asserts they still match. A fixture
# missing a key the producer returns renders a *different page* than production,
# which is the one thing a golden fixture must not do: the first draft of this
# one used `best_price` where the board emits `best_odds`, so every posted price
# rendered "n/a" and the test still passed.


def make_fixture_sports_board(*, now: datetime | None = None) -> dict[str, Any]:
    """A fresh sports board with one event, as `safe_sports_board` returns.

    Values are shaped like the producer's: exact decimals arrive as strings,
    `market_type` is the normalised name rather than the upstream API key.
    """

    moment = now or datetime.now(timezone.utc)
    fetched = moment.isoformat()
    start = (moment + timedelta(hours=6)).isoformat()

    def selection(
        name: str,
        *,
        best: str,
        worst: str,
        implied: str,
        fair: str,
        consensus: str,
        gap: str,
        gain: str | None = None,
        line: str | None = None,
    ) -> dict[str, Any]:
        return {
            "selection": name,
            "line": line,
            "best_odds": best,
            "best_bookmaker": "book_b",
            "worst_odds": worst,
            "worst_bookmaker": "book_a",
            # Only one side carries a shopping gain: a board where every row
            # shows a pill is not a board anyone reads carefully.
            "line_shopping_gain_probability": gain,
            "odds_format": "american",
            "implied_probability": implied,
            "no_vig_probability": fair,
            "consensus_probability": consensus,
            "best_price_vs_consensus_probability": gap,
            "quoted_by": ["book_a", "book_b"],
            "quote_count": 2,
            "odds_timestamp": fetched,
            "api_fetched_at": fetched,
            "source_snapshot_hash": "0" * 64,
        }

    return {
        "asset_class": "sports",
        "generated_at": fetched,
        "board_state": "fresh",
        "state_reason": "sports_source_within_freshness_window",
        "is_current": True,
        "stale_after_seconds": 3600,
        "latest_source_fetched_at": fetched,
        "source_age_seconds": 19,
        "withheld_event_count": 0,
        "event_count": 1,
        "quote_count": 6,
        "source_health": [],
        "worker": None,
        "model_state": "baseline_only",
        "decision_status": "track_only",
        "probability_source": "bookmaker_implied",
        "disclaimer": (
            "No-vig probabilities and best available prices are observations of "
            "posted bookmaker markets. They are a baseline, not a validated model "
            "edge, and never a betting recommendation."
        ),
        "events": [
            {
                "event_id": "fixture-1",
                "sport": "americanfootball_nfl",
                "league": "nfl",
                "home_team": "Home Team",
                "away_team": "Away Team",
                "game_start_time": start,
                "seconds_to_start": 21600,
                "market_count": 2,
                "markets": [
                    {
                        "market_type": "moneyline",
                        "line": None,
                        "bookmakers": ["book_a", "book_b"],
                        "bookmaker_count": 2,
                        "overround": "0.023933",
                        "no_vig_available": True,
                        "no_vig_method": "shin",
                        "no_vig_method_disagreement": "0.001839",
                        "consensus_available": True,
                        "consensus_method": "per_book_shin_median",
                        "consensus_bookmakers": ["book_a", "book_b"],
                        "consensus_bookmaker_count": 2,
                        "consensus_median_sum_before_normalization": "1.023933",
                        "selections": [
                            selection(
                                "Home Team",
                                best="-130.000000000000",
                                worst="-135.000000000000",
                                implied="0.565217",
                                fair="0.553251",
                                consensus="0.553963",
                                gap="0.011254",
                                gain="0.006401",
                            ),
                            selection(
                                "Away Team",
                                best="118.000000000000",
                                worst="115.000000000000",
                                implied="0.458716",
                                fair="0.446749",
                                consensus="0.446037",
                                gap="-0.012679",
                            ),
                        ],
                    },
                    {
                        # One-sided, so the panel takes its no-de-vig branch, and
                        # a totals market carries a line on both the market and
                        # each selection.
                        "market_type": "total",
                        "line": "218.500000000000",
                        "bookmakers": ["book_a"],
                        "bookmaker_count": 1,
                        "overround": None,
                        "no_vig_available": False,
                        "no_vig_method": None,
                        "no_vig_method_disagreement": None,
                        "consensus_available": False,
                        "consensus_method": None,
                        "consensus_bookmakers": [],
                        "consensus_bookmaker_count": 0,
                        "consensus_median_sum_before_normalization": None,
                        "selections": [
                            selection(
                                "Over",
                                best="-105.000000000000",
                                worst="-105.000000000000",
                                implied="0.512195",
                                fair=None,
                                consensus=None,
                                gap=None,
                                line="218.500000000000",
                            ),
                        ],
                    },
                ],
            },
        ],
    }


def make_fixture_sports_clv_report() -> dict[str, Any]:
    """A graded closing-line report whose interval clears zero.

    Sized so the panel takes its "this is a result" branch; the straddling-zero
    and no-interval branches are covered directly in `test_sports_clv`.
    """

    return {
        "asset_class": "sports",
        "run_id": None,
        "measure": "closing_line_value",
        "graded_rows": 200,
        "pending_rows": 3,
        "beat_close": 120,
        "lost_to_close": 70,
        "matched_close": 10,
        "beat_rate": "0.631579",
        "beat_rate_denominator": 190,
        "average_clv": "0.012000",
        "average_clv_interval": ["0.008000", "0.016000"],
        "average_clv_sample": 200,
        "total_clv": "2.400000",
        "by_market": [
            {"market_type": "moneyline", "graded_rows": 140, "beat_close": 86, "average_clv": "0.013100"}
        ],
        "by_bookmaker": [
            {"bookmaker": "book_a", "graded_rows": 200, "beat_close": 120, "average_clv": "0.012000"}
        ],
        "model_state": "baseline_only",
        "decision_status": "track_only",
        "disclaimer": (
            "Closing line value compares a recorded price against the last price "
            "the same book posted before the game started. It is not profit and "
            "not a settled result."
        ),
    }


def make_fixture_research_record() -> dict[str, Any]:
    """One measured track and one without settled rows.

    Both states matter: the measured card is the only place the hit rate, its
    interval and the success accent render together, and the unmeasured card is
    what proves absence is not being coloured like a result. `status` is `OK`
    because that is what the producer returns for a record with valid rows and a
    reachable database -- without it the panel renders its `WATCH` warning and
    the golden page stops matching production.
    """

    def track(
        name: str,
        asset_class: str,
        *,
        valid: int,
        wins: int,
        losses: int,
        hit_rate: float | None,
        interval: list[float] | None,
        status: str,
    ) -> dict[str, Any]:
        settled = wins + losses
        return {
            "bot_name": name,
            "asset_class": asset_class,
            "valid_rows": valid,
            "invalid_log_rows": 0,
            "settled_rows": settled,
            "deduped_settled_exposures": settled,
            "unresolved_rows": 0,
            "rejected_rows": 0,
            "rejection_reasons": [],
            "wins": wins,
            "losses": losses,
            "push_no_edge_or_void": 0,
            "win_loss_count": settled,
            "observed_hit_rate": hit_rate,
            "observed_hit_rate_raw": hit_rate,
            "observed_hit_rate_interval": interval,
            "hit_rate_status": status,
            "sample_gate_required": 30,
            "dedupe_policy": "event_id + market_id",
            "metric_guardrail": (
                "Hit rate is reported only from settled win/loss rows after "
                "deduplication, and only once the sample gate is met."
            ),
        }

    return {
        "status": "OK",
        "db_available": True,
        "metric_policy": (
            "Research-only. Hit rate is sample-gated and uses settled win/loss "
            "rows only; unresolved, rejected, invalid, push/no-edge, and duplicate "
            "exposure rows are excluded from performance claims."
        ),
        "current_slip_rationale": [],
        "next_action": "Keep collecting settled rows before any performance claim.",
        "tracks": [
            track(
                "Kalshi Slip Engine",
                "kalshi",
                valid=104,
                wins=69,
                losses=35,
                hit_rate=0.663462,
                interval=[0.568301, 0.747004],
                status="measured",
            ),
            track(
                "Crypto Research Bot",
                "crypto",
                valid=0,
                wins=0,
                losses=0,
                hit_rate=None,
                interval=None,
                status="unavailable / no settled rows",
            ),
        ],
    }
