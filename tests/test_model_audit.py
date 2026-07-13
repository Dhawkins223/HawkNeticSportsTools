import sqlite3
import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.evaluation.model_audit import (
    build_platform_model_audit,
    render_platform_model_audit,
)
from kalshi_research_bot.storage import ResearchStore


class ModelAuditTests(unittest.TestCase):
    def test_workflows_remain_separate_and_market_only_rows_are_not_fake_models(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "audit.sqlite"
            store = ResearchStore(database)
            rows = []
            for index in range(20):
                rows.append(
                    {
                        "run_id": "kalshi-run",
                        "timestamp": f"2026-01-{index + 1:02d}T12:00:00Z",
                        "event": f"Game {index}",
                        "event_id": f"KXMLB-EVENT-{index}",
                        "market": f"KXMLB-MARKET-{index}",
                        "market_id": f"KXMLB-MARKET-{index}",
                        "side": "yes",
                        "strategy": "baseline",
                        "model_version": "market_implied_slip_v1",
                        "confidence_score": 0.69,
                        "confidence_label": "market",
                        "predicted_outcome": "yes",
                        "event_start_time": "2026-02-01T12:00:00Z",
                        "market_close_time": "2026-02-01T12:00:00Z",
                        "api_fetched_at": f"2026-01-{index + 1:02d}T11:59:00Z",
                        "source_updated_at": f"2026-01-{index + 1:02d}T11:59:00Z",
                        "entry_price_cents": 60,
                        "implied_probability": 0.6,
                    }
                )
            store.insert_prediction_logs(rows)
            connection = sqlite3.connect(database)
            try:
                connection.execute(
                    """
                    UPDATE prediction_logs SET settlement_state = 'win', actual_outcome = 1,
                        profit_loss_cents = 40, settlement_updated_at = '2026-03-01T00:00:00Z'
                    """
                )
                connection.commit()
            finally:
                connection.close()
            report = build_platform_model_audit(
                database,
                kalshi_run_id="kalshi-run",
                crypto_run_id="crypto-run",
                sports_run_id="sports-run",
            )
        self.assertIn("kalshi:sports", report["evaluations"])
        result = report["evaluations"]["kalshi:sports"]["result"]
        self.assertIsNone(result["selected_challenger"])
        self.assertIn(result["model_state"], {"baseline_only", "insufficient_sample"})
        self.assertNotIn("crypto:crypto", report["evaluations"])
        self.assertFalse(report["live_prediction_logic_changed"])
        self.assertIn("no profitability claim", render_platform_model_audit(report))


if __name__ == "__main__":
    unittest.main()
