import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.crypto_research import (
    apply_crypto_source_status,
    build_crypto_report,
    build_crypto_prediction_candidates,
    build_crypto_stage3b_audit_report,
    build_crypto_stage4_diagnostic_report,
    export_crypto_features,
    log_crypto_predictions,
    normalize_coinbase_candles,
    normalize_kraken_ohlc,
    render_crypto_stage3b_audit_report,
    render_crypto_stage4_diagnostic_report,
    settle_crypto_predictions,
    validate_crypto_prediction,
)


def _coinbase_payload(close: float = 100.0, settle_15m: float = 101.0, settle_1h: float = 102.0, open_price: float = 99.0):
    api_fetched_at = "2026-07-04T00:01:00Z"
    records = normalize_coinbase_candles(
        [
            [1783123200, min(open_price, close), max(open_price, close), open_price, close, 10.0],
            [1783124100, min(close, settle_15m), max(close, settle_15m), close, settle_15m, 11.0],
            [1783126800, min(close, settle_1h), max(close, settle_1h), close, settle_1h, 12.0],
        ],
        symbol="BTC-USD",
        api_fetched_at=api_fetched_at,
    )
    return {
        "asset_class": "crypto",
        "model_version": "crypto_research_v1",
        "strategy": "ohlcv_momentum_v1",
        "generated_at": api_fetched_at,
        "records": records,
    }


