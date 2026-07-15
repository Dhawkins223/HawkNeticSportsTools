from __future__ import annotations

import os
import re
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Sequence

from .database import DatabaseSettings, database_startup_status
from .db_migrations import apply_postgres_migrations
from .storage import ResearchStore


HOSTED_SQLITE_OVERRIDE = "ALLOW_HOSTED_SQLITE_RUNTIME"


def hosted_environment(env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    return bool(
        values.get("RAILWAY_ENVIRONMENT")
        or values.get("RAILWAY_PROJECT_ID")
        or str(values.get("APP_ENV") or "").strip().lower() in {"staging", "production"}
    )


def _env_bool(name: str, default: bool = False, env: Mapping[str, str] | None = None) -> bool:
    values = os.environ if env is None else env
    raw = values.get(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def resolve_database_settings(
    db_path: str | Path | None = None,
    *,
    settings: DatabaseSettings | None = None,
) -> DatabaseSettings:
    configured = settings or DatabaseSettings.from_env()
    if db_path is not None and configured.backend == "sqlite":
        return DatabaseSettings(
            backend="sqlite",
            sqlite_path=str(db_path),
            database_url=None,
            pool_min_size=configured.pool_min_size,
            pool_max_size=configured.pool_max_size,
            migration_mode=configured.migration_mode,
            connect_timeout_seconds=configured.connect_timeout_seconds,
            statement_timeout_ms=configured.statement_timeout_ms,
        )
    return configured


def _enforce_hosted_backend(settings: DatabaseSettings) -> None:
    if settings.backend == "sqlite" and hosted_environment() and not _env_bool(HOSTED_SQLITE_OVERRIDE, False):
        raise RuntimeError("hosted_runtime_requires_postgres_business_store")
    if settings.backend == "postgres" and not settings.database_url:
        raise RuntimeError("postgres_business_store_requires_database_url")


def active_database_backend(db_path: str | Path | None = None, *, settings: DatabaseSettings | None = None) -> str:
    configured = resolve_database_settings(db_path, settings=settings)
    _enforce_hosted_backend(configured)
    return configured.backend


def create_research_store(
    db_path: str | Path | None = None,
    *,
    settings: DatabaseSettings | None = None,
) -> ResearchStore:
    configured = resolve_database_settings(db_path, settings=settings)
    _enforce_hosted_backend(configured)
    if configured.backend == "sqlite":
        return ResearchStore(configured.sqlite_path)
    return PostgresResearchStore(configured)


def open_legacy_connection(
    db_path: str | Path | None = None,
    *,
    settings: DatabaseSettings | None = None,
    initialize: bool = True,
):
    configured = resolve_database_settings(db_path, settings=settings)
    _enforce_hosted_backend(configured)
    if configured.backend == "sqlite":
        path = Path(configured.sqlite_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        if initialize:
            ResearchStore(path).initialize()
        connection = sqlite3.connect(path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        return connection
    if initialize:
        ensure_postgres_ready(configured)
    return PostgresCompatConnection(configured)


def ensure_postgres_ready(settings: DatabaseSettings) -> None:
    if settings.migration_mode == "apply":
        apply_postgres_migrations(settings.database_url or "")
    status = database_startup_status(settings)
    if not status.get("ready"):
        reason = status.get("reason") or status.get("pending_versions") or status.get("state") or "unknown"
        raise RuntimeError(f"postgres_business_store_not_ready:{reason}")


class PostgresResearchStore(ResearchStore):
    backend = "postgres"

    def __init__(self, settings: DatabaseSettings) -> None:
        self.settings = settings
        self.path = Path(settings.sqlite_path)

    def initialize(self) -> None:
        ensure_postgres_ready(self.settings)

    @contextmanager
    def connect(self) -> Iterator["PostgresCompatConnection"]:
        self.initialize()
        connection = PostgresCompatConnection(self.settings)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


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
        return iter(self._columns)

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


def _cursor_column_name(column: Any) -> str:
    name = getattr(column, "name", None)
    if name is not None:
        return str(name)
    return str(column[0])


class PostgresCompatCursor:
    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor
        self.rowcount = int(getattr(cursor, "rowcount", -1) or 0)
        self.description = []
        if cursor.description:
            self.description = [(_cursor_column_name(column),) for column in cursor.description]
        self.lastrowid = None

    def _wrap(self, row: Any):
        if row is None:
            return None
        columns = [column[0] for column in self.description]
        if isinstance(row, Mapping):
            return HybridRow(columns or list(row.keys()), [row.get(column) for column in (columns or row.keys())])
        return HybridRow(columns or [str(index) for index in range(len(row))], list(row))

    def fetchone(self):
        return self._wrap(self._cursor.fetchone())

    def fetchall(self):
        return [self._wrap(row) for row in self._cursor.fetchall()]


class PostgresCompatConnection:
    backend = "postgres"

    def __init__(self, settings: DatabaseSettings) -> None:
        try:
            import psycopg
        except ImportError as exc:  # pragma: no cover - exercised only without optional dep
            raise RuntimeError("postgres_driver_unavailable_install_postgres_extra") from exc
        self.settings = settings
        self._connection = psycopg.connect(
            settings.database_url or "",
            autocommit=False,
            connect_timeout=settings.connect_timeout_seconds,
            options=f"-c statement_timeout={settings.statement_timeout_ms} -c timezone=UTC",
        )

    def execute(self, sql: str, parameters: Sequence[Any] | Mapping[str, Any] | None = None):
        special = self._special_cursor(sql, parameters)
        if special is not None:
            return special
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
        self._connection.close()

    def _special_cursor(self, sql: str, parameters: Sequence[Any] | Mapping[str, Any] | None):
        normalized = " ".join(str(sql).strip().split()).lower()
        if normalized.startswith("pragma table_info"):
            match = re.search(r"pragma\s+table_info\(([^)]+)\)", str(sql), re.IGNORECASE)
            table = match.group(1).strip().strip('"').strip(chr(96)).strip('[').strip(']') if match else ""
            cursor = self._connection.execute(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = %s
                ORDER BY ordinal_position
                """,
                (table,),
            )
            rows = [HybridRow(["cid", "name"], [index, row[0]]) for index, row in enumerate(cursor.fetchall())]
            return ManualCursor(rows=rows, rowcount=len(rows), columns=["cid", "name"])
        if " from sqlite_master " in f" {normalized} ":
            params = _normalize_parameters(parameters)
            table = params[-1] if isinstance(params, Sequence) and params else None
            if table is None:
                match = re.search(r"name\s*=\s*'([^']+)'", str(sql), re.IGNORECASE)
                table = match.group(1) if match else ""
            cursor = self._connection.execute(
                """
                SELECT table_name AS name
                FROM information_schema.tables
                WHERE table_schema = 'public' AND table_name = %s
                """,
                (table,),
            )
            rows = [HybridRow(["name"], [row[0]]) for row in cursor.fetchall()]
            if normalized.startswith("select 1"):
                rows = [HybridRow(["1"], [1]) for _ in rows]
            return ManualCursor(rows=rows, rowcount=len(rows), columns=["name"] if not normalized.startswith("select 1") else ["1"])
        if normalized.startswith("pragma") or normalized.startswith("begin immediate") or normalized == "begin":
            return ManualCursor()
        return None


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
    compact = " ".join(text.split()).lower()
    if compact.startswith("pragma") or compact.startswith("begin immediate") or compact == "begin":
        return None
    insert_ignore = bool(re.match(r"\s*insert\s+or\s+ignore\s+into\s+", text, re.IGNORECASE))
    if insert_ignore:
        text = re.sub(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", "INSERT INTO", text, count=1, flags=re.IGNORECASE)
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
