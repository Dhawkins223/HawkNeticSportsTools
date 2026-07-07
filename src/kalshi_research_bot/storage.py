from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from collections.abc import Iterator
from typing import Any

from .contracts import EdgeResult, SourceRecord


PREDICTION_LOG_COLUMNS = {
    "run_id": "TEXT",
    "event_id": "TEXT",
    "market_id": "TEXT",
    "strategy": "TEXT",
    "event_start_time": "TEXT",
    "market_close_time": "TEXT",
    "api_fetched_at": "TEXT",
    "source_updated_at": "TEXT",
    "source_snapshot_id": "TEXT",
    "source_snapshot_hash": "TEXT",
    "snapshot_sequence": "INTEGER NOT NULL DEFAULT 1",
    "entry_price_cents": "REAL",
    "implied_probability": "REAL",
    "reason_features_json": "TEXT NOT NULL DEFAULT '{}'",
    "validation_status": "TEXT NOT NULL DEFAULT 'invalid'",
    "validation_errors_json": "TEXT NOT NULL DEFAULT '[]'",
    "settlement_state": "TEXT NOT NULL DEFAULT 'unresolved'",
    "settlement_updated_at": "TEXT",
    "settlement_source": "TEXT",
    "settlement_issue": "TEXT",
}

NON_TRADABLE_MARKET_STATUSES = {
    "closed",
    "settled",
    "resolved",
    "canceled",
    "cancelled",
    "void",
    "inactive",
}


def _parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        timestamp = value
    else:
        try:
            timestamp = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


def _prediction_validation_errors(log: dict[str, Any]) -> list[str]:
    timestamp = _parse_timestamp(log.get("timestamp") or log.get("prediction_timestamp"))
    event_start = _parse_timestamp(log.get("event_start_time"))
    market_close = _parse_timestamp(log.get("market_close_time"))
    market_status = str(log.get("market_status") or log.get("status") or "").strip().lower()
    errors = list(log.get("validation_errors") or [])
    if not log.get("run_id"):
        errors.append("missing_run_id")
    if timestamp is None:
        errors.append("missing_prediction_timestamp")
    if event_start is None:
        errors.append("missing_event_start_time")
    if market_close is None:
        errors.append("missing_market_close_time")
    if timestamp and event_start and timestamp >= event_start:
        errors.append("prediction_after_event_start")
    if timestamp and market_close and timestamp >= market_close:
        errors.append("prediction_after_market_close")
    if event_start and market_close and market_close < event_start:
        errors.append("market_closes_before_event_start")
    if market_status in NON_TRADABLE_MARKET_STATUSES:
        errors.append(f"market_not_tradable:{market_status}")
    return sorted(set(errors))


def _validated_log(log: dict[str, Any]) -> dict[str, Any]:
    validated = dict(log)
    errors = _prediction_validation_errors(validated)
    validated["validation_errors"] = errors
    validated["validation_status"] = "invalid" if errors else "valid"
    validated["market_id"] = validated.get("market_id") or validated.get("market")
    validated["event_id"] = validated.get("event_id") or validated.get("event_ticker")
    validated["strategy"] = validated.get("strategy") or validated.get("slip_name")
    validated["source_snapshot_hash"] = validated.get("source_snapshot_hash") or validated.get("source_snapshot_id")
    if validated.get("settlement_state", "unresolved") == "unresolved":
        validated["actual_outcome"] = None
        validated["profit_loss_cents"] = None
    return validated


def _json_dump(value: Any) -> str:
    return json.dumps(value or {}, sort_keys=True)


class ResearchStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path)
        try:
            connection.execute("PRAGMA journal_mode=WAL")
            yield connection
            connection.commit()
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS source_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    url TEXT NOT NULL,
                    title TEXT NOT NULL,
                    text TEXT NOT NULL,
                    metadata_json TEXT NOT NULL,
                    collected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS edge_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticker TEXT NOT NULL,
                    game_id TEXT NOT NULL,
                    side TEXT NOT NULL,
                    model_probability REAL NOT NULL,
                    entry_price_cents REAL NOT NULL,
                    fair_price_cents REAL NOT NULL,
                    expected_value_cents REAL NOT NULL,
                    title TEXT NOT NULL,
                    notes_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS prediction_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    prediction_timestamp TEXT NOT NULL,
                    event TEXT NOT NULL,
                    event_id TEXT,
                    market TEXT NOT NULL,
                    market_id TEXT,
                    side TEXT NOT NULL,
                    strategy TEXT,
                    input_data_json TEXT NOT NULL,
                    odds_json TEXT NOT NULL,
                    model_version TEXT NOT NULL,
                    confidence_score REAL NOT NULL,
                    confidence_label TEXT NOT NULL,
                    predicted_outcome TEXT NOT NULL,
                    event_start_time TEXT,
                    market_close_time TEXT,
                    api_fetched_at TEXT,
                    source_updated_at TEXT,
                    source_snapshot_id TEXT,
                    source_snapshot_hash TEXT,
                    snapshot_sequence INTEGER NOT NULL DEFAULT 1,
                    entry_price_cents REAL,
                    implied_probability REAL,
                    reason_features_json TEXT NOT NULL DEFAULT '{}',
                    validation_status TEXT NOT NULL DEFAULT 'invalid',
                    validation_errors_json TEXT NOT NULL DEFAULT '[]',
                    settlement_state TEXT NOT NULL DEFAULT 'unresolved',
                    actual_outcome INTEGER,
                    profit_loss_cents REAL,
                    settlement_updated_at TEXT,
                    settlement_source TEXT,
                    settlement_issue TEXT,
                    slip_name TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS paper_test_runs (
                    run_id TEXT PRIMARY KEY,
                    started_at TEXT NOT NULL,
                    status TEXT NOT NULL,
                    model_versions_json TEXT NOT NULL,
                    config_json TEXT NOT NULL,
                    config_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS prediction_rejections (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    prediction_timestamp TEXT NOT NULL,
                    event TEXT NOT NULL,
                    event_id TEXT,
                    market TEXT NOT NULL,
                    market_id TEXT,
                    side TEXT NOT NULL,
                    strategy TEXT,
                    validation_errors_json TEXT NOT NULL,
                    raw_log_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS settlement_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    prediction_log_id INTEGER NOT NULL,
                    run_id TEXT NOT NULL,
                    market_id TEXT NOT NULL,
                    previous_settlement_state TEXT,
                    new_settlement_state TEXT,
                    previous_actual_outcome INTEGER,
                    new_actual_outcome INTEGER,
                    previous_profit_loss_cents REAL,
                    new_profit_loss_cents REAL,
                    source TEXT NOT NULL,
                    source_fetched_at TEXT,
                    issue TEXT,
                    raw_settlement_hash TEXT NOT NULL,
                    raw_settlement_json TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_settlement_audit_dedupe
                ON settlement_audit (
                    prediction_log_id, source, issue, new_settlement_state, raw_settlement_hash
                )
                """
            )
            connection.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_prediction_logs_run_dedupe
                ON prediction_logs (run_id, strategy, event_id, market_id, side, prediction_timestamp)
                WHERE run_id IS NOT NULL
                """
            )
            self._migrate_prediction_logs(connection)
            self._backfill_prediction_log_validation(connection)

    def _migrate_prediction_logs(self, connection: sqlite3.Connection) -> None:
        existing_columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(prediction_logs)").fetchall()
        }
        for column, column_type in PREDICTION_LOG_COLUMNS.items():
            if column not in existing_columns:
                connection.execute(f"ALTER TABLE prediction_logs ADD COLUMN {column} {column_type}")

    def _backfill_prediction_log_validation(self, connection: sqlite3.Connection) -> None:
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(prediction_logs)").fetchall()
        }
        required = {"id", "run_id", "prediction_timestamp", "event_start_time", "market_close_time", "validation_status", "validation_errors_json", "settlement_state"}
        if not required.issubset(columns):
            return
        rows = connection.execute(
            """
            SELECT id, run_id, prediction_timestamp, event_start_time, market_close_time,
                   settlement_state
            FROM prediction_logs
            """
        ).fetchall()
        updates = []
        for row_id, run_id, prediction_timestamp, event_start_time, market_close_time, settlement_state in rows:
            log = {
                "run_id": run_id,
                "timestamp": prediction_timestamp,
                "event_start_time": event_start_time,
                "market_close_time": market_close_time,
                "settlement_state": settlement_state or "unresolved",
            }
            errors = _prediction_validation_errors(log)
            updates.append(
                (
                    "invalid" if errors else "valid",
                    json.dumps(errors, sort_keys=True),
                    row_id,
                )
            )
        connection.executemany(
            """
            UPDATE prediction_logs
            SET validation_status = ?,
                validation_errors_json = ?,
                actual_outcome = CASE WHEN settlement_state = 'unresolved' THEN NULL ELSE actual_outcome END,
                profit_loss_cents = CASE WHEN settlement_state = 'unresolved' THEN NULL ELSE profit_loss_cents END
            WHERE id = ?
            """,
            updates,
        )

    def insert_source_records(self, records: list[SourceRecord]) -> None:
        if not records:
            return
        self.initialize()
        rows = [
            (
                record.source,
                record.kind,
                record.url,
                record.title,
                record.text,
                json.dumps(record.metadata, sort_keys=True),
            )
            for record in records
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO source_records
                    (source, kind, url, title, text, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def insert_edge_results(self, edges: list[EdgeResult]) -> None:
        if not edges:
            return
        self.initialize()
        rows = [
            (
                edge.ticker,
                edge.game_id,
                edge.side,
                edge.model_probability,
                edge.entry_price_cents,
                edge.fair_price_cents,
                edge.expected_value_cents,
                edge.title,
                json.dumps(edge.notes),
            )
            for edge in edges
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO edge_results
                    (ticker, game_id, side, model_probability, entry_price_cents,
                     fair_price_cents, expected_value_cents, title, notes_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def insert_prediction_logs(self, logs: list[dict]) -> int:
        if not logs:
            return 0
        self.initialize()
        validated_logs = [_validated_log(log) for log in logs]
        rows = [
            (
                log.get("run_id"),
                log.get("timestamp", ""),
                log.get("event", ""),
                log.get("event_id"),
                log.get("market", ""),
                log.get("market_id"),
                log.get("side", ""),
                log.get("strategy"),
                _json_dump(log.get("input_data_used", {})),
                _json_dump(log.get("odds_used", {})),
                log.get("model_version", ""),
                float(log.get("confidence_score") or 0.0),
                log.get("confidence_label", ""),
                log.get("predicted_outcome", ""),
                log.get("event_start_time"),
                log.get("market_close_time"),
                log.get("api_fetched_at"),
                log.get("source_updated_at"),
                log.get("source_snapshot_id"),
                log.get("source_snapshot_hash"),
                int(log.get("snapshot_sequence") or 1),
                log.get("entry_price_cents"),
                log.get("implied_probability"),
                _json_dump(log.get("reason_features", {})),
                log.get("validation_status", "invalid"),
                json.dumps(log.get("validation_errors", []), sort_keys=True),
                log.get("settlement_state", "unresolved"),
                None if log.get("actual_outcome") is None else int(bool(log.get("actual_outcome"))),
                None if log.get("settlement_state", "unresolved") == "unresolved" else log.get("profit_loss_cents"),
                log.get("slip_name", ""),
            )
            for log in validated_logs
        ]
        with self.connect() as connection:
            cursor = connection.executemany(
                """
                INSERT OR IGNORE INTO prediction_logs
                    (run_id, prediction_timestamp, event, event_id, market,
                     market_id, side, strategy, input_data_json,
                     odds_json, model_version, confidence_score, confidence_label,
                     predicted_outcome, event_start_time, market_close_time, api_fetched_at,
                     source_updated_at, source_snapshot_id, source_snapshot_hash,
                     snapshot_sequence, entry_price_cents, implied_probability, reason_features_json,
                     validation_status,
                     validation_errors_json, settlement_state, actual_outcome,
                     profit_loss_cents, slip_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
            return int(cursor.rowcount or 0)

    def create_paper_test_run(self, run: dict[str, Any]) -> None:
        self.initialize()
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO paper_test_runs
                    (run_id, started_at, status, model_versions_json, config_json, config_hash)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    run["run_id"],
                    run["started_at"],
                    run.get("status", "active"),
                    _json_dump(run.get("model_versions", {})),
                    _json_dump(run.get("config", {})),
                    run["config_hash"],
                ),
            )

    def insert_prediction_rejections(self, rejections: list[dict[str, Any]]) -> None:
        if not rejections:
            return
        self.initialize()
        rows = [
            (
                rejection.get("run_id", ""),
                rejection.get("timestamp", ""),
                rejection.get("event", ""),
                rejection.get("event_id"),
                rejection.get("market", ""),
                rejection.get("market_id"),
                rejection.get("side", ""),
                rejection.get("strategy"),
                json.dumps(rejection.get("validation_errors", []), sort_keys=True),
                _json_dump(rejection.get("raw_log", {})),
            )
            for rejection in rejections
        ]
        with self.connect() as connection:
            connection.executemany(
                """
                INSERT INTO prediction_rejections
                    (run_id, prediction_timestamp, event, event_id, market,
                     market_id, side, strategy, validation_errors_json, raw_log_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
