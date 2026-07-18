from __future__ import annotations

import atexit
import os
import re
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator
from urllib.parse import urlparse

from .postgres_db_migrations import postgres_migration_status


@dataclass(frozen=True)
class DatabaseSettings:
    backend: str
    database_url: str
    schema: str
    pool_min_size: int
    pool_max_size: int
    migration_mode: str
    connect_timeout_seconds: int = 5
    statement_timeout_ms: int = 30000

    @classmethod
    def from_env(cls) -> "DatabaseSettings":
        database_url = str(os.environ.get("DATABASE_URL") or "").strip()
        configured_backend = str(os.environ.get("DATABASE_BACKEND") or "postgres").strip().lower()
        if configured_backend != "postgres":
            raise RuntimeError("postgres_runtime_only")
        if not database_url:
            raise RuntimeError("postgres_runtime_requires_database_url")
        schema = str(os.environ.get("DATABASE_SCHEMA") or "public").strip()
        if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", schema):
            raise ValueError("invalid_database_schema")
        migration_mode = str(os.environ.get("DATABASE_MIGRATION_MODE") or "check").strip().lower()
        if migration_mode not in {"check", "apply"}:
            raise ValueError("database_migration_mode_must_be_check_or_apply")
        return cls(
            backend="postgres",
            database_url=database_url,
            schema=schema,
            pool_min_size=max(1, int(os.environ.get("DATABASE_POOL_MIN_SIZE", "1"))),
            pool_max_size=max(1, int(os.environ.get("DATABASE_POOL_MAX_SIZE", "5"))),
            migration_mode=migration_mode,
            connect_timeout_seconds=max(1, int(os.environ.get("DATABASE_CONNECT_TIMEOUT", "5"))),
            statement_timeout_ms=max(1000, int(os.environ.get("DATABASE_STATEMENT_TIMEOUT", "30000"))),
        )

    def safe_description(self) -> dict[str, Any]:
        parsed = urlparse(self.database_url)
        return {
            "backend": "postgres",
            "host": parsed.hostname,
            "port": parsed.port,
            "database": parsed.path.lstrip("/") or None,
            "schema": self.schema,
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
            kwargs={
                "autocommit": False,
                "connect_timeout": settings.connect_timeout_seconds,
                "options": (
                    f"-c statement_timeout={settings.statement_timeout_ms} "
                    f"-c timezone=UTC -c search_path={settings.schema},public"
                ),
            },
        )

    def open(self) -> None:
        self._pool.open(wait=True)

    def close(self) -> None:
        self._pool.close()

    def acquire(self) -> Any:
        self.open()
        return self._pool.getconn()

    def release(self, connection: Any) -> None:
        self._pool.putconn(connection)

    @contextmanager
    def connection(self) -> Iterator[Any]:
        connection = self.acquire()
        try:
            try:
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        finally:
            self.release(connection)


_POOL_REGISTRY: dict[DatabaseSettings, PostgresConnectionPool] = {}
_POOL_REGISTRY_LOCK = threading.Lock()


def postgres_connection_pool(settings: DatabaseSettings) -> PostgresConnectionPool:
    """Return the process-local PostgreSQL pool for one runtime configuration."""

    with _POOL_REGISTRY_LOCK:
        pool = _POOL_REGISTRY.get(settings)
        if pool is None:
            pool = PostgresConnectionPool(settings)
            _POOL_REGISTRY[settings] = pool
        return pool


def close_postgres_connection_pools() -> None:
    """Close process-local pools during an explicit application shutdown."""

    with _POOL_REGISTRY_LOCK:
        pools = list(_POOL_REGISTRY.values())
        _POOL_REGISTRY.clear()
    for pool in pools:
        pool.close()


atexit.register(close_postgres_connection_pools)


def database_startup_status(settings: DatabaseSettings | None = None) -> dict[str, Any]:
    try:
        configured = settings or DatabaseSettings.from_env()
    except RuntimeError as exc:
        reason = str(exc)
        if reason == "postgres_runtime_requires_database_url":
            reason = "postgres_database_url_missing"
        return {
            "dialect": "postgres",
            "ready": False,
            "state": "missing_required",
            "reason": reason,
        }
    status = postgres_migration_status(
        configured.database_url,
        schema=configured.schema,
        connect_timeout_seconds=configured.connect_timeout_seconds,
        statement_timeout_ms=configured.statement_timeout_ms,
    )
    status["description"] = configured.safe_description()
    return status


def production_safety_status() -> dict[str, Any]:
    hosted = bool(
        os.environ.get("RAILWAY_ENVIRONMENT")
        or os.environ.get("RAILWAY_PROJECT_ID")
        or str(os.environ.get("APP_ENV") or "").lower() in {"staging", "production"}
    )
    required = {
        "RESEARCH_ONLY": True,
        "LIVE_EXECUTION_ENABLED": False,
        "AUTO_UPLOAD_ENABLED": False,
        "AUTO_TRADE_ENABLED": False,
        "KALSHI_ORDER_UPLOAD_ENABLED": False,
        "MODEL_PROMOTION_ENABLED": False,
        "STALE_CACHE_AS_FRESH": False,
    }
    violations = []
    for name, expected in required.items():
        actual = _env_bool(name, expected if not hosted else not expected)
        if actual is not expected:
            violations.append(f"unsafe_flag:{name}")
    if hosted and not _env_bool("DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED", True):
        violations.append("hosted_auth_not_required")
    return {
        "hosted": hosted,
        "ready": not violations,
        "state": "configured_healthy" if not violations else "configured_failed",
        "violations": violations,
    }


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}
