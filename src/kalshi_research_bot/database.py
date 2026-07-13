from __future__ import annotations

import os
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse

from .db_migrations import postgres_migration_status


@dataclass(frozen=True)
class DatabaseSettings:
    backend: str
    sqlite_path: str
    database_url: str | None
    pool_min_size: int
    pool_max_size: int
    migration_mode: str

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        database_url = os.environ.get("DATABASE_URL") or None
        backend = str(os.environ.get("DATABASE_BACKEND") or ("postgres" if database_url else "sqlite")).strip().lower()
        if backend not in {"sqlite", "postgres"}:
            raise ValueError(f"unsupported_database_backend:{backend}")
        migration_mode = str(os.environ.get("DATABASE_MIGRATION_MODE") or "check").strip().lower()
        if migration_mode not in {"check", "apply"}:
            raise ValueError("database_migration_mode_must_be_check_or_apply")
        return cls(
            backend=backend,
            sqlite_path=os.environ.get("EVALUATION_DB_PATH", "data/evaluation.sqlite"),
            database_url=database_url,
            pool_min_size=max(1, int(os.environ.get("DATABASE_POOL_MIN_SIZE", "1"))),
            pool_max_size=max(1, int(os.environ.get("DATABASE_POOL_MAX_SIZE", "5"))),
            migration_mode=migration_mode,
        )

    def safe_description(self) -> dict[str, Any]:
        if self.backend == "sqlite":
            return {"backend": "sqlite", "path": self.sqlite_path}
        parsed = urlparse(self.database_url or "")
        return {
            "backend": "postgres",
            "host": parsed.hostname,
            "port": parsed.port,
            "database": parsed.path.lstrip("/") or None,
            "credentials_present": bool(parsed.username or parsed.password),
        }


class PostgresConnectionPool:
    def __init__(self, settings: DatabaseSettings) -> None:
        if settings.backend != "postgres" or not settings.database_url:
            raise RuntimeError("postgres_pool_requires_database_url")
        try:
            from psycopg_pool import ConnectionPool
        except ImportError as exc:
            raise RuntimeError("postgres_pool_unavailable_install_postgres_extra") from exc
        self._pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.pool_min_size,
            max_size=settings.pool_max_size,
            open=False,
            kwargs={"autocommit": False},
        )

    def open(self) -> None:
        self._pool.open(wait=True)

    def close(self) -> None:
        self._pool.close()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        with self._pool.connection() as connection:
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise


def database_startup_status(settings: DatabaseSettings | None = None) -> dict[str, Any]:
    configured = settings or DatabaseSettings.from_env()
    if configured.backend == "sqlite":
        return {
            "backend": "sqlite",
            "state": "configured_healthy",
            "ready": True,
            "description": configured.safe_description(),
        }
    status = postgres_migration_status(configured.database_url or "")
    status["description"] = configured.safe_description()
    return status
