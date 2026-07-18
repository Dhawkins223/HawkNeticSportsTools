from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from .db_migrations import apply_postgres_migrations


EXPORT_TABLES = (
    "source_records",
    "edge_results",
    "prediction_logs",
    "paper_test_runs",
    "prediction_rejections",
    "settlement_audit",
    "crypto_prediction_logs",
    "crypto_prediction_rejections",
    "sports_prediction_logs",
    "sports_prediction_rejections",
    "model_evaluations",
    "model_evaluation_predictions",
    "simulated_executions",
    "exposure_decisions",
    "worker_status",
    "worker_runs",
    "connector_health",
)

BOOLEAN_COLUMNS = {
    ("prediction_logs", "actual_outcome"),
    ("settlement_audit", "previous_actual_outcome"),
    ("settlement_audit", "new_actual_outcome"),
    ("model_evaluation_predictions", "actual_outcome"),
    ("exposure_decisions", "accepted"),
}

CRITICAL_AGGREGATE_TOLERANCE = 1e-9


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone() is not None


def _safe_identifier(value: str) -> str:
    if not re.fullmatch(r"[a-z_][a-z0-9_]*", value):
        raise ValueError(f"unsafe_identifier:{value}")
    return value


def _canonical_line(row: Mapping[str, Any]) -> str:
    return json.dumps(dict(row), sort_keys=True, separators=(",", ":"), default=str)


def _table_digest(rows: Iterable[Mapping[str, Any]]) -> tuple[str, int, list[str]]:
    digest = hashlib.sha256()
    count = 0
    lines = []
    for row in rows:
        line = _canonical_line(row)
        digest.update(line.encode("utf-8"))
        digest.update(b"\n")
        lines.append(line)
        count += 1
    return digest.hexdigest(), count, lines


def _sqlite_critical_aggregates(connection: sqlite3.Connection) -> dict[str, Any]:
    aggregates: dict[str, Any] = {}
    if _table_exists(connection, "prediction_logs"):
        row = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN settlement_state = 'win' THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN settlement_state = 'loss' THEN 1 ELSE 0 END) AS losses,
                   COALESCE(SUM(profit_loss_cents), 0.0) AS profit_loss_cents
            FROM prediction_logs
            """
        ).fetchone()
        aggregates["prediction_logs"] = list(row)
    if _table_exists(connection, "crypto_prediction_logs"):
        row = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN settlement_state IN ('settled', 'push') THEN 1 ELSE 0 END) AS settled,
                   COALESCE(SUM(return_bps), 0.0) AS return_bps
            FROM crypto_prediction_logs
            """
        ).fetchone()
        aggregates["crypto_prediction_logs"] = list(row)
    if _table_exists(connection, "sports_prediction_logs"):
        row = connection.execute(
            """
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN settlement_state IN ('settled', 'push', 'void') THEN 1 ELSE 0 END) AS settled
            FROM sports_prediction_logs
            """
        ).fetchone()
        aggregates["sports_prediction_logs"] = list(row)
    return aggregates


