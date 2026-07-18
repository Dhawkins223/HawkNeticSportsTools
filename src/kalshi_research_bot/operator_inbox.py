from __future__ import annotations

import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .business_store import active_database_backend, open_legacy_connection
from .storage import ResearchStore


PRIORITIES = ("low", "normal", "high", "urgent")
TARGETS = ("codex", "code", "research", "operations")
STATUSES = ("queued", "claimed", "completed", "rejected")
SOURCES = ("dashboard", "cli", "github")
MAX_TITLE_LENGTH = 200
MAX_BODY_LENGTH = 100_000
MAX_SUMMARY_LENGTH = 10_000


def utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_required(value: str, *, name: str, maximum: int) -> str:
    cleaned = str(value or "").strip()
    if not cleaned:
        raise ValueError(f"{name}_required")
    if len(cleaned) > maximum:
        raise ValueError(f"{name}_too_long")
    return cleaned


def _row_payload(row: sqlite3.Row) -> dict[str, Any]:
    payload = dict(row)
    payload["requires_approval"] = bool(payload["requires_approval"])
    payload["execution_allowed"] = bool(payload["execution_allowed"])
    return payload


class OperatorInbox:
    """Private instruction queue that never executes submitted content."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        if active_database_backend(self.path) == "sqlite":
            ResearchStore(self.path).initialize()
        else:
            connection = open_legacy_connection(self.path)
            connection.close()

    @contextmanager
    def connection(self) -> Iterator[Any]:
        connection = open_legacy_connection(self.path)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def add(
        self,
        *,
        title: str,
        body: str,
        created_by: str,
        priority: str = "normal",
        target: str = "codex",
        source: str = "cli",
        message_id: str | None = None,
    ) -> dict[str, Any]:
        clean_title = _clean_required(title, name="title", maximum=MAX_TITLE_LENGTH)
        clean_body = _clean_required(body, name="body", maximum=MAX_BODY_LENGTH)
        clean_creator = _clean_required(created_by, name="created_by", maximum=128)
        if priority not in PRIORITIES:
            raise ValueError("invalid_priority")
        if target not in TARGETS:
            raise ValueError("invalid_target")
        if source not in SOURCES:
            raise ValueError("invalid_source")
        resolved_id = str(message_id or f"msg_{uuid.uuid4().hex}").strip()
        if not resolved_id or len(resolved_id) > 96:
            raise ValueError("invalid_message_id")
        now = utc_iso()
        with self.connection() as connection:
            existing = connection.execute(
                "SELECT * FROM operator_messages WHERE message_id = ?",
                (resolved_id,),
            ).fetchone()
            if existing is not None:
                if (
                    existing["title"] != clean_title
                    or existing["body"] != clean_body
                    or existing["created_by"] != clean_creator
                ):
                    raise ValueError("message_id_conflict")
                return _row_payload(existing)
            connection.execute(
                """
                INSERT INTO operator_messages (
                    message_id, created_at, updated_at, created_by, title, body,
                    priority, target, status, source, requires_approval,
                    execution_allowed
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'queued', ?, ?, ?)
                """,
                (
                    resolved_id,
                    now,
                    now,
                    clean_creator,
                    clean_title,
                    clean_body,
                    priority,
                    target,
                    source,
                    True,
                    False,
                ),
            )
            row = connection.execute(
                "SELECT * FROM operator_messages WHERE message_id = ?",
                (resolved_id,),
            ).fetchone()
        return _row_payload(row)

    def list(
        self,
        *,
        status: str | None = None,
        target: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if status is not None and status not in STATUSES:
            raise ValueError("invalid_status")
        if target is not None and target not in TARGETS:
            raise ValueError("invalid_target")
        clauses: list[str] = []
        parameters: list[Any] = []
        if status is not None:
            clauses.append("status = ?")
            parameters.append(status)
        if target is not None:
            clauses.append("target = ?")
            parameters.append(target)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        parameters.append(max(1, min(int(limit), 500)))
        with self.connection() as connection:
            rows = connection.execute(
                f"""
                SELECT * FROM operator_messages
                {where}
                ORDER BY
                    CASE priority
                        WHEN 'urgent' THEN 1
                        WHEN 'high' THEN 2
                        WHEN 'normal' THEN 3
                        ELSE 4
                    END,
                    created_at ASC
                LIMIT ?
                """,
                parameters,
            ).fetchall()
        return [_row_payload(row) for row in rows]

    def get(self, message_id: str) -> dict[str, Any] | None:
        with self.connection() as connection:
            row = connection.execute(
                "SELECT * FROM operator_messages WHERE message_id = ?",
                (str(message_id),),
            ).fetchone()
        return _row_payload(row) if row is not None else None

    def claim(self, message_id: str, *, agent: str) -> dict[str, Any]:
        clean_agent = _clean_required(agent, name="agent", maximum=128)
        now = utc_iso()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operator_messages WHERE message_id = ?",
                (str(message_id),),
            ).fetchone()
            if row is None:
                raise ValueError("message_not_found")
            if row["status"] == "claimed" and row["claimed_by"] == clean_agent:
                return _row_payload(row)
            if row["status"] != "queued":
                raise ValueError(f"message_not_claimable:{row['status']}")
            connection.execute(
                """
                UPDATE operator_messages
                SET status = 'claimed', claimed_by = ?, claimed_at = ?, updated_at = ?
                WHERE message_id = ?
                """,
                (clean_agent, now, now, str(message_id)),
            )
            updated = connection.execute(
                "SELECT * FROM operator_messages WHERE message_id = ?",
                (str(message_id),),
            ).fetchone()
        return _row_payload(updated)

    def complete(self, message_id: str, *, agent: str, summary: str) -> dict[str, Any]:
        clean_agent = _clean_required(agent, name="agent", maximum=128)
        clean_summary = _clean_required(summary, name="summary", maximum=MAX_SUMMARY_LENGTH)
        now = utc_iso()
        with self.connection() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM operator_messages WHERE message_id = ?",
                (str(message_id),),
            ).fetchone()
            if row is None:
                raise ValueError("message_not_found")
            if row["status"] == "completed" and row["claimed_by"] == clean_agent:
                return _row_payload(row)
            if row["status"] != "claimed":
                raise ValueError(f"message_not_completable:{row['status']}")
            if row["claimed_by"] != clean_agent:
                raise ValueError("message_claimed_by_another_agent")
            connection.execute(
                """
                UPDATE operator_messages
                SET status = 'completed', completed_at = ?, result_summary = ?, updated_at = ?
                WHERE message_id = ?
                """,
                (now, clean_summary, now, str(message_id)),
            )
            updated = connection.execute(
                "SELECT * FROM operator_messages WHERE message_id = ?",
                (str(message_id),),
            ).fetchone()
        return _row_payload(updated)

    def counts(self) -> dict[str, int]:
        with self.connection() as connection:
            rows = connection.execute(
                "SELECT status, COUNT(*) AS count FROM operator_messages GROUP BY status"
            ).fetchall()
        counts = {status: 0 for status in STATUSES}
        counts.update({str(row["status"]): int(row["count"]) for row in rows})
        return counts
