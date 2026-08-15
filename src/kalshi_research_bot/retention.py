"""Age out raw payload bodies without losing the evidence they prove.

`raw.source_payloads` keeps one full response body per collection cycle. Kalshi
ingestion runs every five minutes, so the table grows without bound: it filled
the staging volume outright and production is on the same curve.

Deleting those rows is not an option. Core observations carry foreign keys into
them, and the project's integrity contract treats a payload's content hash as
authoritative evidence that a collection happened and what it contained. So this
prunes the *body* and keeps everything that proves the collection: the row, its
batch lineage, its timestamps, its parser version, and its `content_hash`.

The body is replaced by a tombstone recording when it was pruned and how large it
was. Dedup and import lineage compare the `content_hash` column and never re-hash
the body, so pruning does not disturb either. The body itself is not recoverable.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .business_store import ensure_database_ready
from .database import DatabaseSettings, connection_pool


TOMBSTONE_KEY = "__retention__"
TOMBSTONE_STATE = "body_pruned"
DEFAULT_RETENTION_DAYS = 30
MINIMUM_RETENTION_DAYS = 7
DEFAULT_BATCH_LIMIT = 5000


class RetentionWindowTooShort(ValueError):
    """Raised when a requested window would prune recent evidence."""


def _now(now: datetime | str | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(now).replace("Z", "+00:00")).astimezone(timezone.utc)


def _tombstone(*, pruned_at: str, original_bytes: int, content_hash: str) -> str:
    return json.dumps(
        {
            TOMBSTONE_KEY: {
                "state": TOMBSTONE_STATE,
                "pruned_at": pruned_at,
                "original_bytes": int(original_bytes),
                "content_hash": content_hash,
            }
        },
        sort_keys=True,
        separators=(",", ":"),
    )


# One definition of "prunable", shared by the pruner and the report so the two can
# never disagree about how much is eligible. The newest payload per
# (source, entity_type) is what the dashboard reads for its current snapshot, so it
# is never a candidate no matter how the window is configured.
_PRUNABLE_SQL = """
    WITH newest AS (
        SELECT DISTINCT ON (source, entity_type) id
        FROM raw.source_payloads
        ORDER BY source, entity_type, observed_at DESC NULLS LAST, id DESC
    )
    SELECT {columns}
    FROM raw.source_payloads
    WHERE received_at < %s
      AND id NOT IN (SELECT id FROM newest)
      AND NOT jsonb_exists(payload_json, %s)
      AND (%s::text IS NULL OR source = %s)
