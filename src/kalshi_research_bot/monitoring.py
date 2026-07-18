from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Mapping

from .business_store import ensure_database_ready
from .connectors.slack_alerts import build_alert_payload, send_alert
from .connectors.status import build_connectors_status
from .database import DatabaseSession, DatabaseSettings, connection_pool


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc)
    try:
        timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp.astimezone(timezone.utc)


def _safe_error_code(value: str | None) -> str | None:
    if not value:
        return None
    return str(value).replace("\r", " ").replace("\n", " ")[:160]


def _details_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    try:
        parsed = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


class WorkerMonitorStore:
    """PostgreSQL operational monitoring store with idempotent worker ownership."""

    def __init__(self, settings: DatabaseSettings | None = None) -> None:
        self.settings = ensure_database_ready(settings)

    def _connect(self):
        return connection_pool(self.settings).connection()

    def start_run(
        self,
        *,
        worker_name: str,
        asset_class: str,
        run_id: str,
        idempotency_key: str,
        attempted_at: str,
    ) -> bool:
        with self._connect() as connection:
            run = connection.execute(
                """
                INSERT INTO ops.worker_runs
                    (worker_name, worker_version, deployment_identifier, run_id,
                     idempotency_key, started_at, heartbeat_at, status,
                     records_read, records_written, records_rejected, records_duplicated,
                     details_json)
                VALUES (%s, 'runtime', 'application', %s, %s, %s, %s, 'started', 0, 0, 0, 0, '{}'::jsonb)
                ON CONFLICT (worker_name, idempotency_key) DO NOTHING
                RETURNING id
                """,
                (worker_name, run_id, idempotency_key, attempted_at, attempted_at),
            ).fetchone()
            if run is None:
                return False
            connection.execute(
                """
                INSERT INTO ops.worker_status
                    (worker_name, asset_class, current_run_id, status,
                     last_attempted_at, last_successful_at, consecutive_failures,
                     total_failures, heartbeat_at, details_json)
                VALUES (%s, %s, %s, 'running', %s, NULL, 0, 0, %s, '{}'::jsonb)
                ON CONFLICT (worker_name) DO UPDATE SET
                    asset_class = EXCLUDED.asset_class,
                    current_run_id = EXCLUDED.current_run_id,
                    status = 'running',
                    last_attempted_at = EXCLUDED.last_attempted_at,
                    heartbeat_at = EXCLUDED.heartbeat_at
                """,
                (worker_name, asset_class, run_id, attempted_at, attempted_at),
            )
        return True

    def finish_success(
        self,
        *,
        worker_name: str,
        idempotency_key: str,
        finished_at: str,
        records_processed: int,
        details: Mapping[str, Any],
        data_fresh_at: str | None = None,
        source_fresh_at: str | None = None,
        pending_settlements: int = 0,
        model_state: str | None = None,
    ) -> bool:
        details_json = json.dumps(dict(details), sort_keys=True, default=str)
        with self._connect() as connection:
            completed = connection.execute(
                """
                UPDATE ops.worker_runs
                SET completed_at = %s, heartbeat_at = %s, status = 'completed', records_written = %s,
                    error_code = NULL, error_detail = NULL, details_json = %s::jsonb
                WHERE worker_name = %s AND idempotency_key = %s AND status = 'started'
                RETURNING id
                """,
                (finished_at, finished_at, int(records_processed), details_json, worker_name, idempotency_key),
            ).fetchone()
            if completed is None:
                return False
            connection.execute(
                """
                UPDATE ops.worker_status
                SET status = 'healthy', last_successful_at = %s, consecutive_failures = 0,
                    last_error_code = NULL, data_fresh_at = COALESCE(%s, data_fresh_at),
                    source_fresh_at = COALESCE(%s, source_fresh_at),
                    pending_settlements = %s, model_state = COALESCE(%s, model_state),
                    heartbeat_at = %s, details_json = %s::jsonb
                WHERE worker_name = %s
                """,
                (
                    finished_at,
                    data_fresh_at,
                    source_fresh_at,
                    int(pending_settlements),
                    model_state,
                    finished_at,
                    details_json,
                    worker_name,
                ),
            )
        return True

    def finish_failure(
        self,
        *,
        worker_name: str,
        idempotency_key: str,
        finished_at: str,
        error_code: str,
        details: Mapping[str, Any],
    ) -> int:
        safe_code = _safe_error_code(error_code) or "worker_failed"
        details_json = json.dumps(dict(details), sort_keys=True, default=str)
        with self._connect() as connection:
            failed = connection.execute(
                """
                UPDATE ops.worker_runs
                SET completed_at = %s, heartbeat_at = %s, status = 'failed', error_code = %s,
                    error_detail = %s, details_json = %s::jsonb
                WHERE worker_name = %s AND idempotency_key = %s AND status = 'started'
                RETURNING id
                """,
                (finished_at, finished_at, safe_code, safe_code, details_json, worker_name, idempotency_key),
            ).fetchone()
            if failed is None:
                return 0
            status = connection.execute(
                """
                UPDATE ops.worker_status
                SET status = 'failed', consecutive_failures = consecutive_failures + 1,
                    total_failures = total_failures + 1, last_error_code = %s,
                    heartbeat_at = %s, details_json = %s::jsonb
                WHERE worker_name = %s
                RETURNING consecutive_failures
                """,
                (safe_code, finished_at, details_json, worker_name),
            ).fetchone()
        return int(status["consecutive_failures"]) if status is not None else 0

    def heartbeat(self, worker_name: str, *, status: str = "healthy") -> bool:
        with self._connect() as connection:
            row = connection.execute(
                """
                UPDATE ops.worker_status SET status = %s, heartbeat_at = %s
                WHERE worker_name = %s
                RETURNING worker_name
                """,
                (status, utc_now_iso(), worker_name),
            ).fetchone()
        return row is not None

    def workers(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute("SELECT * FROM ops.worker_status ORDER BY worker_name").fetchall()
        return [dict(row) for row in rows]


def _pending_settlements(connection: DatabaseSession) -> dict[str, int]:
    return {
        "kalshi": int(connection.execute(
            "SELECT COUNT(*) AS count FROM app.prediction_logs WHERE validation_status='valid' AND settlement_state='unresolved'"
        ).fetchone()["count"]),
        "crypto": int(connection.execute(
            "SELECT COUNT(*) AS count FROM app.crypto_prediction_logs WHERE validation_status='valid' AND settlement_state='unresolved'"
        ).fetchone()["count"]),
        "sports": int(connection.execute(
            "SELECT COUNT(*) AS count FROM app.sports_prediction_logs WHERE validation_status='valid' AND settlement_state='unresolved'"
        ).fetchone()["count"]),
    }


def _settlement_delays(connection: DatabaseSession, *, now_iso: str) -> dict[str, int]:
    return {
        "kalshi": int(connection.execute(
            """
            SELECT COUNT(*) AS count FROM app.prediction_logs
            WHERE validation_status='valid' AND settlement_state='unresolved'
              AND COALESCE(event_start_time, market_close_time) IS NOT NULL
              AND COALESCE(event_start_time, market_close_time) < %s
            """,
            (now_iso,),
        ).fetchone()["count"]),
        "crypto": int(connection.execute(
            """
            SELECT COUNT(*) AS count FROM app.crypto_prediction_logs
            WHERE validation_status='valid' AND settlement_state='unresolved'
              AND settlement_time < %s
            """,
            (now_iso,),
        ).fetchone()["count"]),
        "sports": int(connection.execute(
            """
            SELECT COUNT(*) AS count FROM app.sports_prediction_logs
            WHERE validation_status='valid' AND settlement_state='unresolved'
              AND game_start_time < %s
            """,
            (now_iso,),
        ).fetchone()["count"]),
    }


def build_internal_status(
    settings: DatabaseSettings | None = None,
    *,
    heartbeat_stale_seconds: int = 900,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = now or datetime.now(timezone.utc)
    try:
        monitor = WorkerMonitorStore(settings)
        workers = monitor.workers()
        with connection_pool(monitor.settings).connection() as connection:
            pending = _pending_settlements(connection)
            settlement_delays = _settlement_delays(connection, now_iso=checked_at.isoformat())
            latest_models = [
                dict(row)
                for row in connection.execute(
                    """
                    SELECT DISTINCT ON (category)
                        category, model_state, model_version, dataset_version,
                        feature_version, evaluation_timestamp
                    FROM app.model_evaluations
                    ORDER BY category, evaluation_timestamp DESC, id DESC
                    """
                ).fetchall()
            ]
        database = {"state": "configured_healthy", "available": True, "backend": "postgres"}
    except Exception as exc:
        workers = []
        pending = {"kalshi": None, "crypto": None, "sports": None}
        settlement_delays = {"kalshi": None, "crypto": None, "sports": None}
        latest_models = []
        database = {
            "state": "configured_failed",
            "available": False,
            "backend": "postgres",
            "reason": f"database_unavailable:{type(exc).__name__}",
        }
    anomalies = []
    for worker in workers:
        heartbeat = _parse_timestamp(worker.get("heartbeat_at"))
        age = (checked_at - heartbeat).total_seconds() if heartbeat else None
        worker["heartbeat_age_seconds"] = age
        worker["heartbeat_state"] = "stale" if age is None or age > heartbeat_stale_seconds else "fresh"
        if worker["heartbeat_state"] == "stale":
            anomalies.append({"type": "stale_worker_heartbeat", "worker_name": worker["worker_name"]})
        if int(worker.get("consecutive_failures") or 0) >= 3:
            anomalies.append({"type": "consecutive_worker_failures", "worker_name": worker["worker_name"]})
        for freshness_field, anomaly_type in (
            ("data_fresh_at", "stale_market_data"),
            ("source_fresh_at", "stale_external_data"),
        ):
            fresh_at = _parse_timestamp(worker.get(freshness_field))
            if fresh_at and (checked_at - fresh_at).total_seconds() > heartbeat_stale_seconds:
                anomalies.append({"type": anomaly_type, "worker_name": worker["worker_name"]})
        if worker.get("model_state") == "drift_detected":
            anomalies.append({"type": "model_drift", "worker_name": worker["worker_name"]})
        details = _details_payload(worker.get("details_json"))
        api_attempts = int(details.get("api_attempts") or 0)
        api_failures = int(details.get("api_failures") or 0)
        if api_attempts >= 5 and api_failures / api_attempts >= 0.5:
            anomalies.append(
                {
                    "type": "high_api_failure_rate",
                    "worker_name": worker["worker_name"],
                    "failure_rate": api_failures / api_attempts,
                }
            )
    for asset_class, count in settlement_delays.items():
        if count and count > 0:
            anomalies.append({"type": "settlement_backlog", "asset_class": asset_class, "count": count})
    if not database["available"]:
        anomalies.append({"type": "database_failure"})
    connector_status = build_connectors_status()
    ready = database["available"] and not any(
        anomaly["type"] in {"stale_worker_heartbeat", "consecutive_worker_failures"}
        for anomaly in anomalies
    )
    return {
        "status": "ready" if ready else "degraded",
        "checked_at": checked_at.isoformat(),
        "database": database,
        "workers": workers,
        "pending_settlements": pending,
        "settlement_delays": settlement_delays,
        "models": latest_models,
        "connectors": connector_status.get("states", connector_status),
        "anomalies": anomalies,
        "public_exposure_allowed": False,
    }


def actionable_monitoring_events(status: Mapping[str, Any]) -> list[dict[str, Any]]:
    severity_by_type = {
        "database_failure": "critical",
        "consecutive_worker_failures": "critical",
        "stale_worker_heartbeat": "warning",
        "stale_market_data": "warning",
        "stale_external_data": "warning",
        "settlement_backlog": "warning",
        "model_drift": "warning",
        "high_api_failure_rate": "warning",
    }
    events = []
    for anomaly in status.get("anomalies") or []:
        event_type = str(anomaly.get("type") or "monitoring_anomaly")
        if event_type not in severity_by_type:
            continue
        events.append(
            {
                "severity": severity_by_type[event_type],
                "event_type": event_type,
                "message": json.dumps(anomaly, sort_keys=True),
                "next_action": "inspect /internal/status.json and the affected private worker",
            }
        )
    if status.get("status") != "ready" and not events:
        events.append(
            {
                "severity": "warning",
                "event_type": "readiness_failure",
                "message": "Internal application readiness is degraded",
                "next_action": "inspect /internal/status.json",
            }
        )
    return events


def send_monitoring_alerts(
    status: Mapping[str, Any],
    *,
    run_id: str,
    report_path: str | None = None,
) -> list[dict[str, Any]]:
    results = []
    for event in actionable_monitoring_events(status):
        alert = build_alert_payload(
            bot_name="platform-monitor",
            asset_class="all",
            run_id=run_id,
            severity=event["severity"],
            event_type=event["event_type"],
            message=event["message"],
            report_path=report_path,
            next_action=event["next_action"],
        )
        results.append(send_alert(alert))
    return results
