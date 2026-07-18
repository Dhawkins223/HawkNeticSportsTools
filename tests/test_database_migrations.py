from __future__ import annotations

import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from kalshi_research_bot.db_migrations import _statements, apply_postgres_migrations, discover_migrations, postgres_migration_status
from kalshi_research_bot.postgres_import import ImportConflictError, canonical_row_hash, import_canonical_rows

from tests.postgres_support import PostgresTestCase


class DatabaseMigrationTests(PostgresTestCase):
    def test_migrations_are_versioned_and_second_apply_is_safe(self) -> None:
        versions = [migration.version for migration in discover_migrations()]
        self.assertEqual(versions, sorted(versions))
        self.assertTrue(versions)
        first = apply_postgres_migrations(self.settings.require_url())
        second = apply_postgres_migrations(self.settings.require_url())
        status = postgres_migration_status(self.settings.require_url())
        self.assertTrue(first["ready"])
        self.assertEqual(second["newly_applied"], [])
        self.assertTrue(status["ready"])
        self.assertEqual(status["required_schemas"], ["app", "raw", "core", "research", "ops", "reporting", "auth"])
        self.assertIn("reporting.latest_market_state", status["required_relations"])

    def test_missing_database_url_fails_closed(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "postgres_database_url_required"):
            apply_postgres_migrations("")
        status = postgres_migration_status("")
        self.assertFalse(status["ready"])

    def test_canonical_import_detects_content_conflicts_not_only_counts(self) -> None:
        row = {
            "username": "migration-user",
            "password_hash": "hash",
            "password_salt": "salt",
            "password_algorithm": "scrypt",
            "role": "read_only",
            "is_disabled": False,
            "failed_login_count": 0,
            "created_at": "2026-07-18T00:00:00+00:00",
            "updated_at": "2026-07-18T00:00:00+00:00",
        }
        self.assertEqual(canonical_row_hash(row), canonical_row_hash(dict(row)))
        self.assertEqual(
            canonical_row_hash({"value": Decimal("1.0")}),
            canonical_row_hash({"value": Decimal("1.000000000000")}),
        )
        with self.store().connect() as connection:
            first = import_canonical_rows(connection, table="auth.app_users", key_columns=("username",), rows=[row])
            repeated = import_canonical_rows(connection, table="auth.app_users", key_columns=("username",), rows=[row])
            self.assertEqual(first.inserted, 1)
            self.assertEqual(repeated.identical_duplicates, 1)
            with self.assertRaises(ImportConflictError):
                import_canonical_rows(connection, table="auth.app_users", key_columns=("username",), rows=[{**row, "role": "admin"}])

    def test_canonical_import_preserves_falsey_jsonb_values(self) -> None:
        rows = [
            {
                "source": "neutral-import",
                "kind": "jsonb",
                "url": f"https://example.test/falsey/{index}",
                "title": f"falsey-{index}",
                "text": "body",
                "metadata_json": value,
            }
            for index, value in enumerate((None, False, True, 0, 0.0, "", [], [0], {}, {"value": False}))
        ]
        with self.store().connect() as connection:
            result = import_canonical_rows(
                connection,
                table="app.source_records",
                key_columns=("url",),
                rows=rows,
                json_columns=("metadata_json",),
            )
            actual = connection.execute(
                "SELECT metadata_json FROM app.source_records WHERE source = %s ORDER BY id",
                ("neutral-import",),
            ).fetchall()
        self.assertEqual(result.inserted, len(rows))
        self.assertEqual([row["metadata_json"] for row in actual], [row["metadata_json"] for row in rows])
        self.assertEqual(
            [type(row["metadata_json"]) for row in actual],
            [type(row["metadata_json"]) for row in rows],
        )

    def test_canonical_import_uses_one_transaction_lock_per_table(self) -> None:
        rows = [
            {
                "source": "neutral-import",
                "kind": "lock-check",
                "url": f"https://example.test/locks/{index}",
                "title": f"lock-{index}",
                "text": "body",
                "metadata_json": {},
            }
            for index in range(32)
        ]
        with self.store().connect() as connection:
            result = import_canonical_rows(
                connection,
                table="app.source_records",
                key_columns=("url",),
                rows=rows,
                json_columns=("metadata_json",),
            )
            advisory_locks = connection.execute(
                "SELECT COUNT(*) AS count FROM pg_locks "
                "WHERE locktype = 'advisory' AND pid = pg_backend_pid()"
            ).fetchone()["count"]
        self.assertEqual(result.inserted, len(rows))
        self.assertEqual(advisory_locks, 1)

    def test_canonical_import_can_preserve_generated_identity_values(self) -> None:
        row = {
            "id": 42,
            "worker_name": "legacy-worker",
            "worker_version": "legacy-local",
            "deployment_identifier": "legacy-local",
            "run_id": "legacy-run",
            "idempotency_key": "legacy-worker-run",
            "started_at": datetime(2026, 7, 18, tzinfo=timezone.utc),
            "heartbeat_at": datetime(2026, 7, 18, tzinfo=timezone.utc),
            "completed_at": datetime(2026, 7, 18, tzinfo=timezone.utc),
            "status": "completed",
            "records_read": 0,
            "records_written": 7,
            "records_rejected": 0,
            "records_duplicated": 0,
            "error_code": None,
            "error_detail": None,
            "created_at": datetime(2026, 7, 18, tzinfo=timezone.utc),
            "details_json": {"source": "legacy"},
        }
        with self.store().connect() as connection:
            result = import_canonical_rows(
                connection,
                table="ops.worker_runs",
                key_columns=("id",),
                rows=[row],
                json_columns=("details_json",),
                override_system_identity=True,
            )
            actual = connection.execute(
                "SELECT id, records_written, details_json FROM ops.worker_runs WHERE id = %s",
                (42,),
            ).fetchone()
        self.assertEqual(result.inserted, 1)
        self.assertEqual(dict(actual), {"id": 42, "records_written": 7, "details_json": {"source": "legacy"}})

    def test_import_rejects_noncanonical_table_identifier(self) -> None:
        with self.store().connect() as connection:
            with self.assertRaises(ValueError):
                import_canonical_rows(connection, table="auth.app_users;drop", key_columns=("username",), rows=[])

    def test_database_layer_rejects_non_native_parameter_placeholders(self) -> None:
        with self.store().connect() as connection:
            with self.assertRaisesRegex(RuntimeError, "postgres_parameter_style_required"):
                connection.execute("SELECT ?", (1,))

    def test_migration_statement_parser_ignores_semicolons_in_comments(self) -> None:
        script = "-- first; comment\nCREATE TABLE app.example (id INTEGER); /* second; comment */ INSERT INTO app.example VALUES (1);"
        self.assertEqual(
            list(_statements(script)),
            ["CREATE TABLE app.example (id INTEGER)", "INSERT INTO app.example VALUES (1)"],
        )
