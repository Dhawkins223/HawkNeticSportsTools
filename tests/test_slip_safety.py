from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from kalshi_research_bot.evaluation.logging import extract_prediction_logs_from_payload
from kalshi_research_bot.paper_server import build_service_readiness
from kalshi_research_bot.review_packet import build_review_packet
from kalshi_research_bot.slip_safety import consumer_payload, gate_slip_payload, slip_payload_gate


NOW = datetime(2026, 7, 11, 18, 0, tzinfo=timezone.utc)


def sample_payload(**overrides):
    payload = {
        "date": "20260711",
        "generated_at": "2026-07-11T17:55:00Z",
        "source_cache_status": {"stale_fallback_count": 0},
        "custom_slip": {
            "action": "BUILD_SLIP",
            "leg_count": 1,
            "legs": [{"market_ticker": "TEST", "side": "yes"}],
        },
    }
    payload.update(overrides)
    return payload


class SlipSafetyTests(unittest.TestCase):
    def test_fresh_payload_remains_available(self) -> None:
        gated = gate_slip_payload(sample_payload(), now=NOW)

        self.assertEqual(gated["public_data_gate"]["status"], "ready")
        self.assertEqual(gated["custom_slip"]["action"], "BUILD_SLIP")

    def test_stale_fallback_hides_all_slips_and_review_packet(self) -> None:
        gated = gate_slip_payload(
            sample_payload(source_cache_status={"stale_fallback_count": 2}),
            now=NOW,
        )
        packet = build_review_packet(gated, "primary")

        self.assertEqual(gated["public_data_gate"]["code"], "blocked_stale_source")
        self.assertEqual(gated["custom_slip"]["action"], "NO_SLIP")
        self.assertEqual(gated["custom_slip"]["legs"], [])
        slip_keys = ("custom_slip", "leverage_slip", "all_day_slip", "research_edge_slip")
        self.assertTrue(all(gated[key]["action"] == "NO_SLIP" for key in slip_keys))
        self.assertFalse(packet["ready"])
        self.assertEqual(packet["legs"], [])
        self.assertEqual(extract_prediction_logs_from_payload(gated, run_id="test"), [])

    def test_old_payload_is_blocked_from_public_use(self) -> None:
        gate = slip_payload_gate(
            sample_payload(generated_at="2026-07-11T16:00:00Z"),
            now=NOW,
            max_age_seconds=1800,
        )

        self.assertEqual(gate["status"], "blocked")
        self.assertEqual(gate["code"], "blocked_stale_payload")

    def test_refresh_failure_hides_previous_slip_rows(self) -> None:
        gated = gate_slip_payload(sample_payload(refresh_error="live_refresh_failed"), now=NOW)

        self.assertEqual(gated["public_data_gate"]["code"], "blocked_refresh_failed")
        self.assertEqual(gated["custom_slip"]["blocked_previous_leg_count"], 1)
        self.assertEqual(gated["custom_slip"]["leg_count"], 0)

    def test_consumer_payload_excludes_internal_diagnostics(self) -> None:
        payload = gate_slip_payload(
            sample_payload(
                research_summary={"internal": True},
                source_cache_status={"stale_fallback_count": 0},
            ),
            now=NOW,
        )
        public = consumer_payload(payload)

        self.assertNotIn("research_summary", public)
        self.assertNotIn("source_cache_status", public)
        self.assertEqual(public["custom_slip"]["action"], "BUILD_SLIP")

    def test_readiness_reports_blocked_without_exposing_details(self) -> None:
        with patch.dict(os.environ, {"DASHBOARD_MAX_SLIP_AGE_SECONDS": "1800"}, clear=False):
            readiness = build_service_readiness(sample_payload(refresh_error="live_refresh_failed"))

        self.assertEqual(readiness["status"], "blocked")
        self.assertEqual(readiness["data_gate"], "blocked_refresh_failed")
        self.assertEqual(
            set(readiness),
            {"status", "service", "data_gate", "generated_at", "database", "production_safety"},
        )
        rendered = str(readiness)
        self.assertNotIn("DATABASE_URL", rendered)
        self.assertNotIn("password", rendered.lower())


if __name__ == "__main__":
    unittest.main()
