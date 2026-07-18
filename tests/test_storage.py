from __future__ import annotations

from decimal import Decimal

from kalshi_research_bot.contracts import EdgeResult, SourceRecord

from tests.postgres_support import PostgresTestCase


class StorageTests(PostgresTestCase):
    def test_source_and_edge_records_use_jsonb_and_exact_numerics(self) -> None:
        store = self.store("storage")
        store.insert_source_records([SourceRecord("source", "kind", "https://example.test", "title", "text", {"value": False})])
        store.insert_edge_results([
            EdgeResult("TEST", "game", "YES", Decimal("0.6"), Decimal("55.25"), Decimal("60.5"), Decimal("5.25"), "Test market")
        ])
        source = self.query_one("SELECT metadata_json FROM app.source_records")
        edge = self.query_one("SELECT entry_price_cents, expected_value_cents FROM app.edge_results")
        self.assertEqual(source["metadata_json"], {"value": False})
        self.assertEqual(edge["entry_price_cents"], Decimal("55.25"))
        self.assertEqual(edge["expected_value_cents"], Decimal("5.25"))

    def test_prediction_validation_retains_required_audit_fields(self) -> None:
        store = self.store("prediction-validation")
        inserted = store.insert_prediction_logs([
            {
                "run_id": "stage3a-test",
                "timestamp": "2026-07-03T20:00:00+00:00",
                "event": "Detroit vs Texas",
                "market": "MKT",
                "side": "yes",
                "model_version": "test-model",
                "confidence_score": Decimal("0.69"),
                "confidence_label": "price_implied",
                "predicted_outcome": "yes",
                "event_start_time": "2026-07-04T00:00:00+00:00",
                "market_close_time": "2026-07-04T00:00:00+00:00",
                "api_fetched_at": "2026-07-03T20:00:00+00:00",
                "source_snapshot_hash": "snapshot-1",
            }
        ])
        self.assertEqual(inserted, 1)
        row = self.query_one("SELECT validation_status, settlement_state, prediction_timestamp FROM app.prediction_logs")
        self.assertEqual(row["validation_status"], "valid")
        self.assertEqual(row["settlement_state"], "unresolved")
        self.assertEqual(row["prediction_timestamp"].isoformat(), "2026-07-03T20:00:00+00:00")

    def test_missing_timing_is_rejected_and_unresolved_profit_is_cleared(self) -> None:
        store = self.store("invalid-prediction")
        store.insert_prediction_logs([
            {
                "timestamp": "2026-07-03T20:00:00+00:00",
                "event": "Detroit vs Texas",
                "market": "MKT",
                "side": "yes",
                "model_version": "test-model",
                "confidence_score": Decimal("0.69"),
                "confidence_label": "price_implied",
                "predicted_outcome": "yes",
                "settlement_state": "unresolved",
                "actual_outcome": True,
                "profit_loss_cents": Decimal("18"),
            }
        ])
        row = self.query_one("SELECT validation_status, validation_errors_json, actual_outcome, profit_loss_cents FROM app.prediction_logs")
        self.assertEqual(row["validation_status"], "invalid")
        self.assertIn("missing_run_id", row["validation_errors_json"])
        self.assertIn("missing_event_start_time", row["validation_errors_json"])
        self.assertIsNone(row["actual_outcome"])
        self.assertIsNone(row["profit_loss_cents"])
