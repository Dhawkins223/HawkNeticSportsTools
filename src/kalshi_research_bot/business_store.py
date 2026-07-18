from __future__ import annotations

import os
import hashlib
import json
import re
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from dataclasses import replace
from decimal import Decimal
from datetime import datetime, timezone
from typing import Any, Sequence

from .contracts import EdgeResult, SourceRecord
from .database import DatabaseSettings, database_startup_status, postgres_connection_pool
from .postgres_db_migrations import apply_postgres_migrations

TEST_SCHEMA_FROM_PATH_ENV = "HAWKNETIC_TEST_POSTGRES_SCHEMAS"
NON_TRADABLE_MARKET_STATUSES = {
    "closed",
    "settled",
    "resolved",
    "canceled",
    "cancelled",
    "void",
    "inactive",
}


def _test_schema_enabled() -> bool:
    return str(os.environ.get(TEST_SCHEMA_FROM_PATH_ENV) or "").strip().lower() in {"1", "true", "yes", "on"}


def _test_schema_for_path(path: str | os.PathLike[str]) -> str:
    digest = hashlib.sha256(os.fspath(path).encode("utf-8", errors="replace")).hexdigest()[:24]
    return f"test_{digest}"


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
    return timestamp.replace(tzinfo=timezone.utc) if timestamp.tzinfo is None else timestamp


def _prediction_validation_errors(log: Mapping[str, Any]) -> list[str]:
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


def _validated_log(log: Mapping[str, Any]) -> dict[str, Any]:
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
    return json.dumps(value or {}, sort_keys=True, default=str)


def _optional_timestamp(value: Any) -> Any:
    return None if value is None or str(value).strip() == "" else value


def resolve_database_settings(
    db_path: str | os.PathLike[str] | None = None,
    *,
    settings: DatabaseSettings | None = None,
) -> DatabaseSettings:
    configured = settings or DatabaseSettings.from_env()
    if db_path is not None:
        if not _test_schema_enabled():
            raise RuntimeError("runtime_database_path_not_supported_use_DATABASE_URL")
        return replace(configured, schema=_test_schema_for_path(db_path))
    return configured


def active_database_backend(db_path: str | os.PathLike[str] | None = None, *, settings: DatabaseSettings | None = None) -> str:
    resolve_database_settings(db_path, settings=settings)
    return "postgres"


def create_research_store(
    db_path: str | os.PathLike[str] | None = None,
    *,
    settings: DatabaseSettings | None = None,
) -> "PostgresResearchStore":
    configured = resolve_database_settings(db_path, settings=settings)
    return PostgresResearchStore(configured)


def open_runtime_connection(
    db_path: str | os.PathLike[str] | None = None,
    *,
    settings: DatabaseSettings | None = None,
    initialize: bool = True,
):
    configured = resolve_database_settings(db_path, settings=settings)
    if initialize:
        ensure_postgres_ready(configured)
    return PostgresCompatConnection(configured)


def ensure_postgres_ready(settings: DatabaseSettings) -> None:
    if settings.migration_mode == "apply":
        migration_url = str(os.environ.get("DATABASE_MIGRATION_URL") or settings.database_url).strip()
        apply_postgres_migrations(migration_url, schema=settings.schema)
    status = database_startup_status(settings)
    if not status.get("ready"):
        reason = status.get("reason") or status.get("pending_versions") or status.get("state") or "unknown"
        raise RuntimeError(f"postgres_business_store_not_ready:{reason}")


