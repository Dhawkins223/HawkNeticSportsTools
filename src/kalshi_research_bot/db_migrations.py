"""Migration discovery plus legacy SQLite archive migration support.

The active application runtime uses PostgreSQL migrations through
``postgres_db_migrations``. SQLite routines remain solely for read-only archive
validation and compatibility fixtures during the one-time import path.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import repo_path


@dataclass(frozen=True)
class Migration:
    version: str
    path: Path
    sha256: str
    sql: str


def migration_directory(dialect: str) -> Path:
    normalized = str(dialect).strip().lower()
    if normalized not in {"sqlite", "postgres"}:
        raise ValueError(f"unsupported_migration_dialect:{normalized}")
    return repo_path("migrations", normalized)


def discover_migrations(
    dialect: str,
    *,
    directory: str | Path | None = None,
) -> list[Migration]:
    root = Path(directory) if directory else migration_directory(dialect)
    migrations: list[Migration] = []
    for path in sorted(root.glob("*.sql")):
        version = path.stem.split("_", 1)[0]
        if not version.isdigit():
            raise ValueError(f"invalid_migration_filename:{path.name}")
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            Migration(
                version=version,
                path=path,
                sha256=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
            )
        )
    if len({migration.version for migration in migrations}) != len(migrations):
        raise ValueError("duplicate_migration_version")
    return migrations


def _ensure_sqlite_version_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            sha256 TEXT NOT NULL,
            applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )


def sqlite_migration_status(
    connection: sqlite3.Connection,
    *,
    directory: str | Path | None = None,
) -> dict[str, Any]:
    _ensure_sqlite_version_table(connection)
    applied = {
        str(row[0]): str(row[1])
        for row in connection.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
    }
    pending: list[str] = []
    for migration in discover_migrations("sqlite", directory=directory):
        if migration.version not in applied:
            pending.append(migration.version)
        elif applied[migration.version] != migration.sha256:
            raise RuntimeError(f"applied_migration_hash_mismatch:{migration.version}")
    return {
        "dialect": "sqlite",
        "applied_versions": sorted(applied),
        "pending_versions": pending,
        "ready": not pending,
    }


def apply_sqlite_migrations(
    connection: sqlite3.Connection,
    *,
    directory: str | Path | None = None,
) -> dict[str, Any]:
    _ensure_sqlite_version_table(connection)
    connection.commit()
    applied = {
        str(row[0]): str(row[1])
        for row in connection.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
    }
    newly_applied: list[str] = []
    for migration in discover_migrations("sqlite", directory=directory):
        existing_hash = applied.get(migration.version)
        if existing_hash:
            if existing_hash != migration.sha256:
                raise RuntimeError(f"applied_migration_hash_mismatch:{migration.version}")
            continue
        safe_version = migration.version.replace("'", "''")
        safe_hash = migration.sha256.replace("'", "''")
        transactional_script = (
            "BEGIN IMMEDIATE;\n"
            f"{migration.sql}\n"
            "INSERT INTO schema_migrations (version, sha256) "
            f"VALUES ('{safe_version}', '{safe_hash}');\n"
            "COMMIT;"
        )
        try:
            connection.executescript(transactional_script)
        except Exception:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise
        newly_applied.append(migration.version)
        applied[migration.version] = migration.sha256
    return {
        "dialect": "sqlite",
        "newly_applied": newly_applied,
        "applied_versions": sorted(applied),
        "pending_versions": [],
        "ready": True,
    }


def _postgres_statements(sql: str) -> Iterable[str]:
    for statement in sql.split(";"):
        stripped = statement.strip()
        if stripped:
            yield stripped


def _validated_schema(schema: str) -> str:
    normalized = str(schema or "public").strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", normalized):
        raise ValueError("invalid_database_schema")
    return normalized


def _set_postgres_search_path(connection: Any, schema: str) -> None:
    normalized = _validated_schema(schema)
    connection.execute(f'SET search_path TO "{normalized}", public')


def apply_postgres_migrations(database_url: str, *, schema: str = "public") -> dict[str, Any]:
    if not database_url:
        raise RuntimeError("postgres_database_url_missing")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("postgres_driver_unavailable_install_postgres_extra") from exc
    newly_applied: list[str] = []
    with psycopg.connect(database_url) as connection:
        _set_postgres_search_path(connection, schema)
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                sha256 TEXT NOT NULL,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        applied = {
            str(row[0]): str(row[1])
            for row in connection.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
        }
        for migration in discover_migrations("postgres"):
            existing_hash = applied.get(migration.version)
            if existing_hash:
                if existing_hash != migration.sha256:
                    raise RuntimeError(f"applied_migration_hash_mismatch:{migration.version}")
                continue
            with connection.transaction():
                for statement in _postgres_statements(migration.sql):
                    connection.execute(statement)
                connection.execute(
                    "INSERT INTO schema_migrations (version, sha256) VALUES (%s, %s)",
                    (migration.version, migration.sha256),
                )
            newly_applied.append(migration.version)
            applied[migration.version] = migration.sha256
    return {
        "dialect": "postgres",
        "schema": _validated_schema(schema),
        "newly_applied": newly_applied,
        "applied_versions": sorted(applied),
        "pending_versions": [],
        "ready": True,
    }


def postgres_migration_status(
    database_url: str,
    *,
    schema: str = "public",
    connect_timeout_seconds: int = 5,
    statement_timeout_ms: int = 30000,
) -> dict[str, Any]:
    if not database_url:
        return {
            "dialect": "postgres",
            "ready": False,
            "state": "missing_required",
            "reason": "postgres_database_url_missing",
        }
    try:
        import psycopg
    except ImportError:
        return {
            "dialect": "postgres",
            "ready": False,
            "state": "configured_failed",
            "reason": "postgres_driver_unavailable_install_postgres_extra",
        }
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=max(1, int(connect_timeout_seconds)),
            options=f"-c statement_timeout={max(1000, int(statement_timeout_ms))} -c timezone=UTC",
        ) as connection:
            _set_postgres_search_path(connection, schema)
            exists = connection.execute(
                "SELECT to_regclass('public.schema_migrations') IS NOT NULL"
            ).fetchone()[0]
            if not exists:
                return {
                    "dialect": "postgres",
                    "ready": False,
                    "state": "configured_degraded",
                    "reason": "schema_migrations_table_missing",
                    "pending_versions": [migration.version for migration in discover_migrations("postgres")],
                }
            applied = {
                str(row[0]): str(row[1])
                for row in connection.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
            }
    except Exception as exc:
        return {
            "dialect": "postgres",
            "schema": _validated_schema(schema),
            "ready": False,
            "state": "configured_failed",
            "reason": f"database_connection_failed:{type(exc).__name__}",
        }
    pending = []
    for migration in discover_migrations("postgres"):
        if migration.version not in applied:
            pending.append(migration.version)
        elif applied[migration.version] != migration.sha256:
            return {
                "dialect": "postgres",
                "ready": False,
                "state": "configured_failed",
                "reason": f"applied_migration_hash_mismatch:{migration.version}",
            }
    return {
        "dialect": "postgres",
        "schema": _validated_schema(schema),
        "ready": not pending,
        "state": "configured_healthy" if not pending else "configured_degraded",
        "pending_versions": pending,
        "applied_versions": sorted(applied),
    }
