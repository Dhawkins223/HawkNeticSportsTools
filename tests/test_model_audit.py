from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.evaluation.model_audit import (
    build_platform_model_audit,
    default_platform_model_audit_path,
    render_platform_model_audit,
    write_platform_model_audit,
)

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


class ModelAuditOutputTests(unittest.TestCase):
    """The write path, which had no coverage and did not work.

    Both of these raised NameError -- ``Path`` was used in the bodies but never
    imported, and ``from __future__ import annotations`` made the signatures
    lazy enough that nothing noticed until the CLI ran. That broke
    ``model-audit`` outright, on the default-path branch and the write branch
    alike.
    """

    def report(self) -> dict:
        """The keys ``render_platform_model_audit`` indexes without a default."""

        return {
            "report_type": "platform_model_validation",
            "research_only": True,
            "baseline": "market_implied_probability",
            "split_policy": "chronological_60_20_20_with_untouched_test_set",
            "evaluations": {
                "kalshi:event": {
                    "result": {
                        "model_state": "baseline_only",
                        "reason": "insufficient_sample",
                        "selected_challenger": None,
                        "sample_size": 20,
                        "periods": {},
                        "test_metrics": {},
                    }
                }
            },
            "usable_research_models": [],
            "live_prediction_logic_changed": False,
        }

    def test_the_default_output_path_resolves(self) -> None:
        self.assertEqual(default_platform_model_audit_path().name, "model_validation_audit.txt")

    def test_writing_produces_both_the_text_and_the_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "nested" / "audit.txt"
            write_platform_model_audit(self.report(), target)
            self.assertTrue(target.exists())
            self.assertEqual(target.read_text(encoding="utf-8"), render_platform_model_audit(self.report()))
            sidecar = target.with_suffix(".json")
            self.assertEqual(json.loads(sidecar.read_text(encoding="utf-8")), self.report())

    def test_a_plain_string_path_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = str(Path(tmp) / "audit.txt")
            write_platform_model_audit(self.report(), target)
            self.assertTrue(Path(target).exists())
