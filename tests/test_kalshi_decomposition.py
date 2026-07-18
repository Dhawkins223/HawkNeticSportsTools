import unittest
from decimal import Decimal

from kalshi_research_bot.evaluation.kalshi_decomposition import (
    build_kalshi_return_decomposition_from_rows,
    render_kalshi_return_decomposition,
)


def _row(index, *, event_id=None, market_id=None, state="win", entry=80, strategy="primary_80"):
    event = event_id or f"KXMLB-EVENT-{index}"
    market = market_id or f"KXMLB-MARKET-{index}"
    return {
        "id": index,
        "run_id": "run-1",
        "prediction_timestamp": f"2026-07-01T{index % 20:02d}:00:00Z",
        "event": f"Game {index}",
        "event_id": event,
        "market": market,
        "market_id": market,
        "side": "yes",
        "strategy": strategy,
        "input_data_json": "{}",
        "odds_json": f'{{"ask_cents": {entry}, "bid_cents": {entry - 2}}}',
        "model_version": "market_implied_slip_v1",
        "confidence_score": 0.69,
        "predicted_outcome": "yes",
        "market_close_time": "2026-07-03T00:00:00Z",
        "source_updated_at": "2026-06-30T23:59:00Z",
        "source_snapshot_hash": f"hash-{index}",
        "snapshot_sequence": 1,
        "entry_price_cents": entry,
        "implied_probability": entry / 100,
        "reason_features_json": '{"open_interest": 100, "volume_24h": 200, "spread_cents": 2}',
        "validation_status": "valid",
        "settlement_state": state,
        "profit_loss_cents": 100 - entry if state == "win" else -entry,
    }


class KalshiDecompositionTests(unittest.TestCase):
    def test_high_accuracy_can_still_have_negative_net_return(self):
        rows = [_row(index, state="win" if index < 8 else "loss", entry=90) for index in range(10)]
        report = build_kalshi_return_decomposition_from_rows(rows, run_id="run-1")
        summary = report["market_deduped_performance"]
        self.assertEqual(summary["directional_accuracy"], Decimal("0.8"))
        self.assertLess(summary["gross_simulated_return_cents"], 0)
        self.assertLess(summary["net_simulated_return_cents"], summary["gross_simulated_return_cents"])
        self.assertGreater(report["explanation"]["average_price_break_even_accuracy_before_costs"], 0.8)

    def test_duplicate_snapshots_and_correlated_event_markets_are_separate_counts(self):
        rows = [
            _row(1, event_id="event-a", market_id="market-a"),
            _row(2, event_id="event-a", market_id="market-a", strategy="leverage_75"),
            _row(3, event_id="event-a", market_id="market-b"),
            _row(4, event_id="event-b", market_id="market-c"),
        ]
        report = build_kalshi_return_decomposition_from_rows(rows, run_id="run-1")
        self.assertEqual(report["counts"]["raw_settled_rows"], 4)
        self.assertEqual(report["counts"]["market_deduped_settled_exposures"], 3)
        self.assertEqual(report["counts"]["event_adjusted_settled_exposures"], 2)
        self.assertEqual(report["counts"]["duplicate_snapshot_or_strategy_rows"], 1)
        self.assertEqual(report["counts"]["additional_correlated_event_markets"], 1)

    def test_market_implied_rows_do_not_fake_model_edge(self):
        report = build_kalshi_return_decomposition_from_rows([_row(1)], run_id="run-1")
        summary = report["market_deduped_performance"]
        self.assertIsNone(summary["average_model_edge"])
        self.assertEqual(summary["model_edge_sample_size"], 0)

    def test_report_has_required_breakdowns_and_research_warning(self):
        report = build_kalshi_return_decomposition_from_rows([_row(1)], run_id="run-1")
        for key in (
            "price_buckets",
            "category_buckets",
            "confidence_buckets",
            "time_to_expiration_buckets",
            "liquidity_buckets",
        ):
            self.assertIn(key, report)
        rendered = render_kalshi_return_decomposition(report)
        self.assertIn("not proof of tradable profitability", rendered)
        self.assertIn("historical depth unavailable", rendered)


if __name__ == "__main__":
    unittest.main()
