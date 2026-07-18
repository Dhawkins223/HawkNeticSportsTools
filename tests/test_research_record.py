from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kalshi_research_bot.business_store import create_research_store, open_runtime_connection
from kalshi_research_bot.research_record import build_research_record


def _prediction_log(index: int, market_id: str) -> dict[str, object]:
    return {
        "run_id": "research-record-test",
        "timestamp": f"2026-07-01T12:00:{index:02d}Z",
        "event": f"Event {market_id}",
        "event_id": f"EVENT-{market_id}",
        "market": market_id,
        "market_id": market_id,
        "side": "yes",
        "strategy": "primary",
        "model_version": "research_record_fixture_v1",
        "confidence_score": 0.7,
        "confidence_label": "fixture",
        "predicted_outcome": "yes",
        "event_start_time": "2026-07-01T21:00:00Z",
        "market_close_time": "2026-07-01T22:00:00Z",
        "api_fetched_at": "2026-07-01T11:59:00Z",
        "source_updated_at": "2026-07-01T11:59:00Z",
        "source_snapshot_id": f"snapshot-{index}",
        "source_snapshot_hash": f"hash-{index}",
        "entry_price_cents": 50,
        "implied_probability": 0.5,
        "settlement_state": "unresolved",
    }


class ResearchRecordTests(unittest.TestCase):
    def test_missing_database_reports_unavailable_without_zero_rate(self) -> None:
        with patch(
            "kalshi_research_bot.research_record.open_runtime_connection",
            side_effect=RuntimeError("database unavailable"),
        ):
            record = build_research_record(db_path="unavailable-runtime", payload={})
        self.assertFalse(record["db_available"])
        self.assertEqual(record["status"], "WATCH")
        self.assertEqual(record["tracks"], [])
        self.assertIn("settled win/loss rows only", record["metric_policy"])

    def test_kalshi_record_counts_settled_only_and_sample_gates_hit_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            database = Path(tmp) / "research-record-runtime"
            store = create_research_store(database)
            store.insert_prediction_logs(
                [
                    _prediction_log(1, "MKT1"),
                    _prediction_log(2, "MKT1"),
                    _prediction_log(3, "MKT2"),
                    _prediction_log(4, "MKT3"),
                    _prediction_log(5, "MKT4"),
                    _prediction_log(6, "MKT5"),
                ]
            )
            with open_runtime_connection(database) as connection:
                connection.executemany(
                    """
                    UPDATE prediction_logs
                    SET settlement_state = ?, actual_outcome = ?, profit_loss_cents = ?
                    WHERE market_id = ?
                    """,
                    [
                        ("win", True, 50, "MKT1"),
                        ("loss", False, -50, "MKT2"),
                        ("push", None, 0, "MKT4"),
                    ],
                )
                connection.execute(
                    """
                    UPDATE prediction_logs
                    SET validation_status = 'invalid', validation_errors_json = '[\"missing_api_fetched_at\"]',
                        settlement_state = 'win', actual_outcome = TRUE, profit_loss_cents = 50
                    WHERE market_id = 'MKT5'
                    """
                )
                connection.commit()
            store.insert_prediction_rejections(
                [
                    {
                        "run_id": "research-record-test",
                        "timestamp": "2026-07-01T12:01:00Z",
                        "event": "Rejected Event",
                        "event_id": "EVENT-REJECTED",
                        "market": "MKT-REJECTED",
                        "market_id": "MKT-REJECTED",
                        "side": "yes",
                        "strategy": "primary",
                        "validation_errors": ["missing_api_fetched_at"],
                    }
                ]
            )

            record = build_research_record(
                db_path=database,
                payload={"custom_slip": {"action": "BUILD_SLIP", "leg_count": 2, "min_leg_probability": 0.8}},
            )

        kalshi = next(track for track in record["tracks"] if track["asset_class"] == "kalshi")
        self.assertEqual(kalshi["valid_rows"], 5)
        self.assertEqual(kalshi["settled_rows"], 4)
        self.assertEqual(kalshi["deduped_settled_exposures"], 3)
        self.assertEqual(kalshi["wins"], 1)
        self.assertEqual(kalshi["losses"], 1)
        self.assertEqual(kalshi["push_no_edge_or_void"], 1)
        self.assertEqual(kalshi["unresolved_rows"], 1)
        self.assertEqual(kalshi["invalid_log_rows"], 1)
        self.assertEqual(kalshi["rejected_rows"], 1)
        self.assertEqual(kalshi["observed_hit_rate"], None)
        self.assertEqual(kalshi["observed_hit_rate_raw"], 0.5)
        self.assertIn("withheld / sample too small", kalshi["hit_rate_status"])
        self.assertEqual(kalshi["rejection_reasons"], {"missing_api_fetched_at": 1})


if __name__ == "__main__":
    unittest.main()
