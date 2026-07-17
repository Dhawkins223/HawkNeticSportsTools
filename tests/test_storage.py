import json
import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.business_store import create_research_store
from kalshi_research_bot.contracts import EdgeResult


class PostgresRuntimeStoreTests(unittest.TestCase):
    def test_insert_edge_results_uses_postgres_without_creating_a_local_database_file(self):
        with tempfile.TemporaryDirectory() as directory:
            database_key = Path(directory) / "research-runtime"
            store = create_research_store(database_key)
            store.insert_edge_results(
                [
                    EdgeResult(
                        ticker="TEST",
                        game_id="game-1",
                        side="YES",
                        model_probability=0.60,
                        entry_price_cents=55,
                        fair_price_cents=60,
                        expected_value_cents=5,
                        title="Test market",
                    )
                ]
            )
            self.assertFalse(database_key.exists())
            with store.connect() as connection:
                count = connection.execute("SELECT COUNT(*) FROM edge_results").fetchone()[0]
            self.assertEqual(count, 1)

    def test_prediction_logs_record_required_audit_fields_in_postgres(self):
        with tempfile.TemporaryDirectory() as directory:
            store = create_research_store(Path(directory) / "audit-fields")
            store.insert_prediction_logs(
                [
                    {
                        "run_id": "stage3a_test",
                        "timestamp": "2026-07-03T16:00:00-04:00",
                        "event": "Detroit vs Texas",
                        "market": "MKT",
                        "side": "yes",
                        "input_data_used": {"market": "MKT"},
                        "odds_used": {"ask_cents": 82},
                        "model_version": "test_model_v1",
                        "confidence_score": 0.69,
                        "confidence_label": "price_implied",
                        "predicted_outcome": "yes",
                        "event_start_time": "2026-07-03T20:00:00-04:00",
                        "market_close_time": "2026-07-03T20:00:00-04:00",
                        "api_fetched_at": "2026-07-03T16:00:00-04:00",
                        "source_updated_at": "2026-07-03T15:59:00-04:00",
                        "source_snapshot_id": "snapshot-1",
                        "actual_outcome": None,
                        "profit_loss_cents": None,
                    }
                ]
            )
            with store.connect() as connection:
                row = connection.execute(
                    """
                    SELECT prediction_timestamp, event, market, model_version,
                           confidence_label, validation_status, settlement_state,
                           event_start_time, market_close_time
                    FROM prediction_logs
                    """
                ).fetchone()
            self.assertEqual(row[1], "Detroit vs Texas")
            self.assertEqual(row[2], "MKT")
            self.assertEqual(row[3], "test_model_v1")
            self.assertEqual(row[4], "price_implied")
            self.assertEqual(row[5], "valid")
            self.assertEqual(row[6], "unresolved")
            self.assertEqual(str(row[0]), "2026-07-03 20:00:00+00:00")
            self.assertEqual(str(row[7]), "2026-07-04 00:00:00+00:00")
            self.assertEqual(str(row[8]), "2026-07-04 00:00:00+00:00")

    def test_prediction_log_insert_marks_missing_timing_invalid_and_clears_unresolved_profit_loss(self):
        with tempfile.TemporaryDirectory() as directory:
            store = create_research_store(Path(directory) / "invalid-timing")
            store.insert_prediction_logs(
                [
                    {
                        "timestamp": "2026-07-03T16:00:00-04:00",
                        "event": "Detroit vs Texas",
                        "market": "MKT",
                        "side": "yes",
                        "input_data_used": {"market": "MKT"},
                        "odds_used": {"ask_cents": 82},
                        "model_version": "test_model_v1",
                        "confidence_score": 0.69,
                        "confidence_label": "price_implied",
                        "predicted_outcome": "yes",
                        "settlement_state": "unresolved",
                        "actual_outcome": True,
                        "profit_loss_cents": 18.0,
                    }
                ]
            )
            with store.connect() as connection:
                row = connection.execute(
                    "SELECT validation_status, validation_errors_json, actual_outcome, profit_loss_cents FROM prediction_logs"
                ).fetchone()
            self.assertEqual(row[0], "invalid")
            self.assertIn("missing_run_id", json.loads(row[1]))
            self.assertIn("missing_event_start_time", json.loads(row[1]))
            self.assertIn("missing_market_close_time", json.loads(row[1]))
            self.assertIsNone(row[2])
            self.assertIsNone(row[3])


if __name__ == "__main__":
    unittest.main()
