from __future__ import annotations

import csv
import tempfile
from pathlib import Path

from kalshi_research_bot.crypto_research import (
    apply_crypto_source_status,
    build_crypto_prediction_candidates,
    build_crypto_report,
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

from tests.postgres_support import PostgresTestCase


def _payload(*, close: float = 100.0, settle_15m: float = 101.0, settle_1h: float = 102.0, open_price: float = 99.0) -> dict:
    fetched_at = "2026-07-04T00:01:00+00:00"
    records = normalize_coinbase_candles(
        [
            [1783123200, min(open_price, close), max(open_price, close), open_price, close, 10.0],
            [1783124100, min(close, settle_15m), max(close, settle_15m), close, settle_15m, 11.0],
            [1783126800, min(close, settle_1h), max(close, settle_1h), close, settle_1h, 12.0],
        ],
        symbol="BTC-USD",
        api_fetched_at=fetched_at,
    )
    return {"asset_class": "crypto", "model_version": "crypto_research_v1", "strategy": "ohlcv_momentum_v1", "generated_at": fetched_at, "records": records}


class CryptoResearchTests(PostgresTestCase):
    def test_exchange_normalization_and_timestamp_validation(self) -> None:
        coinbase = normalize_coinbase_candles([[1783123200, 99, 101, 100, 100.5, 10]], symbol="BTC-USD", api_fetched_at="2026-07-04T00:01:00+00:00")
        kraken = normalize_kraken_ohlc({"result": {"XXBTZUSD": [[1783123200, "100", "101", "99", "100.5", "100.2", "10", 4]]}}, pair_key="XXBTZUSD", symbol="BTC-USD", api_fetched_at="2026-07-04T00:01:00+00:00")
        candidate = build_crypto_prediction_candidates(_payload(), run_id="validation")[0]
        self.assertEqual(coinbase[0]["exchange"], "coinbase")
        self.assertEqual(kraken[0]["exchange"], "kraken")
        self.assertIn("missing_api_fetched_at", validate_crypto_prediction({**candidate, "api_fetched_at": None}))
        self.assertIn("future_candle_leakage", validate_crypto_prediction({**candidate, "candle_close_time": "2026-07-04T00:02:00+00:00"}))

    def test_predictions_settle_and_reports_exclude_unresolved_rows(self) -> None:
        payload = _payload()
        logged = log_crypto_predictions(run_id="settle", payload=payload)
        settled = settle_crypto_predictions(run_id="settle", payload=payload)
        report = build_crypto_report(run_id="settle")
        self.assertEqual(logged["logged_predictions"], 2)
        self.assertEqual(settled["rows_updated"], 2)
        self.assertEqual(report["settled_deduped_exposures"], 2)
        self.assertEqual(report["deduped_wins"], 2)
        self.assertIn("unavailable", report["roi_status"].lower())

    def test_repeat_is_rejected_and_source_failure_never_creates_rows(self) -> None:
        payload = _payload()
        first = log_crypto_predictions(run_id="repeat", payload=payload)
        repeated = log_crypto_predictions(run_id="repeat", payload=payload)
        source = apply_crypto_source_status({"blockers": [], "run_id": "blocked", "next_automatic_action": "continue"}, {"records": [], "errors": [{"exchange": "coinbase", "error": "URLError"}]})
        self.assertEqual(first["logged_predictions"], 2)
        self.assertEqual(repeated["logged_predictions"], 0)
        self.assertEqual(repeated["rejection_reasons"].get("exact_duplicate"), 2)
        self.assertEqual(source["heartbeat_status"], "blocked_by_source")
        self.assertEqual(self.query_one("SELECT COUNT(*) AS total FROM app.crypto_prediction_logs WHERE run_id = %s", ("blocked",))["total"], 0)

    def test_snapshot_hash_is_stable_across_fetch_time(self) -> None:
        first = normalize_coinbase_candles(
            [[1783123200, 99, 101, 100, 100.5, 10]],
            symbol="BTC-USD",
            api_fetched_at="2026-07-04T00:01:00+00:00",
        )
        second = normalize_coinbase_candles(
            [[1783123200, 99, 101, 100, 100.5, 10]],
            symbol="BTC-USD",
            api_fetched_at="2026-07-04T00:02:00+00:00",
        )
        self.assertEqual(first[0]["source_snapshot_hash"], second[0]["source_snapshot_hash"])

    def test_entry_prices_and_settlement_horizons_are_explicit(self) -> None:
        horizons = {row["horizon"]: row for row in build_crypto_prediction_candidates(_payload(), run_id="horizons")}
        self.assertEqual(horizons["15m"]["entry_price"], 100)
        self.assertEqual(horizons["15m"]["settlement_time"], "2026-07-04T00:16:00Z")
        self.assertEqual(horizons["1h"]["settlement_time"], "2026-07-04T01:01:00Z")

    def test_push_and_unresolved_states_do_not_become_losses(self) -> None:
        push_payload = _payload(close=100.0, settle_15m=100.03, settle_1h=100.03)
        self.assertEqual(log_crypto_predictions(run_id="push", payload=push_payload)["logged_predictions"], 2)
        self.assertEqual(settle_crypto_predictions(run_id="push", payload=push_payload)["rows_updated"], 2)
        self.assertEqual(build_crypto_report(run_id="push")["push_no_edge_count"], 2)

        unresolved_payload = {"generated_at": "2026-07-04T02:00:00+00:00", "records": _payload()["records"][:1]}
        self.assertEqual(log_crypto_predictions(run_id="unresolved", payload=_payload())["logged_predictions"], 2)
        self.assertEqual(settle_crypto_predictions(run_id="unresolved", payload=unresolved_payload)["rows_updated"], 0)
        self.assertEqual(build_crypto_report(run_id="unresolved")["settled_raw_rows"], 0)

    def test_changed_snapshot_logs_and_report_stays_nonfinancial(self) -> None:
        original = _payload()
        changed = _payload(close=100.5, settle_15m=101.0, settle_1h=102.0)
        self.assertEqual(log_crypto_predictions(run_id="snapshots", payload=original)["logged_predictions"], 2)
        unchanged = log_crypto_predictions(
            run_id="snapshots",
            payload=original,
            prediction_timestamp="2026-07-04T00:02:00+00:00",
        )
        changed_result = log_crypto_predictions(
            run_id="snapshots",
            payload=changed,
            prediction_timestamp="2026-07-04T00:03:00+00:00",
        )
        settle_crypto_predictions(run_id="snapshots", payload=_payload())
        report = build_crypto_report(run_id="snapshots")
        self.assertEqual(unchanged["rejection_reasons"].get("unchanged_repeat_snapshot"), 2)
        self.assertEqual(changed_result["logged_predictions"], 2)
        self.assertIn("unavailable", report["roi_status"].lower())
        self.assertIn("insufficient_sample", report["sample_size_status"])

    def test_feature_export_keeps_outcomes_outside_feature_file(self) -> None:
        payload = _payload()
        log_crypto_predictions(run_id="features", payload=payload)
        settle_crypto_predictions(run_id="features", payload=payload)
        with tempfile.TemporaryDirectory() as directory:
            features = Path(directory) / "features.csv"
            labels = Path(directory) / "labels.csv"
            result = export_crypto_features(run_id="features", output=features, labels_output=labels)
            with features.open(newline="", encoding="utf-8") as handle:
                feature_header = next(csv.reader(handle))
            with labels.open(newline="", encoding="utf-8") as handle:
                label_header = next(csv.reader(handle))
        self.assertEqual(result["feature_rows"], 2)
        self.assertNotIn("actual_outcome", feature_header)
        self.assertNotIn("settlement_price", feature_header)
        self.assertIn("actual_outcome", label_header)

    def test_stage_three_audit_is_deduped_and_research_only(self) -> None:
        upward = _payload()
        downward = _payload(close=100.0, settle_15m=99.0, settle_1h=98.0, open_price=101.0)
        log_crypto_predictions(run_id="audit", payload=upward)
        settle_crypto_predictions(run_id="audit", payload=upward)
        log_crypto_predictions(run_id="audit", payload=downward)
        settle_crypto_predictions(run_id="audit", payload=downward)
        audit = build_crypto_stage3b_audit_report(run_id="audit")
        self.assertEqual(audit["primary_view"], "de-duped settled exposures")
        self.assertEqual(audit["settled_deduped_exposures"], 4)
        self.assertEqual(audit["audit_status"], "not_ready_blocked_sample_size")
        self.assertIn("No profitability, edge", render_crypto_stage3b_audit_report(audit))

    def test_stage_four_diagnostics_prohibit_model_change(self) -> None:
        upward = _payload()
        downward = _payload(close=100.0, settle_15m=99.0, settle_1h=98.0, open_price=101.0)
        log_crypto_predictions(run_id="diagnostic", payload=upward)
        settle_crypto_predictions(run_id="diagnostic", payload=upward)
        log_crypto_predictions(run_id="diagnostic", payload=downward)
        settle_crypto_predictions(run_id="diagnostic", payload=downward)
        diagnostic = build_crypto_stage4_diagnostic_report(run_id="diagnostic")
        self.assertEqual(diagnostic["stage4_status"], "controlled_diagnosis_only_no_model_change")
        self.assertFalse(diagnostic["decision"]["model_change_justified_now"])
        self.assertTrue(diagnostic["decision"]["more_data_needed_before_rule_changes"])
        self.assertIn("No ML training was run", render_crypto_stage4_diagnostic_report(diagnostic))
