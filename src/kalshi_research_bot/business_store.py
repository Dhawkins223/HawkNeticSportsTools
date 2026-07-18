from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator

from .database import DatabaseSession, DatabaseSettings, database_startup_status
from .db_migrations import apply_postgres_migrations
from .storage import PostgresStore


def ensure_database_ready(settings: DatabaseSettings | None = None) -> DatabaseSettings:
    configured = settings or DatabaseSettings.from_env()
    if configured.migration_mode == "apply":
        apply_postgres_migrations(configured.require_url())
    status = database_startup_status(configured)
    if not status.get("ready"):
        reason = status.get("reason") or status.get("pending_versions") or status.get("state") or "unknown"
        raise RuntimeError(f"postgres_database_not_ready:{reason}")
    return configured


def create_store(namespace: str | None = None, *, settings: DatabaseSettings | None = None) -> PostgresStore:
    configured = ensure_database_ready(settings)
    return PostgresStore(namespace, settings=configured)


@contextmanager
def open_connection(namespace: str | None = None, *, settings: DatabaseSettings | None = None) -> Iterator[DatabaseSession]:
    store = create_store(namespace, settings=settings)
    with store.connect() as connection:
        yield connection


def start_report_refresh(
    connection: DatabaseSession,
    *,
    refresh_id: str,
    report_name: str,
    data_cutoff_at: str,
    started_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO ops.report_refreshes (refresh_id, report_name, data_cutoff_at, started_at, status)
        VALUES (%s, %s, %s, %s, 'started')
        ON CONFLICT (refresh_id) DO NOTHING
        """,
        (refresh_id, report_name, data_cutoff_at, started_at),
    )


def finish_report_refresh(
    connection: DatabaseSession,
    *,
    refresh_id: str,
    completed_at: str,
    status: str,
    row_count: int | None = None,
    error_code: str | None = None,
) -> None:
    connection.execute(
        """
        UPDATE ops.report_refreshes
        SET completed_at = %s, status = %s, row_count = %s, error_code = %s
        WHERE refresh_id = %s
        """,
        (completed_at, status, row_count, error_code, refresh_id),
    )
