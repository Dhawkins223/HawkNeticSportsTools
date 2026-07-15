from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from kalshi_research_bot.business_store import (
    PostgresCompatCursor,
    _transform_sql,
    active_database_backend,
    create_research_store,
    finish_report_refresh,
    hosted_environment,
    open_legacy_connection,
    start_report_refresh,
)
from kalshi_research_bot.collection_ledger import CollectionLedger
from kalshi_research_bot.monitoring import WorkerMonitorStore
from kalshi_research_bot.storage import ResearchStore


VALID_LOG = {
    "run_id": "parity_run",
    "timestamp": "2099-01-01T00:00:00+00:00",
    "event": "Example event",
    "event_id": "EVT_PARITY",
    "market": "Example market",
    "market_id": "MKT_PARITY",
    "side": "yes",
    "strategy": "parity_strategy",
    "input_data_used": {"source": "fixture"},
    "odds_used": {"yes_ask": 0.52},
    "model_version": "fixture_v1",
    "confidence_score": 0.61,
    "confidence_label": "medium",
    "predicted_outcome": "yes",
    "event_start_time": "2099-01-02T00:00:00+00:00",
    "market_close_time": "2099-01-01T23:00:00+00:00",
    "api_fetched_at": "2099-01-01T00:00:00+00:00",
    "source_updated_at": "2099-01-01T00:00:00+00:00",
    "source_snapshot_id": "snap-1",
    "source_snapshot_hash": "sha256:snap1",
    "snapshot_sequence": 1,
    "entry_price_cents": 52.0,
    "implied_probability": 0.52,
    "reason_features": {"freshness_state": "fresh"},
}


