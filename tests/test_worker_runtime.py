import json

from kalshi_research_bot.monitoring import actionable_monitoring_events, build_internal_status
from kalshi_research_bot.worker_runtime import NonRetryableWorkerError, WorkerSpec, run_worker_once, structured_worker_log
from tests.postgres_support import PostgresTestCase


class WorkerRuntimeTests(PostgresTestCase):
    def _run(self, spec, operation, *, run_id, key, **kwargs):
        return run_worker_once(
            spec,
            operation,
            settings=self.settings,
            run_id=run_id,
            idempotency_key=key,
            log_writer=lambda _: None,
            **kwargs,
        )

    def test_worker_run_is_idempotent(self):
        calls = []
        operation = lambda: calls.append("called") or {"records_processed": 2}
        spec = WorkerSpec("crypto-research", "crypto", 60)
        first = self._run(spec, operation, run_id="run", key="same")
        second = self._run(spec, operation, run_id="run", key="same")
        self.assertEqual(first["status"], "success")
        self.assertEqual(second["status"], "skipped_duplicate")
        self.assertEqual(calls, ["called"])

    def test_retry_and_backoff_can_recover_settlement_importer(self):
        attempts, sleeps = [], []

        def operation():
            attempts.append(1)
            if len(attempts) < 3:
                raise RuntimeError("settlement_source_timeout")
            return {"records_processed": 4, "pending_settlements": 2}

        result = self._run(
            WorkerSpec("settlement-worker", "kalshi", 60, maximum_attempts=3, initial_backoff_seconds=1),
            operation,
            run_id="run",
            key="retry",
            sleep=sleeps.append,
        )
        self.assertEqual(result["status"], "success")
        self.assertEqual(result["attempts"], 3)
        self.assertEqual(sleeps, [1, 2])

    def test_no_material_change_is_not_zero_record_failure(self):
        result = self._run(
            WorkerSpec("crypto-research", "crypto", 60, expect_records=True),
            lambda: {"records_processed": 0, "no_material_change": True},
            run_id="run",
            key="no-change",
        )
        self.assertEqual(result["status"], "success")
        self.assertTrue(result["no_material_change"])

    def test_unexpected_zero_records_is_actionable_failure(self):
        result = self._run(
            WorkerSpec("kalshi-ingestion", "kalshi", 60, expect_records=True, maximum_attempts=1),
            lambda: {"records_processed": 0},
            run_id="run",
            key="zero",
        )
        self.assertEqual(result["status"], "failed")
        self.assertIn("unexpected_zero_records", result["error_code"])

    def test_non_retryable_source_block_stops_retry_amplification(self):
        attempts = []

        def blocked_operation():
            attempts.append(1)
            raise NonRetryableWorkerError("blocked_public_source_unavailable")

        result = self._run(
            WorkerSpec("sports-research", "sports", 60, maximum_attempts=3),
            blocked_operation,
            run_id="run",
            key="blocked",
            sleep=lambda _: self.fail("non-retryable failure must not back off"),
        )
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["attempts"], 1)
        self.assertEqual(attempts, [1])

    def test_failed_worker_does_not_prevent_other_worker_success(self):
        failed = self._run(
            WorkerSpec("sports-research", "sports", 60, maximum_attempts=1),
            lambda: (_ for _ in ()).throw(RuntimeError("source_blocked")),
            run_id="sports",
            key="sports-1",
        )
        healthy = self._run(
            WorkerSpec("kalshi-ingestion", "kalshi", 60),
            lambda: {"records_processed": 5},
            run_id="kalshi",
            key="kalshi-1",
        )
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(healthy["status"], "success")

    def test_internal_status_reports_workers_database_and_backlog(self):
        self._run(
            WorkerSpec("reporting-worker", "all", 60),
            lambda: {"records_processed": 1},
            run_id="run",
            key="one",
        )
        status = build_internal_status(self.settings, heartbeat_stale_seconds=10**9)
        self.assertTrue(status["database"]["available"])
        self.assertEqual(status["workers"][0]["worker_name"], "reporting-worker")
        self.assertIn("pending_settlements", status)
        self.assertFalse(status["public_exposure_allowed"])

    def test_structured_logs_omit_secret_named_fields(self):
        output = []
        structured_worker_log({"event": "test", "api_key": "do-not-print", "password": "hidden", "count": 3}, writer=output.append)
        payload = json.loads(output[0])
        self.assertEqual(payload["count"], 3)
        self.assertNotIn("api_key", payload)
        self.assertNotIn("password", payload)

    def test_monitoring_events_are_actionable_and_not_healthy_heartbeat_spam(self):
        self.assertEqual(actionable_monitoring_events({"status": "ready", "anomalies": []}), [])
        degraded = actionable_monitoring_events(
            {"status": "degraded", "anomalies": [{"type": "settlement_backlog", "asset_class": "sports", "count": 4}, {"type": "model_drift", "worker_name": "crypto-research"}]}
        )
        self.assertEqual({event["event_type"] for event in degraded}, {"settlement_backlog", "model_drift"})
