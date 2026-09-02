from __future__ import annotations

import os
import unittest
from typing import Any

from kalshi_research_bot.business_store import clear_database_readiness_cache, create_store
from kalshi_research_bot.database import DatabaseSettings, close_connection_pools, connection_pool
from kalshi_research_bot.db_migrations import apply_postgres_migrations


def test_database_url() -> str:
    """Resolve the database every test reads, writes, and truncates.

    ``TEST_DATABASE_URL`` wins so a developer never points a test run at the
    development database by accident.
    """

    url = os.environ.get("TEST_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("test_postgres_url_required")
    return url


def bind_test_database_environment() -> str:
    """Point the whole process at the test database before anything opens a pool.

    The code under test builds its own settings from ``DATABASE_URL``, while the
    harness truncates whatever ``test_settings()`` resolves. In the two-database
    layout ``.env.example`` ships those are different databases: the harness then
    truncates one database while the code writes to another, so rows survive
    ``setUp`` and accumulate into later assertions — and the writes land in the
    developer's development database. Binding both names to the test URL keeps
    the reset and the code under test on the same database.
    """

    url = test_database_url()
    os.environ["DATABASE_URL"] = url
    os.environ["TEST_DATABASE_URL"] = url
    os.environ.setdefault("DATABASE_MIGRATION_MODE", "apply")
    os.environ["APP_ENV"] = "test"
    return url


def test_settings() -> DatabaseSettings:
    url = bind_test_database_environment()
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
        cls.settings = test_settings()
        apply_postgres_migrations(cls.settings.require_url())

    def setUp(self) -> None:
        close_connection_pools()
        clear_database_readiness_cache()
        reset_database(self.settings)

    def tearDown(self) -> None:
        close_connection_pools()
        clear_database_readiness_cache()

    def store(self, namespace: str | None = None):
        return create_store(namespace, settings=self.settings)

    def query_one(self, statement: str, parameters: tuple[Any, ...] = ()):
        with connection_pool(self.settings).connection() as connection:
            return connection.execute(statement, parameters).fetchone()

    def query_all(self, statement: str, parameters: tuple[Any, ...] = ()):
        with connection_pool(self.settings).connection() as connection:
            return connection.execute(statement, parameters).fetchall()
