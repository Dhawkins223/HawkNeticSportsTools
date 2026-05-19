from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.database import execute, get_connection


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RawImportTracker:
    @staticmethod
    def create_job(source: str, season: int | None = None, status: str = "running") -> int:
        with get_connection() as conn:
            cur = execute(conn, "INSERT INTO raw_import_jobs(source, season, status, started_at) VALUES(?, ?, ?, ?)", (source, season, status, utc_now()))
            return int(cur.lastrowid)

    @staticmethod
    def finish_job(job_id: int, status: str, counts: dict[str, int] | None = None, error_message: str | None = None) -> None:
        counts = counts or {}
        with get_connection() as conn:
            execute(conn, """
                UPDATE raw_import_jobs
                   SET status = ?,
                       finished_at = ?,
                       records_fetched = ?,
                       records_inserted = ?,
                       records_updated = ?,
                       records_skipped = ?,
                       records_failed = ?,
                       error_message = ?
                 WHERE id = ?
            """, (
                status,
                utc_now(),
                int(counts.get("records_fetched", counts.get("fetched", 0))),
                int(counts.get("records_inserted", counts.get("inserted", 0))),
                int(counts.get("records_updated", counts.get("updated", 0))),
                int(counts.get("records_skipped", counts.get("skipped", 0))),
                int(counts.get("records_failed", counts.get("failed", 0))),
                error_message,
                job_id,
            ))

    @staticmethod
    def log_error(job_id: int | None, source: str, error_message: str, season: int | None = None, raw_payload_id: int | None = None, table_name: str | None = None, row_identifier: str | None = None) -> None:
        with get_connection() as conn:
            execute(conn, """
                INSERT INTO raw_import_errors(job_id, source, season, raw_payload_id, table_name, row_identifier, error_message)
                VALUES(?, ?, ?, ?, ?, ?, ?)
            """, (job_id, source, season, raw_payload_id, table_name, row_identifier, error_message))

    @staticmethod
    def store_historical_payload(job_id: int, season: int, payload_type: str, source_url: str | None = None, raw_json: dict[str, Any] | list[Any] | None = None, raw_text: str | None = None) -> int:
        with get_connection() as conn:
            cur = execute(conn, """
                INSERT INTO raw_historical_payloads(job_id, source, season, payload_type, source_url, raw_json, raw_text)
                VALUES(?, 'basketball_reference', ?, ?, ?, ?, ?)
            """, (job_id, season, payload_type, source_url, json.dumps(raw_json, separators=(",", ":")) if raw_json is not None else None, raw_text))
            return int(cur.lastrowid)

    @staticmethod
    def store_historical_files(job_id: int, season: int, season_path: Path, root_path: Path) -> int:
        stored = 0
        for path in [root_path / "teams.csv", root_path / "players.csv", *sorted(season_path.glob("*.csv")), *sorted(season_path.glob("*.json"))]:
            if not path.exists() or not path.is_file():
                continue
            try:
                RawImportTracker.store_historical_payload(
                    job_id=job_id,
                    season=season,
                    payload_type=path.name,
                    source_url=str(path),
                    raw_text=path.read_text(encoding="utf-8", errors="replace"),
                )
                stored += 1
            except Exception as exc:
                RawImportTracker.log_error(job_id, "basketball_reference", str(exc), season=season, table_name="raw_historical_payloads", row_identifier=str(path))
        return stored

    @staticmethod
    def store_balldontlie_payload(job_id: int, endpoint: str, request_params: dict[str, Any], raw_json: dict[str, Any]) -> int:
        with get_connection() as conn:
            cur = execute(conn, """
                INSERT INTO raw_balldontlie_payloads(job_id, endpoint, request_params, raw_json)
                VALUES(?, ?, ?, ?)
            """, (job_id, endpoint, json.dumps(request_params, separators=(",", ":")), json.dumps(raw_json, separators=(",", ":"))))
            return int(cur.lastrowid)
