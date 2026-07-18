import unittest
from decimal import Decimal

from kalshi_research_bot.evaluation.execution import (
    ExecutionConfig,
    MarketSnapshot,
    PaperOrder,
    PriceLevel,
    kalshi_fee_cents,
    settle_execution,
    simulate_order,
)
from kalshi_research_bot.evaluation.exposure import (
    ExposureCandidate,
    ExposureLimits,
    apply_exposure_limits,
    correlation_group_id,
    exposure_adjusted_performance,
)


def _snapshot(**overrides):
    values = {
        "market_id": "MKT-1",
        "snapshot_timestamp": "2026-07-12T12:00:00Z",
        "market_status": "open",
        "yes_bid_cents": 60,
        "yes_ask_cents": 62,
        "no_bid_cents": 37,
        "no_ask_cents": 39,
        "yes_ask_depth": (PriceLevel(62, 3), PriceLevel(63, 4), PriceLevel(65, 10)),
        "no_ask_depth": (PriceLevel(39, 10),),
        "close_timestamp": "2026-07-12T14:00:00Z",
        "source_snapshot_hash": "sha256:fixture",
    }
    values.update(overrides)
    return MarketSnapshot(**values)


def _order(**overrides):
    values = {
        "order_id": "order-1",
        "market_id": "MKT-1",
        "signal_timestamp": "2026-07-12T11:59:00Z",
        "order_timestamp": "2026-07-12T12:00:01Z",
        "contract_side": "yes",
        "order_type": "market",
        "quantity": 5,
        "intended_price_cents": 62,
    }
    values.update(overrides)
    return PaperOrder(**values)


class ExecutionExposureTests(unittest.TestCase):
    def test_official_general_fee_formula_rounds_up_to_cent(self):
        fee = kalshi_fee_cents(
            price_cents=50,
            quantity=1,
            liquidity_role="taker",
            config=ExecutionConfig(),
        )
        self.assertEqual(fee, Decimal("2"))

    def test_conservative_market_order_consumes_depth_and_charges_taker_fee(self):
        result = simulate_order(_order(), _snapshot(), config=ExecutionConfig(market_slippage_cents=2))
        self.assertEqual(result.fill_state, "filled")
        self.assertEqual(result.filled_quantity, 5)
        self.assertEqual(result.simulated_fill_price_cents, Decimal("62.4"))
        self.assertGreater(result.fee_estimate_cents, 0)
        self.assertEqual(result.liquidity_role, "taker")
        settled = settle_execution(result, winning_side="yes")
        self.assertEqual(settled.final_payout_cents, 500)
        self.assertLess(settled.net_return_cents, settled.gross_return_cents)

    def test_market_order_partial_fill_is_not_assumed_full(self):
        snapshot = _snapshot(yes_ask_depth=(PriceLevel(62, 2),))
        result = simulate_order(_order(quantity=5), snapshot)
        self.assertEqual(result.fill_state, "partial_fill")
        self.assertEqual(result.filled_quantity, 2)
        self.assertEqual(result.unfilled_quantity, 3)

    def test_resting_limit_requires_explicit_fill_evidence(self):
        no_fill = simulate_order(
            _order(order_type="limit", limit_price_cents=60, resting_fill_quantity=0),
            _snapshot(),
        )
        self.assertEqual(no_fill.fill_state, "no_fill")
        self.assertEqual(no_fill.rejection_reason, "resting_limit_not_filled")
        partial = simulate_order(
            _order(order_type="limit", limit_price_cents=60, resting_fill_quantity=2),
            _snapshot(),
        )
        self.assertEqual(partial.fill_state, "partial_fill")
        self.assertEqual(partial.liquidity_role, "maker")

    def test_closed_or_future_snapshot_is_rejected(self):
        closed = simulate_order(_order(), _snapshot(market_status="closed"))
        self.assertEqual(closed.fill_state, "rejected")
        self.assertIn("market_not_open", closed.rejection_reason)
        future = simulate_order(
            _order(),
            _snapshot(snapshot_timestamp="2026-07-12T12:00:02Z"),
        )
        self.assertEqual(future.rejection_reason, "future_execution_snapshot")

    def test_position_and_capital_limits_reject_execution(self):
        position = simulate_order(_order(quantity=101), _snapshot())
        self.assertEqual(position.rejection_reason, "position_limit_exceeded")
        capital = simulate_order(
            _order(quantity=5),
            _snapshot(),
            config=ExecutionConfig(maximum_capital_cents=100),
        )
        self.assertEqual(capital.fill_state, "partial_fill")
        self.assertEqual(capital.filled_quantity, 1)

    def test_correlation_group_is_deterministic(self):
        first = correlation_group_id(event_id="Event 1", category="sports", underlying_ids=["Team B", "Team A"])
        second = correlation_group_id(event_id="event-1", category="sports", underlying_ids=["team a", "team b"])
        self.assertEqual(first, second)

    def test_exposure_layer_preserves_raw_rows_and_blocks_correlated_markets(self):
        candidates = [
            ExposureCandidate(
                prediction_id="p1",
                prediction_timestamp="2026-07-12T12:00:00Z",
                event_id="game-1",
                market_id="winner-a",
                category="sports",
                contract_side="yes",
                capital_at_risk_cents=5000,
                underlying_ids=("team-a", "team-b"),
            ),
            ExposureCandidate(
                prediction_id="p2",
                prediction_timestamp="2026-07-12T12:01:00Z",
                event_id="game-1",
                market_id="winner-b",
                category="sports",
                contract_side="no",
                capital_at_risk_cents=5000,
                underlying_ids=("team-a", "team-b"),
            ),
        ]
        report = apply_exposure_limits(candidates)
        self.assertEqual(report["raw_prediction_count"], 2)
        self.assertEqual(report["accepted_position_count"], 1)
        self.assertEqual(report["rejected_position_count"], 1)
        self.assertIn("event_market_count_limit_exceeded", report["decisions"][1]["reasons"])

    def test_duplicate_and_opposing_positions_have_explicit_reasons(self):
        base = ExposureCandidate(
            prediction_id="p1",
            prediction_timestamp="2026-07-12T12:00:00Z",
            event_id="event-1",
            market_id="market-1",
            category="event",
            contract_side="yes",
            capital_at_risk_cents=100,
        )
        duplicate = ExposureCandidate(**{**base.__dict__, "prediction_id": "p2"})
        opposing = ExposureCandidate(**{**base.__dict__, "prediction_id": "p3", "contract_side": "no"})
        report = apply_exposure_limits(
            [base, duplicate, opposing],
            limits=ExposureLimits(maximum_markets_per_event=3),
        )
        self.assertIn("duplicate_market_exposure", report["decisions"][1]["reasons"])
        self.assertIn("opposing_same_market_exposure", report["decisions"][2]["reasons"])

    def test_raw_and_adjusted_performance_are_reported_separately(self):
        rows = [
            {"prediction_id": "p1", "settlement_state": "win", "profit_loss_cents": 20, "entry_price_cents": 80},
            {"prediction_id": "p2", "settlement_state": "win", "profit_loss_cents": 20, "entry_price_cents": 80},
        ]
        decisions = [
            {"prediction_id": "p1", "accepted": True},
            {"prediction_id": "p2", "accepted": False},
        ]
        report = exposure_adjusted_performance(rows, decisions)
        self.assertEqual(report["raw_prediction_performance"]["settled_count"], 2)
        self.assertEqual(report["exposure_adjusted_portfolio_performance"]["settled_count"], 1)
        self.assertEqual(report["excluded_correlated_or_limited_positions"], 1)


if __name__ == "__main__":
    unittest.main()
