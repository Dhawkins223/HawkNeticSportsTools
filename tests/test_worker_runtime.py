import json
import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.monitoring import (
    WorkerMonitorStore,
    actionable_monitoring_events,
    build_internal_status,
)
from kalshi_research_bot.worker_runtime import NonRetryableWorkerError, WorkerSpec, run_worker_once, structured_worker_log


class WorkerRuntimeTests(unittest.TestCase):
    def test_worker_run_is_idempotent(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "workers.sqlite"
            calls = []
            operation = lambda: calls.append("called") or {"records_processed": 2}
            spec = WorkerSpec("crypto-research", "crypto", 60)
            first = run_worker_once(spec, operation, db_path=database, run_id="run", idempotency_key="same", log_writer=lambda _: None)
            second = run_worker_once(spec, operation, db_path=database, run_id="run", idempotency_key="same", log_writer=lambda _: None)
            self.assertEqual(first["status"], "success")
            self.assertEqual(second["status"], "skipped_duplicate")
            self.assertEqual(calls, ["called"])

    def test_retry_and_backoff_can_recover_settlement_importer(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "workers.sqlite"
            attempts = []
            sleeps = []

            def operation():
                attempts.append(1)
                if len(attempts) < 3:
                    raise RuntimeError("settlement_source_timeout")
                return {"records_processed": 4, "pending_settlements": 2}

            result = run_worker_once(
                WorkerSpec("settlement-worker", "kalshi", 60, maximum_attempts=3, initial_backoff_seconds=1),
                operation,
                db_path=database,
                run_id="run",
                idempotency_key="retry",
                sleep=sleeps.append,
                log_writer=lambda _: None,
            )
            self.assertEqual(result["status"], "success")
            self.assertEqual(result["attempts"], 3)
            self.assertEqual(sleeps, [1, 2])

    def test_no_material_change_is_not_zero_record_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_worker_once(
                WorkerSpec("crypto-research", "crypto", 60, expect_records=True),
                lambda: {"records_processed": 0, "no_material_change": True},
                db_path=Path(directory) / "workers.sqlite",
                run_id="run",
                idempotency_key="no-change",
                log_writer=lambda _: None,
            )
            self.assertEqual(result["status"], "success")
            self.assertTrue(result["no_material_change"])

    def test_unexpected_zero_records_is_actionable_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            result = run_worker_once(
                WorkerSpec("kalshi-ingestion", "kalshi", 60, expect_records=True, maximum_attempts=1),
                lambda: {"records_processed": 0},
                db_path=Path(directory) / "workers.sqlite",
                run_id="run",
                idempotency_key="zero",
                log_writer=lambda _: None,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIn("unexpected_zero_records", result["error_code"])

    def test_non_retryable_source_block_stops_retry_amplification(self):
        with tempfile.TemporaryDirectory() as directory:
            attempts = []

            def blocked_operation():
                attempts.append(1)
                raise NonRetryableWorkerError("blocked_public_source_unavailable")

            result = run_worker_once(
                WorkerSpec("sports-research", "sports", 60, maximum_attempts=3),
                blocked_operation,
                db_path=Path(directory) / "workers.sqlite",
                run_id="run",
                idempotency_key="blocked",
                sleep=lambda _: self.fail("non-retryable failure must not back off"),
                log_writer=lambda _: None,
            )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(attempts, [1])

    def test_failed_worker_does_not_prevent_other_worker_success(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "workers.sqlite"
            failed = run_worker_once(
                WorkerSpec("sports-research", "sports", 60, maximum_attempts=1),
                lambda: (_ for _ in ()).throw(RuntimeError("source_blocked")),
                db_path=database,
                run_id="sports",
                idempotency_key="sports-1",
                log_writer=lambda _: None,
            )
            healthy = run_worker_once(
                WorkerSpec("kalshi-ingestion", "kalshi", 60),
                lambda: {"records_processed": 5},
                db_path=database,
                run_id="kalshi",
                idempotency_key="kalshi-1",
                log_writer=lambda _: None,
            )
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(healthy["status"], "success")

    def test_internal_status_reports_workers_database_and_backlog(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "workers.sqlite"
            monitor = WorkerMonitorStore(database)
            monitor.start_run(
                worker_name="reporting-worker",
                asset_class="all",
                run_id="run",
                idempotency_key="one",
                attempted_at="2026-07-12T12:00:00+00:00",
            )
            monitor.finish_success(
                worker_name="reporting-worker",
                idempotency_key="one",
                finished_at="2026-07-12T12:01:00+00:00",
                records_processed=1,
                details={},
            )
            status = build_internal_status(database, heartbeat_stale_seconds=10**9)
            self.assertTrue(status["database"]["available"])
            self.assertEqual(status["workers"][0]["worker_name"], "reporting-worker")
            self.assertIn("pending_settlements", status)
            self.assertFalse(status["public_exposure_allowed"])

    def test_structured_logs_omit_secret_named_fields(self):
        output = []
        structured_worker_log(
            {"event": "test", "api_key": "do-not-print", "password": "hidden", "count": 3},
            writer=output.append,
        )
        payload = json.loads(output[0])
        self.assertEqual(payload["count"], 3)
        self.assertNotIn("api_key", payload)
        self.assertNotIn("password", payload)

    def test_monitoring_events_are_actionable_and_not_healthy_heartbeat_spam(self):
        healthy = actionable_monitoring_events({"status": "ready", "anomalies": []})
        self.assertEqual(healthy, [])
        degraded = actionable_monitoring_events(
            {
                "status": "degraded",
                "anomalies": [
                    {"type": "settlement_backlog", "asset_class": "sports", "count": 4},
                    {"type": "model_drift", "worker_name": "crypto-research"},
                ],
            }
        )
        self.assertEqual({event["event_type"] for event in degraded}, {"settlement_backlog", "model_drift"})


if __name__ == "__main__":
    unittest.main()