"""


def _prunable_rows(
    connection: Any,
    *,
    cutoff: datetime,
    limit: int,
    source: str | None,
) -> list[Any]:
    statement = (
        _PRUNABLE_SQL.format(columns="id, content_hash, pg_column_size(payload_json) AS body_bytes")
        + " ORDER BY received_at, id LIMIT %s"
    )
    return connection.execute(statement, (cutoff, TOMBSTONE_KEY, source, source, limit)).fetchall()


def _prunable_totals(connection: Any, *, cutoff: datetime, source: str | None) -> Any:
    statement = _PRUNABLE_SQL.format(
        columns="COUNT(*) AS rows, COALESCE(SUM(pg_column_size(payload_json)), 0) AS body_bytes"
    )
    return connection.execute(statement, (cutoff, TOMBSTONE_KEY, source, source)).fetchone()


def prune_source_payload_bodies(
    *,
    older_than_days: int = DEFAULT_RETENTION_DAYS,
    source: str | None = None,
    limit: int = DEFAULT_BATCH_LIMIT,
    dry_run: bool = True,
    settings: DatabaseSettings | None = None,
    now: datetime | str | None = None,
) -> dict[str, Any]:
    """Replace payload bodies older than the window with a tombstone.

    Defaults to a dry run: the same rows are measured and reported, and nothing is
    written. Pass `dry_run=False` to apply.
    """
    days = int(older_than_days)
    if days < MINIMUM_RETENTION_DAYS:
        raise RetentionWindowTooShort(
            f"retention_window_below_minimum:{days}<{MINIMUM_RETENTION_DAYS}"
        )
    configured = ensure_database_ready(settings)
    moment = _now(now)
    cutoff = moment - timedelta(days=days)
    bounded_limit = max(1, min(int(limit), 100000))

    with connection_pool(configured).connection() as connection:
        candidates = _prunable_rows(connection, cutoff=cutoff, limit=bounded_limit, source=source)
        reclaimable_bytes = sum(int(row["body_bytes"] or 0) for row in candidates)
        pruned = 0
        if not dry_run and candidates:
            pruned_at = moment.isoformat()
            for row in candidates:
                connection.execute(
                    "UPDATE raw.source_payloads SET payload_json = %s::jsonb WHERE id = %s",
                    (
                        _tombstone(
                            pruned_at=pruned_at,
                            original_bytes=int(row["body_bytes"] or 0),
                            content_hash=str(row["content_hash"]),
                        ),
                        int(row["id"]),
                    ),
                )
                pruned += 1
        # Counted after the updates, so it already reflects what this pass wrote.
        remaining = _prunable_totals(connection, cutoff=cutoff, source=source)

    return {
        "dry_run": bool(dry_run),
        "evaluated_at": moment.isoformat(),
        "cutoff": cutoff.isoformat(),
        "older_than_days": days,
        "source": source,
        "candidates": len(candidates),
        "pruned": pruned,
        "reclaimable_bytes": reclaimable_bytes,
        "remaining_after_limit": int(remaining["rows"] or 0),
        "limit": bounded_limit,
        "note": (
            "Payload bodies are replaced by a tombstone. Rows, batch lineage, "
            "timestamps, parser versions, and content hashes are preserved; the "
            "body itself is not recoverable. PostgreSQL reuses the freed space for "
            "new rows, but returning it to the filesystem needs a VACUUM FULL, "
            "which requires free space of its own."
        ),
    }


def source_payload_storage_report(
    *,
    settings: DatabaseSettings | None = None,
    now: datetime | str | None = None,
    older_than_days: int = DEFAULT_RETENTION_DAYS,
) -> dict[str, Any]:
    """Where the raw table's space is going, and how much a prune would free."""
    configured = ensure_database_ready(settings)
    moment = _now(now)
    cutoff = moment - timedelta(days=int(older_than_days))
    with connection_pool(configured).connection() as connection:
        totals = connection.execute(
            """
            SELECT COUNT(*) AS rows,
                   COUNT(*) FILTER (WHERE jsonb_exists(payload_json, %s)) AS tombstoned,
                   COALESCE(SUM(pg_column_size(payload_json)), 0) AS body_bytes,
                   MIN(received_at) AS oldest,
                   MAX(received_at) AS newest
            FROM raw.source_payloads
            """,
            (TOMBSTONE_KEY,),
        ).fetchone()
        prunable = _prunable_totals(connection, cutoff=cutoff, source=None)
        by_source = connection.execute(
            """
            SELECT source,
                   COUNT(*) AS rows,
                   COALESCE(SUM(pg_column_size(payload_json)), 0) AS body_bytes
            FROM raw.source_payloads
            GROUP BY source
            ORDER BY SUM(pg_column_size(payload_json)) DESC
            """
        ).fetchall()
    return {
        "evaluated_at": moment.isoformat(),
        "cutoff": cutoff.isoformat(),
        "older_than_days": int(older_than_days),
        "total_rows": int(totals["rows"] or 0),
        "tombstoned_rows": int(totals["tombstoned"] or 0),
        "total_body_bytes": int(totals["body_bytes"] or 0),
        "oldest_received_at": totals["oldest"].isoformat() if totals["oldest"] else None,
        "newest_received_at": totals["newest"].isoformat() if totals["newest"] else None,
        "prunable_rows": int(prunable["rows"] or 0),
        "prunable_body_bytes": int(prunable["body_bytes"] or 0),
        "by_source": [
            {
                "source": str(row["source"]),
                "rows": int(row["rows"]),
                "body_bytes": int(row["body_bytes"]),
            }
            for row in by_source
        ],
    }


def _megabytes(value: object) -> str:
    try:
        return f"{float(value) / (1024 * 1024):.1f} MB"
    except (TypeError, ValueError):
        return "n/a"


def render_storage_report(report: dict[str, Any]) -> str:
    lines = [
        "Raw Source Payload Storage",
        f"Rows: {report.get('total_rows')} ({report.get('tombstoned_rows')} already pruned)",
        f"Payload bodies: {_megabytes(report.get('total_body_bytes'))}",
        f"Oldest / newest: {report.get('oldest_received_at')} / {report.get('newest_received_at')}",
        "",
        f"Older than {report.get('older_than_days')} days:",
        f"  Rows: {report.get('prunable_rows')}",
        f"  Reclaimable: {_megabytes(report.get('prunable_body_bytes'))}",
        "",
        "By source:",
    ]
    for entry in report.get("by_source") or []:
        lines.append(f"  {entry['source']}: {entry['rows']} rows, {_megabytes(entry['body_bytes'])}")
    return "\n".join(lines)