def export_sqlite_for_postgres(
    sqlite_path: str | Path,
    output_directory: str | Path,
) -> dict[str, Any]:
    source = Path(sqlite_path)
    output = Path(output_directory)
    output.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(source)
    connection.row_factory = sqlite3.Row
    tables: dict[str, Any] = {}
    try:
        for table in EXPORT_TABLES:
            _safe_identifier(table)
            if not _table_exists(connection, table):
                continue
            rows = [dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY ROWID')]
            digest, count, lines = _table_digest(rows)
            path = output / f"{table}.jsonl"
            path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
            tables[table] = {
                "file": path.name,
                "row_count": count,
                "sha256": digest,
            }
        critical_aggregates = _sqlite_critical_aggregates(connection)
    finally:
        connection.close()
    export_identity = json.dumps(
        {table: {"row_count": value["row_count"], "sha256": value["sha256"]} for table, value in tables.items()},
        sort_keys=True,
        separators=(",", ":"),
    )
    manifest = {
        "format_version": 1,
        "source_backend": "sqlite",
        "target_backend": "postgres",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source_path_name": source.name,
        "export_id": f"sha256:{hashlib.sha256(export_identity.encode('utf-8')).hexdigest()}",
        "tables": tables,
        "critical_aggregates": critical_aggregates,
        "excluded_sensitive_tables": [
            "app_users",
            "app_sessions",
            "login_audit",
            "operator_messages",
        ],
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _read_manifest(directory: str | Path) -> tuple[Path, dict[str, Any]]:
    root = Path(directory)
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format_version") != 1:
        raise ValueError("unsupported_export_manifest_version")
    return root, manifest


def _ordered_manifest_tables(manifest: Mapping[str, Any]) -> list[str]:
    tables = manifest.get("tables")
    if not isinstance(tables, Mapping):
        raise ValueError("invalid_export_manifest_tables")
    unsupported = sorted(set(tables) - set(EXPORT_TABLES))
    if unsupported:
        raise ValueError(f"unsupported_export_tables:{','.join(unsupported)}")
    return [table for table in EXPORT_TABLES if table in tables]


def validate_sqlite_export(
    sqlite_path: str | Path,
    export_directory: str | Path,
) -> dict[str, Any]:
    root, manifest = _read_manifest(export_directory)
    connection = sqlite3.connect(sqlite_path)
    connection.row_factory = sqlite3.Row
    errors: list[str] = []
    try:
        for table, expected in manifest["tables"].items():
            _safe_identifier(table)
            if not _table_exists(connection, table):
                errors.append(f"source_table_missing:{table}")
                continue
            source_rows = [dict(row) for row in connection.execute(f'SELECT * FROM "{table}" ORDER BY ROWID')]
            source_digest, source_count, _ = _table_digest(source_rows)
            export_lines = [
                json.loads(line)
                for line in (root / expected["file"]).read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            export_digest, export_count, _ = _table_digest(export_lines)
            if source_count != expected["row_count"] or export_count != expected["row_count"]:
                errors.append(f"row_count_mismatch:{table}")
            if source_digest != expected["sha256"] or export_digest != expected["sha256"]:
                errors.append(f"digest_mismatch:{table}")
        if _sqlite_critical_aggregates(connection) != manifest.get("critical_aggregates"):
            errors.append("critical_aggregate_mismatch")
    finally:
        connection.close()
    return {
        "valid": not errors,
        "errors": errors,
        "export_id": manifest["export_id"],
        "table_count": len(manifest["tables"]),
    }


def _postgres_critical_aggregates(connection: Any) -> dict[str, Any]:
    aggregates: dict[str, Any] = {}
    row = connection.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN settlement_state = 'win' THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN settlement_state = 'loss' THEN 1 ELSE 0 END) AS losses,
               COALESCE(SUM(profit_loss_cents), 0.0) AS profit_loss_cents
        FROM prediction_logs
        """
    ).fetchone()
    aggregates["prediction_logs"] = [int(row[0]), int(row[1] or 0), int(row[2] or 0), float(row[3] or 0.0)]
    row = connection.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN settlement_state IN ('settled', 'push') THEN 1 ELSE 0 END) AS settled,
               COALESCE(SUM(return_bps), 0.0) AS return_bps
        FROM crypto_prediction_logs
        """
    ).fetchone()
    aggregates["crypto_prediction_logs"] = [int(row[0]), int(row[1] or 0), float(row[2] or 0.0)]
    row = connection.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN settlement_state IN ('settled', 'push', 'void') THEN 1 ELSE 0 END) AS settled
        FROM sports_prediction_logs
        """
    ).fetchone()
    aggregates["sports_prediction_logs"] = [int(row[0]), int(row[1] or 0)]
    return aggregates


def _critical_aggregates_match(
    expected: Mapping[str, Any],
    actual: Mapping[str, Any],
    *,
    tolerance: float = CRITICAL_AGGREGATE_TOLERANCE,
) -> tuple[bool, list[dict[str, Any]]]:
    differences: list[dict[str, Any]] = []
    if set(expected) != set(actual):
        differences.append(
            {
                "field": "aggregate_keys",
                "expected": sorted(expected),
                "actual": sorted(actual),
            }
        )
        return False, differences
    for aggregate_name in sorted(expected):
        expected_values = expected[aggregate_name]
        actual_values = actual[aggregate_name]
        if not isinstance(expected_values, list) or not isinstance(actual_values, list):
            if expected_values != actual_values:
                differences.append(
                    {"field": aggregate_name, "expected": expected_values, "actual": actual_values}
                )
            continue
        if len(expected_values) != len(actual_values):
            differences.append(
                {"field": aggregate_name, "expected": expected_values, "actual": actual_values}
            )
            continue
        for index, (expected_value, actual_value) in enumerate(zip(expected_values, actual_values)):
            if isinstance(expected_value, (int, float)) and isinstance(actual_value, (int, float)):
                absolute_difference = abs(float(expected_value) - float(actual_value))
                if absolute_difference <= tolerance:
                    continue
                differences.append(
                    {
                        "field": f"{aggregate_name}[{index}]",
                        "expected": expected_value,
                        "actual": actual_value,
                        "absolute_difference": absolute_difference,
                    }
                )
            elif expected_value != actual_value:
                differences.append(
                    {
                        "field": f"{aggregate_name}[{index}]",
                        "expected": expected_value,
                        "actual": actual_value,
                    }
                )
    return not differences, differences


def import_sqlite_export_to_postgres(
    export_directory: str | Path,
    *,
    database_url: str,
) -> dict[str, Any]:
    if not database_url:
        raise RuntimeError("postgres_database_url_missing")
    try:
        import psycopg
        from psycopg import sql
    except ImportError as exc:
        raise RuntimeError("postgres_driver_unavailable_install_postgres_extra") from exc
    root, manifest = _read_manifest(export_directory)
    apply_postgres_migrations(database_url)
    imported_counts: dict[str, int] = {}
    with psycopg.connect(database_url) as connection:
        existing = connection.execute(
            "SELECT 1 FROM migration_imports WHERE export_id = %s",
            (manifest["export_id"],),
        ).fetchone()
        status = "already_imported" if existing else "imported"
        if existing:
            imported_counts = {table: 0 for table in manifest["tables"]}
        else:
            with connection.transaction():
                for table in _ordered_manifest_tables(manifest):
                    table_manifest = manifest["tables"][table]
                    _safe_identifier(table)
                    rows = [
                        json.loads(line)
                        for line in (root / table_manifest["file"]).read_text(encoding="utf-8").splitlines()
                        if line.strip()
                    ]
                    if not rows:
                        imported_counts[table] = 0
                        continue
                    columns = list(rows[0])
                    if any(set(row) != set(columns) for row in rows):
                        raise ValueError(f"inconsistent_export_columns:{table}")
                    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}) ON CONFLICT DO NOTHING").format(
                        sql.Identifier(table),
                        sql.SQL(", ").join(sql.Identifier(column) for column in columns),
                        sql.SQL(", ").join(sql.Placeholder() for _ in columns),
                    )
                    values = []
                    for row in rows:
                        converted = []
                        for column in columns:
                            value = row[column]
                            if (table, column) in BOOLEAN_COLUMNS and value is not None:
                                value = bool(value)
                            converted.append(value)
                        values.append(tuple(converted))
                    with connection.cursor() as cursor:
                        cursor.executemany(query, values)
                        imported_counts[table] = max(0, int(cursor.rowcount or 0))
                    if "id" in columns:
                        connection.execute(
                            sql.SQL(
                                "SELECT setval(pg_get_serial_sequence({}, 'id'), "
                                "GREATEST(COALESCE(MAX(id), 1), 1), MAX(id) IS NOT NULL) FROM {}"
                            ).format(sql.Literal(table), sql.Identifier(table))
                        )
                connection.execute(
                    "INSERT INTO migration_imports (export_id, source_manifest_json) VALUES (%s, %s)",
                    (manifest["export_id"], json.dumps(manifest, sort_keys=True)),
                )
        destination_counts = {
            table: int(connection.execute(sql.SQL("SELECT COUNT(*) FROM {}").format(sql.Identifier(table))).fetchone()[0])
            for table in manifest["tables"]
        }
        destination_aggregates = _postgres_critical_aggregates(connection)
    count_matches = {
        table: destination_counts[table] == table_manifest["row_count"]
        for table, table_manifest in manifest["tables"].items()
    }
    aggregate_match, aggregate_differences = _critical_aggregates_match(
        manifest.get("critical_aggregates", {}),
        destination_aggregates,
    )
    return {
        "status": status,
        "export_id": manifest["export_id"],
        "imported_counts": imported_counts,
        "destination_counts": destination_counts,
        "row_counts_match": count_matches,
        "critical_aggregates_match": aggregate_match,
        "critical_aggregate_differences": aggregate_differences,
        "critical_aggregate_tolerance": CRITICAL_AGGREGATE_TOLERANCE,
        "unintended_duplicate_rows": sum(
            max(0, destination_counts[table] - int(table_manifest["row_count"]))
            for table, table_manifest in manifest["tables"].items()
        ),
        "immutable_prediction_history_preserved": bool(count_matches.get("prediction_logs")),
    }
