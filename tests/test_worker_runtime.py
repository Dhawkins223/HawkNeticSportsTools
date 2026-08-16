import json
import threading
from unittest import mock
from urllib.request import urlopen

import kalshi_research_bot.worker_runtime as worker_runtime
from kalshi_research_bot.monitoring import actionable_monitoring_events, build_internal_status
from kalshi_research_bot.worker_runtime import (
    NonRetryableWorkerError,
    WorkerSpec,
    run_worker_forever,
    run_worker_once,
    start_worker_health_server,
    structured_worker_log,
)
from tests.postgres_support import PostgresTestCase


class _RecordingEvent(threading.Event):
    """A stop event that records what it was asked to wait for and returns at once."""

    def __init__(self, delays=None) -> None:
        super().__init__()
        self.delays = delays

    def wait(self, timeout=None):  # type: ignore[override]
        if self.delays is not None and timeout is not None:
            self.delays.append(timeout)
        return self.is_set()


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

    def _forever(self, spec, *, cycle_results, stop_after, delays=None):
        """Drive run_worker_forever with a scripted sequence of cycle outcomes.

        Pass a list as `delays` to capture what the loop waited between cycles.
        """
        logs = []
        calls = []
        stopping = _RecordingEvent(delays)

        def fake_cycle(_spec, _operation, **_kwargs):
            index = len(calls)
            calls.append(index)
            if index + 1 >= stop_after:
                stopping.set()
            outcome = cycle_results[min(index, len(cycle_results) - 1)]
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        with mock.patch.object(worker_runtime, "run_worker_once", fake_cycle):
            run_worker_forever(
                spec,
                lambda: {"records_processed": 1},
                run_id="run",
                settings=self.settings,
                stop_event=stopping,
                log_writer=logs.append,
            )
        return calls, [json.loads(entry) for entry in logs]

    def test_a_sustained_outage_backs_off_to_the_worker_cadence(self):
        # A database that stays down must not be retried faster than the worker
        # would have run anyway. Capping the exponent instead of the delay pinned
        # an hourly worker to a 16-second retry against a recovering database.
        delays = []
        # The real hourly worker, with the default backoff base. The recording stop
        # event returns immediately, so this costs no wall-clock time.
        self._forever(
            WorkerSpec("sports-research", "sports", 3600),
            cycle_results=[RuntimeError("the database system is in recovery mode")],
            stop_after=25,
            delays=delays,
        )

        self.assertEqual(delays[0], 2.0)
        self.assertTrue(
            all(later >= earlier for earlier, later in zip(delays, delays[1:])),
            "backoff must be monotonic",
        )
        self.assertEqual(delays[-1], 3600.0, "a long outage must settle at the cadence")
        self.assertLessEqual(max(delays), 3600.0, "backoff must never exceed the cadence")

    def test_lost_database_connection_does_not_stop_the_worker(self):
        # The staging collector died exactly this way: a dropped connection during
        # the cycle's own bookkeeping escaped run_worker_once and killed the process.
        calls, logs = self._forever(
            WorkerSpec("sports-research", "sports", 60, initial_backoff_seconds=0.01),
            cycle_results=[
                RuntimeError("the connection is lost"),
                RuntimeError("the connection is lost"),
                {"status": "success"},
            ],
            stop_after=3,
        )
        self.assertEqual(len(calls), 3, "the worker must keep cycling after a crashed cycle")

        crashes = [entry for entry in logs if entry.get("event") == "worker_cycle_crashed"]
        self.assertEqual(len(crashes), 2)
        self.assertEqual(crashes[0]["consecutive_crashes"], 1)
        self.assertEqual(crashes[1]["consecutive_crashes"], 2)
        self.assertIn("the connection is lost", crashes[0]["error_code"])
        self.assertEqual(logs[-1]["event"], "worker_stopped")

    def test_repeated_crashes_reset_the_connection_pool(self):
        with mock.patch.object(worker_runtime, "close_connection_pools") as reset_pools:
            self._forever(
                WorkerSpec("sports-research", "sports", 60, initial_backoff_seconds=0.01),
                cycle_results=[RuntimeError("the connection is lost")],
                stop_after=4,
            )
        # Broken pooled connections keep failing the same way, so the pool is
        # dropped once the crashes stop looking transient.
        self.assertEqual(reset_pools.call_count, 2)

    def test_a_successful_cycle_clears_the_crash_streak(self):
        _, logs = self._forever(
            WorkerSpec("sports-research", "sports", 60, initial_backoff_seconds=0.01),
            cycle_results=[
                RuntimeError("the connection is lost"),
                {"status": "success"},
                RuntimeError("the connection is lost"),
            ],
            stop_after=3,
        )
        crashes = [entry for entry in logs if entry.get("event") == "worker_cycle_crashed"]
        self.assertEqual([entry["consecutive_crashes"] for entry in crashes], [1, 1])

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

    def test_worker_health_server_exposes_liveness_and_database_readiness(self):
        server = start_worker_health_server("kalshi-market-ingestion", 0)
        port = int(server.server_address[1])
        try:
            with urlopen(f"http://127.0.0.1:{port}/healthz", timeout=2) as response:
                health = json.loads(response.read())
            with urlopen(f"http://127.0.0.1:{port}/readyz", timeout=2) as response:
                readiness = json.loads(response.read())
        finally:
            server.shutdown()
            server.server_close()

        self.assertEqual(health, {"service": "kalshi-market-ingestion", "status": "ok"})
        self.assertEqual(readiness["status"], "ready")
        self.assertTrue(readiness["database"]["ready"])
