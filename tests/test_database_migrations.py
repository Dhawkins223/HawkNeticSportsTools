import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from kalshi_research_bot.database import DatabaseSettings, database_startup_status
from kalshi_research_bot.db_migrations import (
    apply_sqlite_migrations,
    discover_migrations,
    sqlite_migration_status,
)
from kalshi_research_bot.postgres_migration import (
    _critical_aggregates_match,
    _ordered_manifest_tables,
    _sqlite_critical_aggregates,
    export_sqlite_for_postgres,
    import_sqlite_export_to_postgres,
    validate_sqlite_export,
)
from kalshi_research_bot.storage import ResearchStore


class DatabaseMigrationTests(unittest.TestCase):
    def test_research_store_applies_versioned_additive_migration_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "research.sqlite"
            store = ResearchStore(path)
            store.initialize()
            store.initialize()
            connection = sqlite3.connect(path)
            try:
                versions = connection.execute("SELECT version FROM schema_migrations").fetchall()
                tables = {
                    row[0]
                    for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
                }
                status = sqlite_migration_status(connection)
            finally:
                connection.close()
        self.assertEqual(versions, [("0001",), ("0002",), ("0003",), ("0004",)])
        self.assertIn("model_evaluations", tables)
        self.assertIn("simulated_executions", tables)
        self.assertIn("worker_status", tables)
        self.assertIn("operator_messages", tables)
        self.assertIn("ingestion_batches", tables)
        self.assertIn("raw_source_payloads", tables)
        self.assertIn("collection_checkpoints", tables)
        self.assertTrue(status["ready"])

    def test_modified_applied_migration_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            migration = root / "0001_test.sql"
            migration.write_text("CREATE TABLE sample (id INTEGER PRIMARY KEY);", encoding="utf-8")
            connection = sqlite3.connect(root / "db.sqlite")
            try:
                apply_sqlite_migrations(connection, directory=root)
                migration.write_text("CREATE TABLE changed (id INTEGER PRIMARY KEY);", encoding="utf-8")
                with self.assertRaisesRegex(RuntimeError, "applied_migration_hash_mismatch"):
                    apply_sqlite_migrations(connection, directory=root)
            finally:
                connection.close()

    def test_sqlite_export_validates_counts_hashes_and_aggregates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            database = root / "source.sqlite"
            store = ResearchStore(database)
            store.insert_prediction_logs(
                [
                    {
                        "run_id": "run-1",
                        "timestamp": "2026-07-12T12:00:00Z",
                        "event": "Fixture",
                        "event_id": "event-1",
                        "market": "market-1",
                        "market_id": "market-1",
                        "side": "yes",
                        "strategy": "baseline",
                        "model_version": "market-v1",
                        "confidence_score": 0.6,
                        "confidence_label": "baseline",
                        "predicted_outcome": "yes",
                        "event_start_time": "2026-07-12T14:00:00Z",
                        "market_close_time": "2026-07-12T14:00:00Z",
                        "entry_price_cents": 60,
                        "implied_probability": 0.6,
                    }
                ]
            )
            export = root / "export"
            manifest = export_sqlite_for_postgres(database, export)
            validation = validate_sqlite_export(database, export)
            self.assertTrue(validation["valid"])
            self.assertEqual(manifest["tables"]["prediction_logs"]["row_count"], 1)
            self.assertIn("app_users", manifest["excluded_sensitive_tables"])
            self.assertIn("operator_messages", manifest["excluded_sensitive_tables"])
            self.assertTrue(manifest["export_id"].startswith("sha256:"))

            connection = sqlite3.connect(database)
            try:
                connection.execute("UPDATE prediction_logs SET event = 'Changed'")
                connection.commit()
            finally:
                connection.close()
            changed = validate_sqlite_export(database, export)
            self.assertFalse(changed["valid"])
            self.assertIn("digest_mismatch:prediction_logs", changed["errors"])

    def test_postgres_schema_has_constraints_and_query_indexes(self):
        migrations = discover_migrations("postgres")
        sql = "\n".join(migration.sql for migration in migrations)
        self.assertIn("CREATE TABLE IF NOT EXISTS prediction_logs", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS migration_imports", sql)
        self.assertIn("idx_prediction_logs_settlement", sql)
        self.assertIn("idx_crypto_prediction_time", sql)
        self.assertIn("idx_sports_prediction_time", sql)
        self.assertIn("UNIQUE (portfolio_run_id, prediction_id)", sql)
        self.assertIn("execution_allowed BOOLEAN NOT NULL DEFAULT FALSE", sql)
        self.assertIn("CREATE SCHEMA IF NOT EXISTS raw", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS core.market_observations", sql)
        self.assertIn("NUMERIC(12, 8)", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS research.prediction_outcomes", sql)
        self.assertIn("CREATE OR REPLACE VIEW reporting.prediction_evaluation", sql)

    def test_postgres_import_requires_configuration_and_never_guesses(self):
        with self.assertRaisesRegex(RuntimeError, "postgres_database_url_missing"):
            import_sqlite_export_to_postgres("missing", database_url="")

    def test_postgres_import_uses_dependency_safe_manifest_order(self):
        manifest = {
            "tables": {
                "model_evaluation_predictions": {},
                "prediction_logs": {},
                "model_evaluations": {},
            }
        }
        self.assertEqual(
            _ordered_manifest_tables(manifest),
            ["prediction_logs", "model_evaluations", "model_evaluation_predictions"],
        )
        with self.assertRaisesRegex(ValueError, "unsupported_export_tables:unknown_table"):
            _ordered_manifest_tables({"tables": {"unknown_table": {}}})

    def test_postgres_aggregate_comparison_uses_documented_float_tolerance(self):
        expected = {"crypto_prediction_logs": [3204, 3176, -1642.948057]}
        actual = {"crypto_prediction_logs": [3204, 3176, -1642.9480569999994]}
        matches, differences = _critical_aggregates_match(expected, actual)
        self.assertTrue(matches)
        self.assertEqual(differences, [])

        matches, differences = _critical_aggregates_match(
            expected,
            {"crypto_prediction_logs": [3204, 3175, -1642.9480569999994]},
        )
        self.assertFalse(matches)
        self.assertEqual(differences[0]["field"], "crypto_prediction_logs[1]")

    def test_export_aggregates_use_actual_crypto_and_sports_settlement_states(self):
        connection = sqlite3.connect(":memory:")
        try:
            connection.execute("CREATE TABLE crypto_prediction_logs (settlement_state TEXT, return_bps REAL)")
            connection.executemany(
                "INSERT INTO crypto_prediction_logs VALUES (?, ?)",
                [("settled", 5.0), ("push", 0.0), ("unresolved", None)],
            )
            connection.execute("CREATE TABLE sports_prediction_logs (settlement_state TEXT)")
            connection.executemany(
                "INSERT INTO sports_prediction_logs VALUES (?)",
                [("settled",), ("push",), ("void",), ("unresolved",)],
            )
            aggregates = _sqlite_critical_aggregates(connection)
        finally:
            connection.close()
        self.assertEqual(aggregates["crypto_prediction_logs"], [3, 2, 5.0])
        self.assertEqual(aggregates["sports_prediction_logs"], [4, 3])

    def test_database_description_redacts_credentials(self):
        settings = DatabaseSettings(
            backend="postgres",
            sqlite_path="unused.sqlite",
            database_url="postgresql://private_user:private_password@example.com:5432/research",
            pool_min_size=1,
            pool_max_size=5,
            migration_mode="check",
        )
        rendered = json.dumps(settings.safe_description())
        self.assertNotIn("private_user", rendered)
        self.assertNotIn("private_password", rendered)
        self.assertIn("example.com", rendered)

    def test_unconfigured_postgres_status_is_explicit(self):
        with patch.dict(os.environ, {"DATABASE_BACKEND": "postgres"}, clear=True):
            status = database_startup_status()
        self.assertFalse(status["ready"])
        self.assertEqual(status["state"], "missing_required")
        self.assertEqual(status["reason"], "postgres_database_url_missing")

    def test_production_safety_flags_fail_closed_when_hosted(self):
        from kalshi_research_bot.database import production_safety_status

        with patch.dict(
            os.environ,
            {
                "APP_ENV": "production",
                "RESEARCH_ONLY": "false",
                "LIVE_EXECUTION_ENABLED": "true",
                "AUTO_UPLOAD_ENABLED": "true",
                "AUTO_TRADE_ENABLED": "true",
                "KALSHI_ORDER_UPLOAD_ENABLED": "true",
                "MODEL_PROMOTION_ENABLED": "true",
                "STALE_CACHE_AS_FRESH": "true",
            },
            clear=True,
        ):
            status = production_safety_status()
        self.assertFalse(status["ready"])
        self.assertGreaterEqual(len(status["violations"]), 7)


if __name__ == "__main__":
    unittest.main()
