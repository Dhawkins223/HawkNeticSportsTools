from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from .config import repo_path


@dataclass(frozen=True)
class PostgresMigration:
    version: str
    path: Path
    sha256: str
    sql: str


def postgres_migration_directory() -> Path:
    return repo_path("migrations", "postgres")


def discover_postgres_migrations(*, directory: str | Path | None = None) -> list[PostgresMigration]:
    root = Path(directory) if directory else postgres_migration_directory()
    migrations: list[PostgresMigration] = []
    for path in sorted(root.glob("*.sql")):
        version = path.stem.split("_", 1)[0]
        if not version.isdigit():
            raise ValueError(f"invalid_migration_filename:{path.name}")
        sql = path.read_text(encoding="utf-8")
        migrations.append(
            PostgresMigration(
                version=version,
                path=path,
                sha256=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
                sql=sql,
            )
        )
    if len({migration.version for migration in migrations}) != len(migrations):
        raise ValueError("duplicate_migration_version")
    return migrations


def _validated_schema(schema: str) -> str:
    normalized = str(schema or "public").strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", normalized):
        raise ValueError("invalid_database_schema")
    return normalized


def _set_postgres_search_path(connection: Any, schema: str) -> None:
    normalized = _validated_schema(schema)
    connection.execute(f'SET search_path TO "{normalized}", public')


def _postgres_statements(sql: str) -> Iterable[str]:
    for statement in sql.split(";"):
        stripped = statement.strip()
        if stripped:
            yield stripped


def apply_postgres_migrations(database_url: str, *, schema: str = "public") -> dict[str, Any]:
    if not database_url:
        raise RuntimeError("postgres_database_url_missing")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("postgres_driver_unavailable_install_postgres_extra") from exc
    normalized_schema = _validated_schema(schema)
    newly_applied: list[str] = []
    with psycopg.connect(database_url) as connection:
        connection.execute(f'CREATE SCHEMA IF NOT EXISTS "{normalized_schema}"')
        _set_postgres_search_path(connection, normalized_schema)
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
        for migration in discover_postgres_migrations():
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
        "schema": normalized_schema,
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
    normalized_schema = _validated_schema(schema)
    if not database_url:
        return {
            "dialect": "postgres",
            "schema": normalized_schema,
            "ready": False,
            "state": "missing_required",
            "reason": "postgres_database_url_missing",
        }
    try:
        import psycopg
    except ImportError:
        return {
            "dialect": "postgres",
            "schema": normalized_schema,
            "ready": False,
            "state": "configured_failed",
            "reason": "postgres_driver_unavailable_install_postgres_extra",
        }
    try:
        with psycopg.connect(
            database_url,
            connect_timeout=max(1, int(connect_timeout_seconds)),
            options=f"-c statement_timeout={max(1000, int(statement_timeout_ms))} -c timezone=UTC -c search_path={normalized_schema},public",
        ) as connection:
            _set_postgres_search_path(connection, normalized_schema)
            exists = connection.execute(
                "SELECT to_regclass('schema_migrations') IS NOT NULL"
            ).fetchone()[0]
            if not exists:
                return {
                    "dialect": "postgres",
                    "schema": normalized_schema,
                    "ready": False,
                    "state": "configured_degraded",
                    "reason": "schema_migrations_table_missing",
                    "pending_versions": [migration.version for migration in discover_postgres_migrations()],
                }
            applied = {
                str(row[0]): str(row[1])
                for row in connection.execute("SELECT version, sha256 FROM schema_migrations").fetchall()
            }
    except Exception as exc:
        return {
            "dialect": "postgres",
            "schema": normalized_schema,
            "ready": False,
            "state": "configured_failed",
            "reason": f"database_connection_failed:{type(exc).__name__}",
        }
    pending = []
    for migration in discover_postgres_migrations():
        if migration.version not in applied:
            pending.append(migration.version)
        elif applied[migration.version] != migration.sha256:
            return {
                "dialect": "postgres",
                "schema": normalized_schema,
                "ready": False,
                "state": "configured_failed",
                "reason": f"applied_migration_hash_mismatch:{migration.version}",
            }
    return {
        "dialect": "postgres",
        "schema": normalized_schema,
        "ready": not pending,
        "state": "configured_healthy" if not pending else "configured_degraded",
        "pending_versions": pending,
        "applied_versions": sorted(applied),
    }