class BusinessStoreSQLiteTests(unittest.TestCase):
    def test_factory_preserves_sqlite_initialization_prediction_duplicates_rejections_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "evaluation.sqlite"
            store = create_research_store(db_path)
            self.assertIsInstance(store, ResearchStore)
            store.initialize()
            inserted = store.insert_prediction_logs([VALID_LOG])
            duplicate = store.insert_prediction_logs([VALID_LOG])
            self.assertEqual(inserted, 1)
            self.assertEqual(duplicate, 0)
            store.insert_prediction_rejections([
                {
                    "run_id": "parity_run",
                    "timestamp": "2099-01-01T00:01:00+00:00",
                    "event": "Example event",
                    "market": "Example market",
                    "side": "yes",
                    "strategy": "parity_strategy",
                    "validation_errors": ["stale_source"],
                    "raw_log": {"bad": True},
                }
            ])
            with store.connect() as connection:
                prediction_count = connection.execute("SELECT COUNT(*) FROM prediction_logs").fetchone()[0]
                rejection_count = connection.execute("SELECT COUNT(*) FROM prediction_rejections").fetchone()[0]
            self.assertEqual(prediction_count, 1)
            self.assertEqual(rejection_count, 1)
            try:
                with store.connect() as connection:
                    connection.execute(
                        "INSERT INTO prediction_rejections (run_id, prediction_timestamp, event, market, side, validation_errors_json, raw_log_json) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        ("rollback", "2099-01-01T00:00:00+00:00", "E", "M", "yes", "[]", "{}"),
                    )
                    raise RuntimeError("inject_rollback")
            except RuntimeError:
                pass
            with store.connect() as connection:
                rollback_count = connection.execute("SELECT COUNT(*) FROM prediction_rejections WHERE run_id='rollback'").fetchone()[0]
            self.assertEqual(rollback_count, 0)

    def test_worker_monitor_and_collection_checkpoint_commit_only_after_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "evaluation.sqlite"
            monitor = WorkerMonitorStore(db_path)
            self.assertTrue(monitor.start_run(
                worker_name="settlement-worker",
                asset_class="kalshi",
                run_id="run1",
                idempotency_key="key1",
                attempted_at="2099-01-01T00:00:00+00:00",
            ))
            self.assertFalse(monitor.start_run(
                worker_name="settlement-worker",
                asset_class="kalshi",
                run_id="run1",
                idempotency_key="key1",
                attempted_at="2099-01-01T00:00:00+00:00",
            ))
            monitor.finish_success(
                worker_name="settlement-worker",
                idempotency_key="key1",
                finished_at="2099-01-01T00:01:00+00:00",
                records_processed=3,
                details={"ok": True},
            )
            ledger = CollectionLedger(db_path)
            batch = ledger.start_batch(
                idempotency_key="batch-key",
                source="kalshi",
                endpoint="markets",
                worker_name="kalshi-market-ingestion",
                worker_version="test",
                collector_version="test",
                started_at="2099-01-01T00:00:00+00:00",
            )
            ledger.complete_batch(
                batch_id=batch.batch_id,
                completed_at="2099-01-01T00:02:00+00:00",
                records_received=3,
                records_accepted=2,
                records_rejected=1,
                records_duplicated=0,
                checkpoint={
                    "source": "kalshi",
                    "endpoint": "markets",
                    "partition_scope": "default",
                    "cursor": "cursor-1",
                    "last_successful_item_time": "2099-01-01T00:01:00+00:00",
                },
            )
            checkpoint = ledger.checkpoint(source="kalshi", endpoint="markets", partition_scope="default")
            self.assertEqual(checkpoint["cursor"], "cursor-1")


    def test_report_refresh_records_commit_and_rollback(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "evaluation.sqlite"
            store = create_research_store(db_path)
            store.initialize()
            with store.connect() as connection:
                start_report_refresh(
                    connection,
                    refresh_id="refresh-1",
                    report_name="reporting-evaluation",
                    data_cutoff_at="2099-01-01T00:00:00+00:00",
                    started_at="2099-01-01T00:00:00+00:00",
                )
                finish_report_refresh(
                    connection,
                    refresh_id="refresh-1",
                    completed_at="2099-01-01T00:01:00+00:00",
                    status="completed",
                    row_count=7,
                )
            with store.connect() as connection:
                row = connection.execute("SELECT status, row_count FROM report_refreshes WHERE refresh_id = ?", ("refresh-1",)).fetchone()
            self.assertEqual(row[0], "completed")
            self.assertEqual(row[1], 7)
            try:
                with store.connect() as connection:
                    start_report_refresh(
                        connection,
                        refresh_id="refresh-rollback",
                        report_name="reporting-evaluation",
                        data_cutoff_at="2099-01-01T00:00:00+00:00",
                        started_at="2099-01-01T00:00:00+00:00",
                    )
                    raise RuntimeError("rollback")
            except RuntimeError:
                pass
            with store.connect() as connection:
                count = connection.execute("SELECT COUNT(*) FROM report_refreshes WHERE refresh_id = ?", ("refresh-rollback",)).fetchone()[0]
            self.assertEqual(count, 0)

    def test_hosted_runtime_refuses_sqlite_without_explicit_override(self):
        with mock.patch.dict(os.environ, {"APP_ENV": "staging", "DATABASE_BACKEND": "sqlite"}, clear=False):
            self.assertTrue(hosted_environment())
            with self.assertRaisesRegex(RuntimeError, "hosted_runtime_requires_postgres_business_store"):
                active_database_backend(Path("data/evaluation.sqlite"))
        with mock.patch.dict(os.environ, {"APP_ENV": "staging", "DATABASE_BACKEND": "sqlite", "ALLOW_HOSTED_SQLITE_RUNTIME": "true"}, clear=False):
            self.assertEqual(active_database_backend(Path("data/evaluation.sqlite")), "sqlite")


    def test_postgres_sql_transform_and_cursor_description_are_safe(self):
        transformed = _transform_sql("INSERT OR IGNORE INTO prediction_logs (run_id, market_id) VALUES (?, ?)")
        self.assertIn("INSERT INTO prediction_logs", transformed)
        self.assertIn("VALUES (%s, %s)", transformed)
        self.assertIn("ON CONFLICT DO NOTHING", transformed)

        class Column:
            def __init__(self, name):
                self.name = name

        class Cursor:
            rowcount = 1
            description = [Column("run_id"), Column("market_id")]

            def __init__(self):
                self.rows = [("run", "market")]

            def fetchone(self):
                return self.rows.pop(0) if self.rows else None

            def fetchall(self):
                rows = list(self.rows)
                self.rows.clear()
                return rows

        cursor = PostgresCompatCursor(Cursor())
        row = cursor.fetchone()
        self.assertEqual(row["run_id"], "run")
        self.assertEqual(row[1], "market")

    def test_postgres_factory_requires_url_and_reports_backend_without_sqlite_fallback(self):
        with mock.patch.dict(os.environ, {"DATABASE_BACKEND": "postgres"}, clear=True):
            with self.assertRaisesRegex(RuntimeError, "postgres_business_store_requires_database_url"):
                create_research_store(Path("ignored.sqlite"))
        with mock.patch.dict(os.environ, {"DATABASE_BACKEND": "postgres", "DATABASE_URL": "postgresql://user:pass@localhost:5432/db"}, clear=True):
            with mock.patch("kalshi_research_bot.business_store.ensure_postgres_ready"):
                with mock.patch("kalshi_research_bot.business_store.PostgresCompatConnection") as connection_cls:
                    connection_cls.return_value.execute.return_value.fetchone.return_value = [1]
                    connection = open_legacy_connection(Path("ignored.sqlite"))
                    self.assertEqual(connection_cls.call_count, 1)
                    connection.close()


if __name__ == "__main__":
    unittest.main()
