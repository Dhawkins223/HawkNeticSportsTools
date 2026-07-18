from __future__ import annotations

from kalshi_research_bot.evaluation.model_audit import build_platform_model_audit, render_platform_model_audit

from tests.postgres_support import PostgresTestCase


class ModelAuditTests(PostgresTestCase):
    def test_market_baseline_is_not_misrepresented_as_validated_challenger(self) -> None:
        store = self.store("audit")
        rows = []
        for index in range(20):
            rows.append({
                "run_id": "kalshi-run", "timestamp": f"2026-01-{index + 1:02d}T12:00:00+00:00",
                "event": f"Game {index}", "event_id": f"event-{index}", "market": f"market-{index}", "market_id": f"market-{index}",
                "side": "yes", "strategy": "baseline", "model_version": "market_implied_slip_v1", "confidence_score": "0.69", "confidence_label": "market",
                "predicted_outcome": "yes", "event_start_time": "2026-02-01T12:00:00+00:00", "market_close_time": "2026-02-01T12:00:00+00:00",
                "api_fetched_at": f"2026-01-{index + 1:02d}T11:59:00+00:00", "source_snapshot_hash": f"hash-{index}", "entry_price_cents": "60", "implied_probability": "0.6",
                "settlement_state": "win", "actual_outcome": True, "profit_loss_cents": "40",
            })
        store.insert_prediction_logs(rows)
        report = build_platform_model_audit(kalshi_run_id="kalshi-run", crypto_run_id="crypto-run", sports_run_id="sports-run", persist=False)
        result = report["evaluations"]["kalshi:event"]["result"]
        self.assertIsNone(result["selected_challenger"])
        self.assertIn(result["model_state"], {"baseline_only", "insufficient_sample"})
        self.assertFalse(report["live_prediction_logic_changed"])
        self.assertIn("no profitability claim", render_platform_model_audit(report))
