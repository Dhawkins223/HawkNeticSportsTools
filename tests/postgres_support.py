from __future__ import annotations

import os
import unittest
from typing import Any

from kalshi_research_bot.business_store import create_store
from kalshi_research_bot.database import DatabaseSettings, close_connection_pools, connection_pool
from kalshi_research_bot.db_migrations import apply_postgres_migrations


def test_settings() -> DatabaseSettings:
    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("test_postgres_url_required")
    return DatabaseSettings(
        database_url=url,
        pool_min_size=1,
        pool_max_size=4,
        migration_mode="apply",
        connect_timeout_seconds=5,
        statement_timeout_ms=30000,
    )


def reset_database(settings: DatabaseSettings | None = None) -> None:
    configured = settings or test_settings()
    apply_postgres_migrations(configured.require_url())
    with connection_pool(configured).connection() as connection:
        tables = connection.execute(
            """
            SELECT quote_ident(table_schema) || '.' || quote_ident(table_name) AS qualified_name
            FROM information_schema.tables
            WHERE table_type = 'BASE TABLE'
              AND table_schema IN ('app', 'raw', 'core', 'research', 'ops', 'auth')
              AND NOT (table_schema = 'ops' AND table_name = 'schema_migrations')
            ORDER BY table_schema, table_name
            """
        ).fetchall()
        if tables:
            names = ', '.join(str(row['qualified_name']) for row in tables)
            connection.execute(f"TRUNCATE TABLE {names} RESTART IDENTITY CASCADE")


class PostgresTestCase(unittest.TestCase):
    settings: DatabaseSettings

    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("DATABASE_BACKEND", "postgres")
        os.environ.setdefault("DATABASE_MIGRATION_MODE", "apply")
        os.environ["APP_ENV"] = "test"
        cls.settings = test_settings()
        apply_postgres_migrations(cls.settings.require_url())

    def setUp(self) -> None:
        close_connection_pools()
        reset_database(self.settings)

    def tearDown(self) -> None:
        close_connection_pools()

    def store(self, namespace: str | None = None):
        return create_store(namespace, settings=self.settings)

    def query_one(self, statement: str, parameters: tuple[Any, ...] = ()):
        with connection_pool(self.settings).connection() as connection:
            return connection.execute(statement, parameters).fetchone()

    def query_all(self, statement: str, parameters: tuple[Any, ...] = ()):
        with connection_pool(self.settings).connection() as connection:
            return connection.execute(statement, parameters).fetchall()