class PostgresResearchStore:
    backend = "postgres"

    def __init__(self, settings: DatabaseSettings) -> None:
        self.settings = settings

    def initialize(self) -> None:
        ensure_postgres_ready(self.settings)

    @contextmanager
    def connect(self) -> Iterator["PostgresCompatConnection"]:
        self.initialize()
        connection = open_runtime_connection(settings=self.settings, initialize=False)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def insert_source_records(self, records: list[SourceRecord]) -> None:
        if not records:
            return
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
                json.dumps(edge.notes, sort_keys=True),
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

    def insert_prediction_logs(self, logs: list[dict[str, Any]]) -> int:
        if not logs:
            return 0
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
                _optional_timestamp(log.get("event_start_time")),
                _optional_timestamp(log.get("market_close_time")),
                _optional_timestamp(log.get("api_fetched_at")),
                _optional_timestamp(log.get("source_updated_at")),
                log.get("source_snapshot_id"),
                log.get("source_snapshot_hash"),
                int(log.get("snapshot_sequence") or 1),
                log.get("entry_price_cents"),
                log.get("implied_probability"),
                _json_dump(log.get("reason_features", {})),
                log.get("validation_status", "invalid"),
                json.dumps(log.get("validation_errors", []), sort_keys=True),
                log.get("settlement_state", "unresolved"),
                None if log.get("actual_outcome") is None else bool(log.get("actual_outcome")),
                None if log.get("settlement_state", "unresolved") == "unresolved" else log.get("profit_loss_cents"),
                log.get("slip_name", ""),
            )
            for log in (_validated_log(log) for log in logs)
        ]
        statement = """
            INSERT INTO prediction_logs
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
            ON CONFLICT DO NOTHING
            RETURNING id
        """
        with self.connect() as connection:
            inserted = 0
            for row in rows:
                cursor = connection.execute(statement, row)
                inserted += 1 if cursor.fetchone() is not None else 0
            return inserted

    def create_paper_test_run(self, run: Mapping[str, Any]) -> None:
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

    def insert_prediction_rejections(self, rejections: list[Mapping[str, Any]]) -> None:
        if not rejections:
            return
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


def start_report_refresh(
    connection: Any,
    *,
    refresh_id: str,
    report_name: str,
    data_cutoff_at: str,
    started_at: str,
) -> None:
    connection.execute(
        """
        INSERT OR IGNORE INTO report_refreshes
            (refresh_id, report_name, data_cutoff_at, started_at, status)
        VALUES (?, ?, ?, ?, 'started')
        """,
        (refresh_id, report_name, data_cutoff_at, started_at),
    )


