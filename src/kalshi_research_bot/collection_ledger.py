from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from .business_store import active_database_backend, open_legacy_connection
from .storage import ResearchStore


BATCH_STATUSES = {
    "started",
    "completed",
    "completed_with_rejections",
    "failed",
    "blocked",
    "cancelled",
}
FRESHNESS_STATES = {
    "fresh",
    "approaching_stale",
    "stale",
    "missing",
    "blocked",
    "failed",
    "unknown",
}


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def content_hash(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value).encode('utf-8')).hexdigest()}"


@dataclass(frozen=True)
class BatchStart:
    batch_id: str
    created: bool


class CollectionLedger:
    """SQLite-compatible operational ledger used by existing collectors during migration."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if active_database_backend(self.path) == "sqlite":
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if not self._ledger_schema_exists():
                ResearchStore(self.path).initialize()
        else:
            connection = open_legacy_connection(self.path)
            connection.close()

    def _ledger_schema_exists(self) -> bool:
        if not self.path.exists():
            return False
        connection = sqlite3.connect(self.path, timeout=10)
        try:
            connection.execute("PRAGMA busy_timeout=10000")
            row = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'ingestion_batches'"
            ).fetchone()
            return row is not None
        finally:
            connection.close()

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        connection = open_legacy_connection(self.path)
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout=10000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def start_batch(
        self,
        *,
        idempotency_key: str,
        source: str,
        endpoint: str,
        worker_name: str,
        worker_version: str,
        collector_version: str,
        collection_mode: str = "live",
        request_parameters: Mapping[str, Any] | None = None,
        cursor_start: str | None = None,
        window_start: str | None = None,
        window_end: str | None = None,
        started_at: str | None = None,
    ) -> BatchStart:
        batch_id = str(uuid.uuid4())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO ingestion_batches (
                    batch_id, idempotency_key, source, endpoint, worker_name,
                    worker_version, collector_version, collection_mode,
                    request_parameters_json, cursor_start, window_start, window_end,
                    started_at, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'started')
                """,
                (
                    batch_id,
                    idempotency_key,
                    source,
                    endpoint,
                    worker_name,
                    worker_version,
                    collector_version,
                    collection_mode,
                    canonical_json(request_parameters or {}),
                    cursor_start,
                    window_start,
                    window_end,
                    started_at or utc_iso(),
                ),
            )
            if cursor.rowcount:
                return BatchStart(batch_id=batch_id, created=True)
            existing = connection.execute(
                "SELECT batch_id FROM ingestion_batches WHERE idempotency_key = ?",
                (idempotency_key,),
            ).fetchone()
            return BatchStart(batch_id=str(existing["batch_id"]), created=False)

    def store_payload(
        self,
        *,
        batch_id: str,
        source: str,
        entity_type: str,
        payload: Any,
        parser_version: str,
        source_identifier: str | None = None,
        observed_at: str | None = None,
        received_at: str | None = None,
    ) -> dict[str, Any]:
        digest = content_hash(payload)
        payload_id = str(uuid.uuid4())
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO raw_source_payloads (
                    payload_id, batch_id, source, entity_type, source_identifier,
                    observed_at, received_at, content_hash, payload_json, parser_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    payload_id,
                    batch_id,
                    source,
                    entity_type,
                    source_identifier,
                    observed_at,
                    received_at or utc_iso(),
                    digest,
                    canonical_json(payload),
                    parser_version,
                ),
            )
            if cursor.rowcount:
                return {"payload_id": payload_id, "content_hash": digest, "duplicate": False}
            existing = connection.execute(
                """
                SELECT payload_id FROM raw_source_payloads
                WHERE batch_id = ? AND source_identifier IS ? AND content_hash = ?
                """,
                (batch_id, source_identifier, digest),
            ).fetchone()
            return {"payload_id": str(existing["payload_id"]), "content_hash": digest, "duplicate": True}

    def reject(
        self,
        *,
        batch_id: str,
        entity_type: str,
        rejection_code: str,
        parser_version: str,
        payload_id: str | None = None,
        rejection_detail: str | None = None,
        rejected_at: str | None = None,
    ) -> str:
        rejection_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO rejected_records (
                    rejection_id, batch_id, payload_id, entity_type, rejection_code,
                    rejection_detail, parser_version, rejected_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    rejection_id,
                    batch_id,
                    payload_id,
                    entity_type,
                    rejection_code,
                    rejection_detail,
                    parser_version,
                    rejected_at or utc_iso(),
                ),
            )
        return rejection_id

    def complete_batch(
        self,
        *,
        batch_id: str,
        records_received: int,
        records_accepted: int,
        records_rejected: int,
        records_duplicated: int,
        payload_hash_value: str | None = None,
        http_status: int | None = None,
        cursor_end: str | None = None,
        checkpoint: Mapping[str, Any] | None = None,
        completed_at: str | None = None,
    ) -> None:
        status = "completed_with_rejections" if records_rejected else "completed"
        finished = completed_at or utc_iso()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE ingestion_batches
                SET completed_at = ?, status = ?, http_status = ?, records_received = ?,
                    records_accepted = ?, records_rejected = ?, records_duplicated = ?,
                    payload_hash = ?, cursor_end = ?
                WHERE batch_id = ? AND status = 'started'
                """,
                (
                    finished,
                    status,
                    http_status,
                    records_received,
                    records_accepted,
                    records_rejected,
                    records_duplicated,
                    payload_hash_value,
                    cursor_end,
                    batch_id,
                ),
            )
            if checkpoint:
                connection.execute(
                    """
                    INSERT INTO collection_checkpoints (
                        source, endpoint, partition_scope, cursor, window_start, window_end,
                        last_successful_item_time, batch_id, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(source, endpoint, partition_scope) DO UPDATE SET
                        cursor = excluded.cursor,
                        window_start = excluded.window_start,
                        window_end = excluded.window_end,
                        last_successful_item_time = excluded.last_successful_item_time,
                        batch_id = excluded.batch_id,
                        updated_at = excluded.updated_at
                    """,
                    (
                        checkpoint["source"],
                        checkpoint["endpoint"],
                        checkpoint.get("partition_scope", ""),
                        checkpoint.get("cursor"),
                        checkpoint.get("window_start"),
                        checkpoint.get("window_end"),
                        checkpoint.get("last_successful_item_time"),
                        batch_id,
                        finished,
                    ),
                )

    def fail_batch(
        self,
        *,
        batch_id: str,
        error_code: str,
        error_message: str | None = None,
        blocked: bool = False,
        completed_at: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE ingestion_batches
                SET completed_at = ?, status = ?, error_code = ?, error_message = ?
                WHERE batch_id = ? AND status = 'started'
                """,
                (completed_at or utc_iso(), "blocked" if blocked else "failed", error_code, error_message, batch_id),
            )

    def update_source_health(
        self,
        *,
        source: str,
        last_attempted_at: str,
        freshness_state: str,
        last_successful_at: str | None = None,
        freshness_deadline: str | None = None,
        last_error: str | None = None,
    ) -> None:
        if freshness_state not in FRESHNESS_STATES:
            raise ValueError(f"invalid_freshness_state:{freshness_state}")
        with self._connect() as connection:
            previous = connection.execute(
                "SELECT consecutive_failures FROM source_health WHERE source = ?",
                (source,),
            ).fetchone()
            failures = 0 if freshness_state in {"fresh", "approaching_stale"} else int(previous[0] if previous else 0) + 1
            connection.execute(
                """
                INSERT INTO source_health (
                    source, last_attempted_at, last_successful_at, freshness_deadline,
                    freshness_state, consecutive_failures, last_error, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source) DO UPDATE SET
                    last_attempted_at = excluded.last_attempted_at,
                    last_successful_at = COALESCE(excluded.last_successful_at, source_health.last_successful_at),
                    freshness_deadline = excluded.freshness_deadline,
                    freshness_state = excluded.freshness_state,
                    consecutive_failures = excluded.consecutive_failures,
                    last_error = excluded.last_error,
                    updated_at = excluded.updated_at
                """,
                (
                    source,
                    last_attempted_at,
                    last_successful_at,
                    freshness_deadline,
                    freshness_state,
                    failures,
                    last_error,
                    utc_iso(),
                ),
            )

    def checkpoint(self, *, source: str, endpoint: str, partition_scope: str = "") -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM collection_checkpoints
                WHERE source = ? AND endpoint = ? AND partition_scope = ?
                """,
                (source, endpoint, partition_scope),
            ).fetchone()
            return dict(row) if row else None