class CryptoResearchTests(unittest.TestCase):
    def test_coinbase_and_kraken_payload_normalization_and_hash(self):
        coinbase = normalize_coinbase_candles([[1783123200, 99, 101, 100, 100.5, 10]], symbol="BTC-USD", api_fetched_at="2026-07-04T00:01:00Z")
        kraken = normalize_kraken_ohlc(
            {"result": {"XXBTZUSD": [[1783123200, "100", "101", "99", "100.5", "100.2", "10", 4]]}},
            pair_key="XXBTZUSD",
            symbol="BTC-USD",
            api_fetched_at="2026-07-04T00:01:00Z",
        )
        self.assertEqual(coinbase[0]["exchange"], "coinbase")
        self.assertEqual(kraken[0]["exchange"], "kraken")
        self.assertEqual(coinbase[0]["source_snapshot_hash"], normalize_coinbase_candles([[1783123200, 99, 101, 100, 100.5, 10]], symbol="BTC-USD", api_fetched_at="2026-07-04T00:02:00Z")[0]["source_snapshot_hash"])

    def test_required_timestamps_stale_payload_and_future_candle_rejection(self):
        candidate = build_crypto_prediction_candidates(_coinbase_payload(), run_id="crypto_run")[0]
        missing = dict(candidate)
        missing["api_fetched_at"] = None
        self.assertIn("missing_api_fetched_at", validate_crypto_prediction(missing))
        naive = dict(candidate)
        naive["prediction_timestamp"] = "2026-07-04T00:01:00"
        self.assertIn("invalid_timezone", validate_crypto_prediction(naive))
        stale = dict(candidate)
        stale["api_fetched_at"] = "2026-07-03T23:00:00Z"
        self.assertIn("stale_payload", validate_crypto_prediction(stale))
        future = dict(candidate)
        future["candle_close_time"] = "2026-07-04T00:02:00Z"
        self.assertIn("future_candle_leakage", validate_crypto_prediction(future))

    def test_entry_price_and_horizons_are_created(self):
        candidates = build_crypto_prediction_candidates(_coinbase_payload(), run_id="crypto_run")
        horizons = {row["horizon"]: row for row in candidates}
        self.assertEqual(horizons["15m"]["entry_price"], 100.0)
        self.assertEqual(horizons["15m"]["settlement_time"], "2026-07-04T00:16:00Z")
        self.assertEqual(horizons["1h"]["settlement_time"], "2026-07-04T01:01:00Z")

    def test_up_down_push_and_unresolved_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "eval.sqlite"
            up_payload = _coinbase_payload(close=100.0, settle_15m=101.0, settle_1h=102.0)
            log_crypto_predictions(db, run_id="up", payload=up_payload)
            result = settle_crypto_predictions(db, run_id="up", payload=up_payload)
            self.assertEqual(result["rows_updated"], 2)
            report = build_crypto_report(db, run_id="up")
            self.assertEqual(report["deduped_wins"], 2)

            down_payload = _coinbase_payload(close=99.0, settle_15m=98.0, settle_1h=97.0, open_price=100.0)
            log_crypto_predictions(db, run_id="down", payload=down_payload)
            settle_crypto_predictions(db, run_id="down", payload=down_payload)
            self.assertEqual(build_crypto_report(db, run_id="down")["deduped_wins"], 2)

            push_payload = _coinbase_payload(close=100.0, settle_15m=100.03, settle_1h=100.03)
            log_crypto_predictions(db, run_id="push", payload=push_payload)
            settle_crypto_predictions(db, run_id="push", payload=push_payload)
            self.assertEqual(build_crypto_report(db, run_id="push")["push_no_edge_count"], 2)

            no_settlement = {"generated_at": "2026-07-04T02:00:00Z", "records": up_payload["records"][:1]}
            log_crypto_predictions(db, run_id="unresolved", payload=up_payload)
            settle_crypto_predictions(db, run_id="unresolved", payload=no_settlement)
            self.assertEqual(build_crypto_report(db, run_id="unresolved")["settled_raw_rows"], 0)

    def test_snapshot_duplicate_metric_filters_and_no_roi(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "eval.sqlite"
            payload = _coinbase_payload()
            first = log_crypto_predictions(db, run_id="snap", payload=payload)
            duplicate = log_crypto_predictions(db, run_id="snap", payload=payload)
            repeat = log_crypto_predictions(db, run_id="snap", payload=payload, prediction_timestamp="2026-07-04T00:02:00Z")
            changed_payload = _coinbase_payload(close=100.5, settle_15m=101.0, settle_1h=102.0)
            changed = log_crypto_predictions(db, run_id="snap", payload=changed_payload, prediction_timestamp="2026-07-04T00:03:00Z")
            self.assertEqual(first["logged_predictions"], 2)
            self.assertEqual(duplicate["rejection_reasons"].get("exact_duplicate"), 2)
            self.assertEqual(repeat["rejection_reasons"].get("unchanged_repeat_snapshot"), 2)
            self.assertEqual(changed["logged_predictions"], 2)
            settle_crypto_predictions(db, run_id="snap", payload=_coinbase_payload(settle_15m=101, settle_1h=102))
            report = build_crypto_report(db, run_id="snap")
            self.assertIn("ROI unavailable", report["roi_status"])
            self.assertIn("insufficient_sample", report["sample_size_status"])
            self.assertEqual(report["rejected_predictions"], 4)

    def test_feature_export_excludes_leakage_fields_and_keeps_labels_separate(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "eval.sqlite"
            payload = _coinbase_payload()
            log_crypto_predictions(db, run_id="export", payload=payload)
            settle_crypto_predictions(db, run_id="export", payload=payload)
            features = Path(directory) / "features.csv"
            labels = Path(directory) / "labels.csv"
            result = export_crypto_features(db, run_id="export", output=features, labels_output=labels)
            self.assertEqual(result["feature_rows"], 2)
            with features.open(newline="", encoding="utf-8") as handle:
                header = next(csv.reader(handle))
            self.assertNotIn("actual_outcome", header)
            self.assertNotIn("settlement_price", header)
            with labels.open(newline="", encoding="utf-8") as handle:
                label_header = next(csv.reader(handle))
            self.assertIn("actual_outcome", label_header)

    def test_source_errors_are_reported_as_blockers_without_fake_rows(self):
        report = {"blockers": [], "run_id": "blocked", "next_automatic_action": "continue"}
        payload = {"records": [], "errors": [{"exchange": "coinbase", "error": "URLError"}]}
        updated = apply_crypto_source_status(report, payload)
        self.assertEqual(updated["heartbeat_status"], "blocked_by_source")
        self.assertEqual(updated["source_error_count"], 1)
        self.assertIn("URLError", updated["blockers"])

    def test_stage3b_audit_is_deduped_and_research_only(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "eval.sqlite"
            payload = _coinbase_payload()
            down_payload = _coinbase_payload(close=100, settle_15m=99, settle_1h=98, open_price=101)
            log_crypto_predictions(db, run_id="audit", payload=payload)
            settle_crypto_predictions(db, run_id="audit", payload=payload)
            log_crypto_predictions(db, run_id="audit", payload=down_payload)
            settle_crypto_predictions(db, run_id="audit", payload=down_payload)
            audit = build_crypto_stage3b_audit_report(db, run_id="audit")
            rendered = render_crypto_stage3b_audit_report(audit)
            self.assertEqual(audit["primary_view"], "de-duped settled exposures")
            self.assertEqual(audit["settled_deduped_exposures"], 4)
            self.assertEqual(audit["total_deduped_predictions"], 4)
            self.assertEqual(audit["deduped_push_no_edge_count"], 0)
            self.assertIsNotNone(audit["median_return_bps"])
            self.assertEqual(audit["audit_status"], "not_ready_blocked_sample_size")
            self.assertIn("ROI unavailable", audit["roi_status"])
            self.assertEqual(audit["brier_status"], "unavailable_no_probability_predictions")
            self.assertEqual(audit["calibration_status"], "unavailable_no_probability_predictions")
            self.assertEqual(audit["calibration_bucket_sample_sizes"], {})
            self.assertEqual({row["symbol"] for row in audit["by_symbol_performance"]}, {"BTC-USD"})
            self.assertEqual({row["horizon"] for row in audit["by_horizon_performance"]}, {"15m", "1h"})
            self.assertEqual({row["side"] for row in audit["by_side_performance"]}, {"UP", "DOWN"})
            self.assertTrue(audit["outcome_clusters"]["best"])
            self.assertTrue(audit["outcome_clusters"]["worst"])
            self.assertTrue(audit["leakage_checks"]["unresolved_rows_excluded_from_metrics"])
            self.assertTrue(audit["leakage_checks"]["rejected_rows_excluded_from_metrics"])
            self.assertTrue(audit["leakage_checks"]["duplicate_snapshots_not_inflating_deduped_performance"])
            self.assertEqual(audit["leakage_checks"]["future_candle_leakage_count"], 0)
            self.assertEqual(audit["leakage_checks"]["feature_export_leakage_status"], "pass")
            self.assertEqual(audit["duplicate_snapshot_impact"]["metric_policy"], "de-duped settled exposures are the primary audit view; repeated snapshots do not inflate readiness")
            self.assertIn("inconclusive", audit["result_assessment"])
            self.assertIn("No profitability, edge", rendered)
            self.assertIn("Total de-duped predictions", rendered)
            self.assertIn("Median return_bps", rendered)
            self.assertIn("Symbol breakdown", rendered)
            self.assertIn("Side breakdown", rendered)
            self.assertIn("Calibration buckets", rendered)
            self.assertIn("Calibration bucket sample sizes", rendered)
            self.assertIn("Best outcome clusters", rendered)
            self.assertIn("Worst outcome clusters", rendered)
            self.assertIn("Validation/leakage checks", rendered)
            self.assertIn("This audit is not proof of tradable profitability", rendered)

    def test_stage4_diagnostic_segments_costs_and_blocks_model_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "eval.sqlite"
            payload = _coinbase_payload()
            down_payload = _coinbase_payload(close=100, settle_15m=99, settle_1h=98, open_price=101)
            log_crypto_predictions(db, run_id="stage4", payload=payload)
            settle_crypto_predictions(db, run_id="stage4", payload=payload)
            log_crypto_predictions(db, run_id="stage4", payload=down_payload)
            settle_crypto_predictions(db, run_id="stage4", payload=down_payload)

            diagnostic = build_crypto_stage4_diagnostic_report(db, run_id="stage4")
            rendered = render_crypto_stage4_diagnostic_report(diagnostic)

            self.assertEqual(diagnostic["stage4_status"], "controlled_diagnosis_only_no_model_change")
            self.assertFalse(diagnostic["decision"]["model_change_justified_now"])
            self.assertTrue(diagnostic["decision"]["more_data_needed_before_rule_changes"])
            self.assertIn("1_bps_round_trip", diagnostic["decision"]["fee_slippage_sensitivity"])
            self.assertEqual(
                set(diagnostic["segment_tables"]),
                {
                    "symbol",
                    "horizon",
                    "side",
                    "symbol_horizon",
                    "symbol_side",
                    "horizon_side",
                    "time_of_day_bucket",
                    "volatility_bucket",
                    "spread_bucket",
                },
            )
            for table in diagnostic["segment_tables"].values():
                for row in table:
                    self.assertIn("raw_count", row)
                    self.assertIn("settled_count", row)
                    self.assertIn("de_duped_settled_count", row)
                    self.assertIn("fee_slippage_sensitivity", row)
                    self.assertIn("classification", row)
            self.assertEqual(diagnostic["leakage_checks"]["feature_export_leakage_status"], "pass")
            self.assertIn("Segment table: symbol + horizon", rendered)
            self.assertIn("Fee/slippage sensitivity estimate (not ROI, not profitability)", rendered)
            self.assertIn("No ML training was run", rendered)
            self.assertIn("No live prediction logic was changed", rendered)
            self.assertIn("This diagnostic is not proof of tradable profitability", rendered)


if __name__ == "__main__":
    unittest.main()
