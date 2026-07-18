from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .connectors.status import build_connectors_status
from .connectors.slack_alerts import build_alert_payload, send_alert
from .business_store import active_database_backend, open_legacy_connection
from .storage import ResearchStore


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
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
    text = str(value).replace("\r", " ").replace("\n", " ")
    return text[:160]


class WorkerMonitorStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if active_database_backend(self.path) == "sqlite":
            ResearchStore(self.path).initialize()
        else:
            connection = open_legacy_connection(self.path)
            connection.close()

    def _connect(self):
        return open_legacy_connection(self.path)

    def start_run(
        self,
        *,
        worker_name: str,
        asset_class: str,
        run_id: str,
        idempotency_key: str,
        attempted_at: str,
    ) -> bool:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO worker_runs
                    (worker_name, run_id, idempotency_key, attempted_at, status,
                     records_processed, details_json)
                VALUES (?, ?, ?, ?, 'running', 0, '{}')
                """,
                (worker_name, run_id, idempotency_key, attempted_at),
            )
            if cursor.rowcount == 0:
                connection.rollback()
                return False
            connection.execute(
                """
                INSERT INTO worker_status
                    (worker_name, asset_class, current_run_id, status,
                     last_attempted_at, last_successful_at, consecutive_failures,
                     total_failures, heartbeat_at, details_json)
                VALUES (?, ?, ?, 'running', ?, NULL, 0, 0, ?, '{}')
                ON CONFLICT(worker_name) DO UPDATE SET
                    asset_class = excluded.asset_class,
                    current_run_id = excluded.current_run_id,
                    status = 'running',
                    last_attempted_at = excluded.last_attempted_at,
                    heartbeat_at = excluded.heartbeat_at
                """,
                (worker_name, asset_class, run_id, attempted_at, attempted_at),
            )
            connection.commit()
            return True
        finally:
            connection.close()

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
    ) -> None:
        details_json = json.dumps(dict(details), sort_keys=True, default=str)
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE worker_runs
                SET finished_at = ?, status = 'success', records_processed = ?,
                    error_code = NULL, details_json = ?
                WHERE worker_name = ? AND idempotency_key = ?
                """,
                (finished_at, int(records_processed), details_json, worker_name, idempotency_key),
            )
            connection.execute(
                """
                UPDATE worker_status
                SET status = 'healthy', last_successful_at = ?, consecutive_failures = 0,
                    last_error_code = NULL, data_fresh_at = COALESCE(?, data_fresh_at),
                    source_fresh_at = COALESCE(?, source_fresh_at),
                    pending_settlements = ?, model_state = COALESCE(?, model_state),
                    heartbeat_at = ?, details_json = ?
                WHERE worker_name = ?
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
            connection.commit()
        finally:
            connection.close()

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
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE worker_runs
                SET finished_at = ?, status = 'failed', error_code = ?, details_json = ?
                WHERE worker_name = ? AND idempotency_key = ?
                """,
                (finished_at, safe_code, details_json, worker_name, idempotency_key),
            )
            connection.execute(
                """
                UPDATE worker_status
                SET status = 'failed', consecutive_failures = consecutive_failures + 1,
                    total_failures = total_failures + 1, last_error_code = ?,
                    heartbeat_at = ?, details_json = ?
                WHERE worker_name = ?
                """,
                (safe_code, finished_at, details_json, worker_name),
            )
            row = connection.execute(
                "SELECT consecutive_failures FROM worker_status WHERE worker_name = ?",
                (worker_name,),
            ).fetchone()
            connection.commit()
            return int(row[0] if row else 0)
        finally:
            connection.close()

    def heartbeat(self, worker_name: str, *, status: str = "healthy") -> None:
        connection = self._connect()
        try:
            connection.execute(
                "UPDATE worker_status SET status = ?, heartbeat_at = ? WHERE worker_name = ?",
                (status, utc_now_iso(), worker_name),
            )
            connection.commit()
        finally:
            connection.close()

    def workers(self) -> list[dict[str, Any]]:
        connection = self._connect()
        try:
            return [dict(row) for row in connection.execute("SELECT * FROM worker_status ORDER BY worker_name")]
        finally:
            connection.close()


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _pending_settlements(connection: sqlite3.Connection) -> dict[str, int]:
    result = {"kalshi": 0, "crypto": 0, "sports": 0}
    if _table_exists(connection, "prediction_logs"):
        result["kalshi"] = int(connection.execute(
            "SELECT COUNT(*) FROM prediction_logs WHERE validation_status='valid' AND settlement_state='unresolved'"
        ).fetchone()[0])
    if _table_exists(connection, "crypto_prediction_logs"):
        result["crypto"] = int(connection.execute(
            "SELECT COUNT(*) FROM crypto_prediction_logs WHERE validation_status='valid' AND settlement_state='unresolved'"
        ).fetchone()[0])
    if _table_exists(connection, "sports_prediction_logs"):
        result["sports"] = int(connection.execute(
            "SELECT COUNT(*) FROM sports_prediction_logs WHERE validation_status='valid' AND settlement_state='unresolved'"
        ).fetchone()[0])
    return result


