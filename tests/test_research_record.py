from __future__ import annotations

from kalshi_research_bot.research_record import build_research_record

from tests.postgres_support import PostgresTestCase


class ResearchRecordTests(PostgresTestCase):
    def test_kalshi_record_excludes_unresolved_invalid_rejected_and_duplicates(self) -> None:
        store = self.store("record")
        base = {
            "run_id": "record", "timestamp": "2026-07-18T12:00:00+00:00", "event": "Event", "market": "Market", "side": "yes", "strategy": "primary",
            "model_version": "baseline", "confidence_score": "0.6", "confidence_label": "medium", "predicted_outcome": "yes",
            "event_start_time": "2026-07-19T12:00:00+00:00", "market_close_time": "2026-07-19T12:00:00+00:00", "api_fetched_at": "2026-07-18T12:00:00+00:00",
        }
        store.insert_prediction_logs([
            {**base, "event_id": "event-1", "market_id": "market-1", "source_snapshot_hash": "one", "settlement_state": "win", "actual_outcome": True, "profit_loss_cents": "40"},
            {**base, "event_id": "event-1", "market_id": "market-1", "source_snapshot_hash": "two", "timestamp": "2026-07-18T12:01:00+00:00", "settlement_state": "win", "actual_outcome": True, "profit_loss_cents": "40"},
            {**base, "event_id": "event-2", "market_id": "market-2", "source_snapshot_hash": "three", "timestamp": "2026-07-18T12:02:00+00:00", "settlement_state": "loss", "actual_outcome": False, "profit_loss_cents": "-60"},
            {**base, "event_id": "event-3", "market_id": "market-3", "source_snapshot_hash": "four", "timestamp": "2026-07-18T12:03:00+00:00"},
        ])
        store.insert_prediction_rejections([{"run_id": "record", "timestamp": "2026-07-18T12:04:00+00:00", "event": "Event", "market": "Bad", "side": "yes", "validation_errors": ["missing_api_fetched_at"], "raw_log": {}}])
        record = build_research_record(payload={"custom_slip": {"action": "BUILD_SLIP", "leg_count": 2}})
        kalshi = next(track for track in record["tracks"] if track["asset_class"] == "kalshi")
        self.assertEqual(kalshi["deduped_settled_exposures"], 2)
        self.assertEqual(kalshi["wins"], 1)
        self.assertEqual(kalshi["losses"], 1)
        self.assertEqual(kalshi["unresolved_rows"], 1)
        self.assertEqual(kalshi["rejected_rows"], 1)
        self.assertIsNone(kalshi["observed_hit_rate"])
        self.assertEqual(kalshi["observed_hit_rate_raw"], 0.5)
