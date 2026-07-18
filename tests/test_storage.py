import json
import tempfile
import unittest
from pathlib import Path
import sqlite3

from kalshi_research_bot.contracts import EdgeResult
from kalshi_research_bot.storage import ResearchStore


class StorageTests(unittest.TestCase):
    def test_insert_edge_results_creates_database(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.sqlite"
            store = ResearchStore(path)
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
            self.assertTrue(path.exists())

    def test_insert_prediction_logs_records_required_audit_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.sqlite"
            ResearchStore(path).insert_prediction_logs(
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
            connection = sqlite3.connect(path)
            try:
                row = connection.execute(
                    """
                    SELECT prediction_timestamp, event, market, model_version,
                           confidence_label, validation_status, settlement_state,
                           event_start_time, market_close_time
                    FROM prediction_logs
                    """
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(
                row,
                (
                    "2026-07-03T16:00:00-04:00",
                    "Detroit vs Texas",
                    "MKT",
                    "test_model_v1",
                    "price_implied",
                    "valid",
                    "unresolved",
                    "2026-07-03T20:00:00-04:00",
                    "2026-07-03T20:00:00-04:00",
                ),
            )
            ResearchStore(path).initialize()
            connection = sqlite3.connect(path)
            try:
                status = connection.execute("SELECT validation_status FROM prediction_logs").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(status, "valid")

    def test_prediction_log_insert_marks_missing_timing_invalid_and_clears_unresolved_pl(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.sqlite"
            ResearchStore(path).insert_prediction_logs(
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
            connection = sqlite3.connect(path)
            try:
                row = connection.execute(
                    "SELECT validation_status, validation_errors_json, actual_outcome, profit_loss_cents FROM prediction_logs"
                ).fetchone()
            finally:
                connection.close()
            self.assertEqual(row[0], "invalid")
            self.assertIn("missing_run_id", json.loads(row[1]))
            self.assertIn("missing_event_start_time", json.loads(row[1]))
            self.assertIn("missing_market_close_time", json.loads(row[1]))
            self.assertIsNone(row[2])
            self.assertIsNone(row[3])


if __name__ == "__main__":
    unittest.main()
