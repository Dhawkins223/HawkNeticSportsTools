import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.combo_safety import VERIFIED_COMBO_EVIDENCE, VERIFIED_COMBO_SOURCE, combo_leg_signature
from kalshi_research_bot.evaluation import (
    build_backtest_report,
    confidence_guardrail,
    data_quality_failures,
    extract_prediction_logs_from_payload,
    run_backtest,
)
from kalshi_research_bot.evaluation.quality import prediction_validation_errors
from kalshi_research_bot.business_store import create_research_store, open_runtime_connection


ResearchStore = create_research_store


def _snapshot(index, *, probability=0.8, snapshot_at="2026-07-03T15:00:00Z"):
    return {
        "snapshot_at": snapshot_at,
        "event": {
            "event_id": f"game-{index}",
            "name": f"Game {index}",
            "start_time": "2026-07-03T20:00:00Z",
        },
        "market": {
            "ticker": f"MKT{index}",
            "side": "yes",
            "yes_bid_cents": 49,
            "yes_ask_cents": 50,
            "no_ask_cents": 52,
            "close_time": "2026-07-03T20:00:00Z",
            "updated_time": "2026-07-03T14:55:00Z",
        },
        "prediction": {
            "side": "yes",
            "probability": probability,
            "model_version": "fixture_model_v1",
            "evidence_count": 2,
            "source_backed": True,
            "margin_of_error": 0.04,
        },
    }


def _prediction(index, *, state="win", strategy="primary_80", confidence=0.8):
    actual = state == "win"
    profit = 50.0 if actual else -50.0
    return {
        "prediction_id": f"pred-{index}-{strategy}",
        "timestamp": "2026-07-03T15:00:00Z",
        "event": f"Game {index}",
        "event_id": f"game-{index}",
        "market": f"MKT{index}",
        "side": "yes",
        "strategy": strategy,
        "model_version": "test",
        "confidence_score": confidence,
        "predicted_probability": confidence,
        "predicted_outcome": "yes",
        "entry_price_cents": 50,
        "settlement_state": state,
        "actual_outcome": actual if state in {"win", "loss"} else None,
        "profit_loss_cents": profit if state in {"win", "loss"} else None,
    }