def finish_report_refresh(
    connection: Any,
    *,
    refresh_id: str,
    completed_at: str,
    status: str,
    row_count: int | None = None,
    error_code: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE report_refreshes
        SET completed_at = ?, status = ?, row_count = ?, error_code = ?
        WHERE refresh_id = ?
        """,
        (completed_at, status, row_count, error_code, refresh_id),
    )


class HybridRow(Mapping[str, Any]):
    def __init__(self, columns: Sequence[str], values: Sequence[Any]) -> None:
        self._columns = [str(column) for column in columns]
        self._values = list(values)
        self._data = dict(zip(self._columns, self._values))

    def __getitem__(self, key: str | int) -> Any:  # type: ignore[override]
        if isinstance(key, int):
            return self._values[key]
        return self._data[key]

    def __iter__(self):
        # Match the historical row sequence behavior so legacy query idioms such as
        # ``dict(cursor.fetchall())`` continue to use the first two values.
        # ``dict(row)`` still uses the explicit keys() mapping protocol below.
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._columns)

    def keys(self):
        return self._data.keys()

    def values(self):
        return self._data.values()

    def items(self):
        return self._data.items()

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __repr__(self) -> str:
        return repr(self._data)


class ManualCursor:
    def __init__(self, rows: list[HybridRow] | None = None, rowcount: int = 0, columns: Sequence[str] | None = None) -> None:
        self._rows = rows or []
        self._index = 0
        self.rowcount = rowcount
        if columns is None and self._rows:
            columns = list(self._rows[0].keys())
        self.description = [(column,) for column in (columns or [])]
        self.lastrowid = None

    def fetchone(self):
        if self._index >= len(self._rows):
            return None
        row = self._rows[self._index]
        self._index += 1
        return row

    def fetchall(self):
        rows = self._rows[self._index:]
        self._index = len(self._rows)
        return rows

    def __iter__(self):
        return iter(self.fetchall())


def _cursor_column_name(column: Any) -> str:
    name = getattr(column, "name", None)
    if name is not None:
        return str(name)
    return str(column[0])


class PostgresCompatCursor:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        self.rowcount = max(0, int(getattr(cursor, "rowcount", -1) or 0))
        self.description = []
        if cursor.description:
            self.description = [(_cursor_column_name(column),) for column in cursor.description]
        self.lastrowid = None

    def _wrap(self, row: Any):
        if row is None:
            return None
        columns = [column[0] for column in self.description]
        if isinstance(row, Mapping):
            return HybridRow(
                columns or list(row.keys()),
                [_compat_runtime_value(row.get(column)) for column in (columns or row.keys())],
            )
        return HybridRow(
            columns or [str(index) for index in range(len(row))],
            [_compat_runtime_value(value) for value in row],
        )

    def fetchone(self):
        return self._wrap(self._cursor.fetchone())

    def fetchall(self):
        return [self._wrap(row) for row in self._cursor.fetchall()]

    def __iter__(self):
        return iter(self.fetchall())


def _compat_runtime_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return str(value.astimezone(timezone.utc))
    if isinstance(value, Decimal):
        return float(value)
    return value


class PostgresCompatConnection:
    backend = "postgres"

    def __init__(self, settings: DatabaseSettings) -> None:
        self.settings = settings
        self._pool = postgres_connection_pool(settings)
        self._connection = self._pool.acquire()
        self._closed = False

    def execute(self, sql: str, parameters: Sequence[Any] | Mapping[str, Any] | None = None):
        transformed = _transform_sql(sql)
        if transformed is None:
            return ManualCursor()
        cursor = self._connection.execute(transformed, _normalize_parameters(parameters))
        return PostgresCompatCursor(cursor)

    def executemany(self, sql: str, seq_of_parameters: Sequence[Sequence[Any] | Mapping[str, Any]]):
        transformed = _transform_sql(sql)
        if transformed is None:
            return ManualCursor(rowcount=0)
        cursor = self._connection.cursor()
        cursor.executemany(transformed, [_normalize_parameters(parameters) for parameters in seq_of_parameters])
        return PostgresCompatCursor(cursor)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        self._connection.rollback()

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self._connection.rollback()
        except Exception:
            pass
        self._pool.release(self._connection)

    def __enter__(self) -> "PostgresCompatConnection":
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        self.close()
        return False

def _normalize_parameters(parameters: Sequence[Any] | Mapping[str, Any] | None):
    if parameters is None:
        return ()
    if isinstance(parameters, Mapping):
        return dict(parameters)
    return tuple(parameters)


def _transform_sql(sql: str) -> str | None:
    text = str(sql).strip()
    if not text:
        return None
    insert_ignore = bool(re.match(r"\s*insert\s+or\s+ignore\s+into\s+", text, re.IGNORECASE))
    if insert_ignore:
        text = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", text, count=1, flags=re.IGNORECASE)
    text = re.sub(r"\bIS\s+NOT\s+\?", "IS DISTINCT FROM ?", text, flags=re.IGNORECASE)
    text = re.sub(r"\bIS\s+\?", "IS NOT DISTINCT FROM ?", text, flags=re.IGNORECASE)
    text = _convert_qmark_placeholders(text)
    if insert_ignore and " on conflict " not in f" {text.lower()} ":
        text = text.rstrip().rstrip(";") + " ON CONFLICT DO NOTHING"
    return text


def _convert_qmark_placeholders(sql: str) -> str:
    output: list[str] = []
    in_single = False
    index = 0
    while index < len(sql):
        char = sql[index]
        if char == "'":
            output.append(char)
            if in_single and index + 1 < len(sql) and sql[index + 1] == "'":
                output.append(sql[index + 1])
                index += 2
                continue
            in_single = not in_single
        elif char == "?" and not in_single:
            output.append("%s")
        else:
            output.append(char)
        index += 1
    return "".join(output)
