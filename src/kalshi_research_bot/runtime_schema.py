from __future__ import annotations

import re
from typing import Any


def _safe_table_name(table_name: str) -> str:
    normalized = str(table_name or "").strip()
    if not re.fullmatch(r"[a-z_][a-z0-9_]{0,62}", normalized):
        raise ValueError(f"invalid_runtime_table_name:{normalized}")
    return normalized


def table_exists(connection: Any, table_name: str) -> bool:
    table = _safe_table_name(table_name)
    row = connection.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = current_schema() AND table_name = ?
        """,
        (table,),
    ).fetchone()
    return row is not None


def table_columns(connection: Any, table_name: str) -> set[str]:
    table = _safe_table_name(table_name)
    rows = connection.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = current_schema() AND table_name = ?
        ORDER BY ordinal_position
        """,
        (table,),
    ).fetchall()
    return {str(row[0]) for row in rows}
