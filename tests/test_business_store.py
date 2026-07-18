from __future__ import annotations

from kalshi_research_bot.business_store import create_store, finish_report_refresh, start_report_refresh
from kalshi_research_bot.collection_ledger import CollectionLedger
from kalshi_research_bot.monitoring import WorkerMonitorStore

from tests.postgres_support import PostgresTestCase


class BusinessStoreTests(PostgresTestCase):
    def test_prediction_and_rejection_writes_are_transactional_and_idempotent(self) -> None:
        store = create_store("business-store", settings=self.settings)
        log = {
            "run_id": "parity-run",
            "timestamp": "2099-01-01T00:00:00+00:00",
            "event": "Example event",
            "event_id": "event",
            "market": "Example market",
            "market_id": "market",
            "side": "yes",
            "strategy": "primary",
            "model_version": "fixture",
            "confidence_score": "0.61",
            "confidence_label": "medium",
            "predicted_outcome": "yes",
            "event_start_time": "2099-01-02T00:00:00+00:00",
            "market_close_time": "2099-01-02T01:00:00+00:00",
            "api_fetched_at": "2099-01-01T00:00:00+00:00",
            "source_snapshot_hash": "sha256:fixture",
            "entry_price_cents": "52.0",
            "implied_probability": "0.52",
        }
        self.assertEqual(store.insert_prediction_logs([log]), 1)
        self.assertEqual(store.insert_prediction_logs([log]), 0)
        store.insert_prediction_rejections(
            [{"run_id": "parity-run", "timestamp": log["timestamp"], "event": "event", "market": "market", "side": "yes", "validation_errors": ["stale_source"], "raw_log": {"bad": True}}]
        )
        with self.assertRaisesRegex(RuntimeError, "rollback"):
            with store.connect() as connection:
                connection.execute(
                    "INSERT INTO app.prediction_rejections (run_id, prediction_timestamp, event, market, side, validation_errors_json, raw_log_json) VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s::jsonb)",
                    ("rollback", log["timestamp"], "event", "market", "yes", "[]", "{}"),
                )
                raise RuntimeError("rollback")
        self.assertEqual(self.query_one("SELECT COUNT(*) AS total FROM app.prediction_logs")["total"], 1)
        self.assertEqual(self.query_one("SELECT COUNT(*) AS total FROM app.prediction_rejections WHERE run_id = %s", ("rollback",))["total"], 0)

    def test_worker_and_checkpoint_state_commit_only_after_success(self) -> None:
        monitor = WorkerMonitorStore(self.settings)
        self.assertTrue(monitor.start_run(worker_name="settlement", asset_class="kalshi", run_id="run", idempotency_key="key", attempted_at="2099-01-01T00:00:00+00:00"))
        self.assertFalse(monitor.start_run(worker_name="settlement", asset_class="kalshi", run_id="run", idempotency_key="key", attempted_at="2099-01-01T00:00:00+00:00"))
        self.assertTrue(monitor.finish_success(worker_name="settlement", idempotency_key="key", finished_at="2099-01-01T00:01:00+00:00", records_processed=3, details={"ok": True}))

        ledger = CollectionLedger(self.settings)
        batch = ledger.start_batch(idempotency_key="batch", source="kalshi", endpoint="markets", worker_name="kalshi", worker_version="test", collector_version="test")
        self.assertTrue(ledger.complete_batch(batch_id=batch.batch_id, records_received=1, records_accepted=1, records_rejected=0, records_duplicated=0, checkpoint={"source": "kalshi", "endpoint": "markets", "cursor": "one"}))
        self.assertEqual(ledger.checkpoint(source="kalshi", endpoint="markets")["cursor"], "one")

    def test_report_refresh_is_committed_or_rolled_back_as_one_transaction(self) -> None:
        store = create_store("report-refresh", settings=self.settings)
        with store.connect() as connection:
            start_report_refresh(connection, refresh_id="refresh", report_name="evaluation", data_cutoff_at="2099-01-01T00:00:00+00:00", started_at="2099-01-01T00:00:00+00:00")
            finish_report_refresh(connection, refresh_id="refresh", completed_at="2099-01-01T00:01:00+00:00", status="completed", row_count=7)
        row = self.query_one("SELECT status, row_count FROM ops.report_refreshes WHERE refresh_id = %s", ("refresh",))
        self.assertEqual((row["status"], row["row_count"]), ("completed", 7))