class EvaluationTests(unittest.TestCase):
    def test_blocks_lookahead_and_post_start_snapshots(self):
        snapshot = {
            "snapshot_at": "2026-07-03T21:00:00Z",
            "event": {"event_id": "game-1", "start_time": "2026-07-03T20:00:00Z"},
            "market": {"ticker": "MKT", "side": "yes", "yes_ask_cents": 60, "no_ask_cents": 42, "close_time": "2026-07-03T20:00:00Z"},
            "prediction": {"side": "yes", "probability": 0.6},
            "features": {"final_score": "7-4"},
        }
        failures = data_quality_failures(snapshot)
        self.assertIn("snapshot_not_before_event_start", failures)
        self.assertIn("lookahead_field:final_score", failures)

    def test_prediction_validation_requires_pre_event_timing_fields(self):
        missing = prediction_validation_errors({"timestamp": "2026-07-03T16:00:00Z"})
        self.assertIn("missing_run_id", missing)
        self.assertIn("missing_event_start_time", missing)
        self.assertIn("missing_market_close_time", missing)

        late = prediction_validation_errors(
            {
                "timestamp": "2026-07-03T20:00:00Z",
                "run_id": "run",
                "event_start_time": "2026-07-03T20:00:00Z",
                "market_close_time": "2026-07-03T20:00:00Z",
            }
        )
        self.assertIn("prediction_after_event_start", late)

        after_close = prediction_validation_errors(
            {
                "timestamp": "2026-07-03T19:00:00Z",
                "run_id": "run",
                "event_start_time": "2026-07-03T20:00:00Z",
                "market_close_time": "2026-07-03T19:00:00Z",
            }
        )
        self.assertIn("prediction_after_market_close", after_close)

    def test_confidence_guardrail_blocks_market_only_high_confidence(self):
        result = confidence_guardrail(probability=0.91, evidence_count=0, source_backed=False, spread_cents=2)
        self.assertFalse(result["high_confidence_allowed"])
        self.assertEqual(result["label"], "price_implied")
        self.assertIn("market_implied_only", result["reasons"])

    def test_confidence_guardrail_allows_source_backed_evidence(self):
        result = confidence_guardrail(probability=0.84, evidence_count=2, source_backed=True, spread_cents=2, margin_of_error=0.04)
        self.assertTrue(result["high_confidence_allowed"])
        self.assertEqual(result["label"], "high_confidence")

    def test_backtest_uses_latest_pre_event_snapshot_and_labels_tiny_sample(self):
        payload = {
            "snapshots": [
                _snapshot(1, probability=0.79, snapshot_at="2026-07-03T15:00:00Z"),
                _snapshot(1, probability=0.81, snapshot_at="2026-07-03T19:00:00Z"),
                {
                    "snapshot_at": "2026-07-03T20:01:00Z",
                    "event": {"event_id": "game-2", "name": "Leak", "start_time": "2026-07-03T20:00:00Z"},
                    "market": {"ticker": "MKT2", "side": "yes", "yes_ask_cents": 60, "no_ask_cents": 42, "close_time": "2026-07-03T20:00:00Z"},
                    "prediction": {"side": "yes", "probability": 0.6},
                    "features": {"winner": "home"},
                },
            ],
            "outcomes": [{"event_id": "game-1", "market": "MKT1", "winning_side": "yes"}],
        }
        report = run_backtest(payload)
        self.assertEqual(report["total_picks_tested"], 1)
        self.assertIsNone(report["win_rate"])
        self.assertIsNone(report["roi_fee_excluded"])
        self.assertEqual(report["performance_sample_status"], "insufficient_sample (1/100)")
        self.assertEqual(report["prediction_logs"][0]["timestamp"], "2026-07-03T19:00:00Z")
        self.assertTrue(report["data_quality_failures"])
        self.assertIsNone(report["brier_score"])

    def test_backtest_supports_settlement_states_and_keeps_unresolved_pl_empty(self):
        payload = {
            "snapshots": [_snapshot(index) for index in range(1, 9)],
            "outcomes": [
                {"event_id": "game-1", "market": "MKT1", "winning_side": "yes"},
                {"event_id": "game-2", "market": "MKT2", "winning_side": "no"},
                {"event_id": "game-3", "market": "MKT3", "settlement_state": "push"},
                {"event_id": "game-4", "market": "MKT4", "settlement_state": "void"},
                {"event_id": "game-5", "market": "MKT5", "settlement_state": "cancelled"},
                {"event_id": "game-6", "market": "MKT6", "settlement_state": "fair_market", "fair_market_price_cents": 45},
                {"event_id": "game-7", "market": "MKT7", "settlement_state": "early_exit", "exit_price_cents": 65},
            ],
        }
        report = run_backtest(payload)
        states = {row["market"]: row["settlement_state"] for row in report["prediction_logs"]}
        self.assertEqual(states["MKT1"], "win")
        self.assertEqual(states["MKT2"], "loss")
        self.assertEqual(states["MKT3"], "push")
        self.assertEqual(states["MKT4"], "void")
        self.assertEqual(states["MKT5"], "cancelled")
        self.assertEqual(states["MKT6"], "fair_market")
        self.assertEqual(states["MKT7"], "early_exit")
        self.assertEqual(states["MKT8"], "unresolved")
        unresolved = next(row for row in report["prediction_logs"] if row["market"] == "MKT8")
        self.assertIsNone(unresolved["actual_outcome"])
        self.assertIsNone(unresolved["profit_loss_cents"])
        self.assertEqual(report["unresolved_predictions"], 1)
        self.assertEqual(report["win_loss_predictions"], 2)

    def test_report_dedupes_market_exposure_and_gates_samples(self):
        insufficient = build_backtest_report([_prediction(index) for index in range(29)])
        self.assertIsNone(insufficient["win_rate"])
        self.assertIsNone(insufficient["roi_fee_excluded"])
        self.assertEqual(insufficient["performance_sample_status"], "insufficient_sample (29/100)")
        self.assertIsNone(insufficient["confidence_bucket_performance"]["75-85"]["win_rate"])

        sufficient = build_backtest_report(
            [_prediction(index, state="win" if index % 2 == 0 else "loss") for index in range(100)]
        )
        self.assertEqual(sufficient["performance_sample_status"], "sufficient_sample")
        self.assertEqual(sufficient["win_rate"], 0.5)
        self.assertEqual(sufficient["roi_fee_excluded"], 0.0)
        self.assertEqual(sufficient["confidence_bucket_performance"]["75-85"]["sample_status"], "sufficient_sample")

        duplicate = build_backtest_report(
            [
                _prediction(1, strategy="primary_80"),
                _prediction(1, strategy="all_day_75_85"),
            ]
        )
        self.assertEqual(duplicate["total_predictions"], 2)
        self.assertEqual(duplicate["overall_predictions_after_dedupe"], 1)
        self.assertEqual(duplicate["duplicate_market_exposures"][0]["count"], 2)
        self.assertEqual(duplicate["duplicate_market_exposures"][0]["strategies"], ["all_day_75_85", "primary_80"])

    def test_extract_and_store_prediction_logs_with_pre_event_proof(self):
        leg = {
            "display_event": "Detroit vs Texas",
            "event_ticker": "EVT",
            "market_ticker": "MKT",
            "side": "yes",
            "probability": 0.82,
            "ask_cents": 83,
            "bid_cents": 81,
            "spread_cents": 2,
            "event_start_time": "2026-07-03T20:00:00-04:00",
            "market_close_time": "2026-07-03T20:00:00-04:00",
            "market_updated_at": "2026-07-03T15:55:00-04:00",
        }
        leg.update(
            {
                "combo_eligible": True,
                "combo_market_ticker": "KXMVE-TEST",
                "combo_market_status": "active",
                "combo_market_yes_ask_cents": 50,
                "combo_market_fetched_at": "2026-07-03T16:00:00-04:00",
                "combo_market_snapshot_hash": "sha256:test-combo",
                "combo_market_leg_signature": combo_leg_signature([leg]),
                "combo_exact_leg_count": 1,
                "combo_evidence_status": VERIFIED_COMBO_EVIDENCE,
                "combo_source": VERIFIED_COMBO_SOURCE,
            }
        )
        payload = {
            "generated_at": "2026-07-03T16:00:00-04:00",
            "custom_slip": {
                "action": "BUILD_SLIP",
                "min_leg_probability": 0.8,
                "adjusted_probability": 0.65,
                "combo_compatibility": {"status": "compatible", "exact_listed_combo": True},
                "listed_combo_market_ticker": "KXMVE-TEST",
                "legs": [leg],
            },
        }
        logs = extract_prediction_logs_from_payload(payload, run_id="stage3a_test")
        self.assertEqual(len(logs), 1)
        self.assertEqual(logs[0]["actual_outcome"], None)
        self.assertEqual(logs[0]["settlement_state"], "unresolved")
        self.assertEqual(logs[0]["validation_status"], "valid")
        self.assertEqual(logs[0]["run_id"], "stage3a_test")
        self.assertEqual(logs[0]["event_start_time"], "2026-07-03T20:00:00-04:00")
        self.assertEqual(logs[0]["market_close_time"], "2026-07-03T20:00:00-04:00")
        self.assertEqual(logs[0]["api_fetched_at"], "2026-07-03T16:00:00-04:00")
        self.assertTrue(logs[0]["source_snapshot_id"])

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "evaluation-runtime"
            ResearchStore(path).insert_prediction_logs(logs)
            connection = open_runtime_connection(path)
            try:
                row = connection.execute(
                    """
                    SELECT event_start_time, market_close_time, api_fetched_at,
                           source_updated_at, source_snapshot_id, validation_status,
                           settlement_state, profit_loss_cents
                    FROM prediction_logs
                    """
                ).fetchone()
            finally:
                connection.close()
        self.assertEqual(row[0], "2026-07-04 00:00:00+00:00")
        self.assertEqual(row[1], "2026-07-04 00:00:00+00:00")
        self.assertEqual(row[2], "2026-07-03 20:00:00+00:00")
        self.assertEqual(row[3], "2026-07-03 19:55:00+00:00")
        self.assertTrue(row[4])
        self.assertEqual(row[5], "valid")
        self.assertEqual(row[6], "unresolved")
        self.assertIsNone(row[7])


if __name__ == "__main__":
    unittest.main()