def _settlement_delays(connection: sqlite3.Connection, *, now_iso: str) -> dict[str, int]:
    result = {"kalshi": 0, "crypto": 0, "sports": 0}
    if _table_exists(connection, "prediction_logs"):
        result["kalshi"] = int(connection.execute(
            """
            SELECT COUNT(*) FROM prediction_logs
            WHERE validation_status='valid' AND settlement_state='unresolved'
              AND COALESCE(event_start_time, market_close_time) IS NOT NULL
              AND COALESCE(event_start_time, market_close_time) < ?
            """,
            (now_iso,),
        ).fetchone()[0])
    if _table_exists(connection, "crypto_prediction_logs"):
        result["crypto"] = int(connection.execute(
            """
            SELECT COUNT(*) FROM crypto_prediction_logs
            WHERE validation_status='valid' AND settlement_state='unresolved'
              AND settlement_time < ?
            """,
            (now_iso,),
        ).fetchone()[0])
    if _table_exists(connection, "sports_prediction_logs"):
        result["sports"] = int(connection.execute(
            """
            SELECT COUNT(*) FROM sports_prediction_logs
            WHERE validation_status='valid' AND settlement_state='unresolved'
              AND game_start_time < ?
            """,
            (now_iso,),
        ).fetchone()[0])
    return result


def build_internal_status(
    db_path: str | Path,
    *,
    heartbeat_stale_seconds: int = 900,
    now: datetime | None = None,
) -> dict[str, Any]:
    checked_at = now or datetime.now(timezone.utc)
    path = Path(db_path)
    try:
        monitor = WorkerMonitorStore(path)
        workers = monitor.workers()
        connection = open_legacy_connection(path)
        try:
            pending = _pending_settlements(connection)
            settlement_delays = _settlement_delays(connection, now_iso=checked_at.isoformat())
            latest_models = [
                dict(row)
                for cursor in [connection.execute(
                    """
                    SELECT category, model_state, model_version, dataset_version,
                           feature_version, evaluation_timestamp
                    FROM model_evaluations
                    WHERE id IN (SELECT MAX(id) FROM model_evaluations GROUP BY category)
                    ORDER BY category
                    """
                )]
                for row in cursor.fetchall()
            ] if _table_exists(connection, "model_evaluations") else []
        finally:
            connection.close()
        database = {"state": "configured_healthy", "available": True, "backend": active_database_backend(path)}
    except Exception as exc:
        workers = []
        pending = {"kalshi": None, "crypto": None, "sports": None}
        settlement_delays = {"kalshi": None, "crypto": None, "sports": None}
        latest_models = []
        database = {
            "state": "configured_failed",
            "available": False,
            "backend": "unknown",
            "reason": f"database_unavailable:{type(exc).__name__}",
        }
    anomalies = []
    for worker in workers:
        heartbeat = _parse_timestamp(worker.get("heartbeat_at"))
        age = (checked_at - heartbeat).total_seconds() if heartbeat else None
        worker["heartbeat_age_seconds"] = age
        worker["heartbeat_state"] = (
            "stale" if age is None or age > heartbeat_stale_seconds else "fresh"
        )
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
        details = {}
        try:
            details = json.loads(worker.get("details_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            pass
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
