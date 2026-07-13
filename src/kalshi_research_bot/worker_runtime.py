from __future__ import annotations

import json
import signal
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .connectors.slack_alerts import build_alert_payload, send_alert
from .monitoring import WorkerMonitorStore


WorkerOperation = Callable[[], Mapping[str, Any]]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_iso(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()


def cadence_idempotency_key(worker_name: str, cadence_seconds: int, *, now: datetime | None = None) -> str:
    timestamp = int((now or utc_now()).timestamp())
    bucket = timestamp // max(1, int(cadence_seconds))
    return f"{worker_name}:{cadence_seconds}:{bucket}"


def structured_worker_log(event: Mapping[str, Any], *, writer: Callable[[str], Any] = print) -> None:
    safe = {
        key: value
        for key, value in event.items()
        if not any(secret in str(key).lower() for secret in ("password", "secret", "token", "api_key", "webhook"))
    }
    writer(json.dumps(safe, sort_keys=True, default=str))


@dataclass(frozen=True)
class WorkerSpec:
    name: str
    asset_class: str
    cadence_seconds: int
    maximum_attempts: int = 3
    initial_backoff_seconds: float = 2.0
    expect_records: bool = False
    alert_after_failures: int = 3


def run_worker_once(
    spec: WorkerSpec,
    operation: WorkerOperation,
    *,
    db_path: str | Path,
    run_id: str,
    idempotency_key: str | None = None,
    now: datetime | None = None,
    sleep: Callable[[float], Any] = time.sleep,
    log_writer: Callable[[str], Any] = print,
) -> dict[str, Any]:
    attempted = now or utc_now()
    key = idempotency_key or cadence_idempotency_key(spec.name, spec.cadence_seconds, now=attempted)
    monitor = WorkerMonitorStore(db_path)
    if not monitor.start_run(
        worker_name=spec.name,
        asset_class=spec.asset_class,
        run_id=run_id,
        idempotency_key=key,
        attempted_at=utc_iso(attempted),
    ):
        result = {
            "status": "skipped_duplicate",
            "worker_name": spec.name,
            "run_id": run_id,
            "idempotency_key": key,
        }
        structured_worker_log(result, writer=log_writer)
        return result
    structured_worker_log(
        {"event": "worker_started", "worker_name": spec.name, "run_id": run_id, "idempotency_key": key},
        writer=log_writer,
    )
    final_error: Exception | None = None
    for attempt in range(1, max(1, spec.maximum_attempts) + 1):
        try:
            raw_result = dict(operation())
            records_processed = int(raw_result.get("records_processed") or 0)
            no_material_change = bool(raw_result.get("no_material_change"))
            if spec.expect_records and records_processed == 0 and not no_material_change:
                raise RuntimeError("unexpected_zero_records")
            finished_at = utc_iso()
            monitor.finish_success(
                worker_name=spec.name,
                idempotency_key=key,
                finished_at=finished_at,
                records_processed=records_processed,
                details=raw_result,
                data_fresh_at=raw_result.get("data_fresh_at"),
                source_fresh_at=raw_result.get("source_fresh_at"),
                pending_settlements=int(raw_result.get("pending_settlements") or 0),
                model_state=raw_result.get("model_state"),
            )
            result = {
                "status": "success",
                "worker_name": spec.name,
                "run_id": run_id,
                "idempotency_key": key,
                "attempts": attempt,
                **raw_result,
            }
            structured_worker_log({"event": "worker_succeeded", **result}, writer=log_writer)
            return result
        except Exception as exc:
            final_error = exc
            structured_worker_log(
                {
                    "event": "worker_attempt_failed",
                    "worker_name": spec.name,
                    "run_id": run_id,
                    "attempt": attempt,
                    "error_code": f"{type(exc).__name__}:{str(exc)[:120]}",
                },
                writer=log_writer,
            )
            if attempt < max(1, spec.maximum_attempts):
                sleep(spec.initial_backoff_seconds * (2 ** (attempt - 1)))
    error_code = f"{type(final_error).__name__}:{str(final_error)[:120]}" if final_error else "worker_failed"
    consecutive_failures = monitor.finish_failure(
        worker_name=spec.name,
        idempotency_key=key,
        finished_at=utc_iso(),
        error_code=error_code,
        details={"attempts": spec.maximum_attempts, "error_code": error_code},
    )
    alert_status = {"status": "not_applicable"}
    if consecutive_failures >= spec.alert_after_failures:
        alert_status = send_alert(
            build_alert_payload(
                bot_name=spec.name,
                asset_class=spec.asset_class,
                run_id=run_id,
                severity="critical" if consecutive_failures >= 5 else "warning",
                event_type="consecutive_worker_failures",
                message=f"{spec.name} failed {consecutive_failures} consecutive runs",
                next_action="inspect private worker status and source/database health",
            )
        )
    result = {
        "status": "failed",
        "worker_name": spec.name,
        "run_id": run_id,
        "idempotency_key": key,
        "error_code": error_code,
        "consecutive_failures": consecutive_failures,
        "alert_status": alert_status.get("status"),
    }
    structured_worker_log({"event": "worker_failed", **result}, writer=log_writer)
    return result


def run_worker_forever(
    spec: WorkerSpec,
    operation: WorkerOperation,
    *,
    db_path: str | Path,
    run_id: str,
    stop_event: threading.Event | None = None,
) -> int:
    stopping = stop_event or threading.Event()

    def request_stop(_signum=None, _frame=None):
        stopping.set()

    for signal_name in ("SIGINT", "SIGTERM"):
        if hasattr(signal, signal_name):
            try:
                signal.signal(getattr(signal, signal_name), request_stop)
            except ValueError:
                pass
    while not stopping.is_set():
        run_worker_once(spec, operation, db_path=db_path, run_id=run_id)
        stopping.wait(spec.cadence_seconds)
    structured_worker_log({"event": "worker_stopped", "worker_name": spec.name, "run_id": run_id})
    return 0
