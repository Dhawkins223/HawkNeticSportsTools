from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.research_record import build_research_record


class ResearchRecordTests(unittest.TestCase):
    def test_missing_database_reports_unavailable_without_zero_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            record = build_research_record(db_path=Path(tmp) / "missing.sqlite", payload={})
        self.assertFalse(record["db_available"])
        self.assertEqual(record["status"], "WATCH")
        self.assertEqual(record["tracks"], [])
        self.assertIn("settled win/loss rows only", record["metric_policy"])

    def test_kalshi_record_counts_settled_only_and_sample_gates_hit_rate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "evaluation.sqlite"
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE prediction_logs (
                    id INTEGER PRIMARY KEY,
                    validation_status TEXT,
                    settlement_state TEXT,
                    actual_outcome INTEGER,
                    market_id TEXT,
                    side TEXT,
                    strategy TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE prediction_rejections (
                    id INTEGER PRIMARY KEY,
                    validation_errors_json TEXT
                )
                """
            )
            rows = [
                ("valid", "win", 1, "MKT1", "yes", "primary"),
                ("valid", "win", 1, "MKT1", "yes", "primary"),
                ("valid", "loss", 0, "MKT2", "yes", "primary"),
                ("valid", "unresolved", None, "MKT3", "yes", "primary"),
                ("valid", "push", None, "MKT4", "yes", "primary"),
                ("invalid", "win", 1, "MKT5", "yes", "primary"),
            ]
            connection.executemany(
                """
                INSERT INTO prediction_logs
                    (validation_status, settlement_state, actual_outcome, market_id, side, strategy)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            connection.execute(
                "INSERT INTO prediction_rejections (validation_errors_json) VALUES (?)",
                ('["missing_api_fetched_at"]',),
            )
            connection.commit()
            connection.close()

            record = build_research_record(
                db_path=db_path,
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
