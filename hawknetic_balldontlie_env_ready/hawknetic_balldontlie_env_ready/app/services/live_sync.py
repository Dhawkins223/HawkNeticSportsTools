"""Live-data ingestion. Accepts JSON snapshots from any provider (Ball Don't Lie,
custom scraper, manual admin entry) and routes them into the live_* tables.

Design intent: providers come and go, but the writer contracts stay stable.
Every write hits `live_data_snapshots` for an audit trail before fanning out.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from app.database import execute, get_connection


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def ingest_snapshot(envelope: dict[str, Any]) -> dict[str, Any]:
    kind = (envelope.get("kind") or "").lower()
    payload = envelope.get("payload") or {}
    if not kind or not payload:
        return {"ok": False, "error": "Snapshot must include `kind` and `payload`."}

    with get_connection() as conn:
        execute(conn, "INSERT INTO live_data_snapshots(kind, payload) VALUES(?, ?)", (kind, json.dumps(payload, separators=(",", ":"))))
        if kind == "game_state":
            return _write_game_state(conn, payload)
        if kind == "odds":
            return _write_odds(conn, payload)
        if kind == "player_status":
            return _write_player_status(conn, payload)
        if kind == "injury":
            return _write_injury(conn, payload)
        if kind == "props":
            return _write_props(conn, payload)
    return {"ok": False, "error": f"Unknown snapshot kind: {kind}"}


def _write_game_state(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    game_id = int(payload["game_id"])
    fields = (
        "status", "period", "clock", "home_score", "away_score",
        "home_team_id", "away_team_id", "tipoff_at", "source",
    )
    values = [payload.get(f) for f in fields]
    existing = execute(conn, "SELECT 1 FROM live_games WHERE game_id = ?", (game_id,)).fetchone()
    if existing:
        execute(conn, """
            UPDATE live_games SET status=?, period=?, clock=?, home_score=?, away_score=?,
                home_team_id=?, away_team_id=?, tipoff_at=?, source=?, last_updated=?
            WHERE game_id=?
        """, (*values, _now(), game_id))
    else:
        execute(conn, """
            INSERT INTO live_games(game_id, status, period, clock, home_score, away_score,
                home_team_id, away_team_id, tipoff_at, source, last_updated)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (game_id, *values, _now()))
    return {"ok": True, "kind": "game_state", "game_id": game_id}


def _write_odds(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or [payload]
    written = 0
    for row in rows:
        execute(conn, """
            INSERT INTO live_odds(game_id, market, selection, line, american_odds, sportsbook, last_updated)
            VALUES(?,?,?,?,?,?,?)
        """, (
            int(row["game_id"]),
            row.get("market"),
            row.get("selection"),
            row.get("line"),
            int(row["american_odds"]),
            row.get("sportsbook", "consensus"),
            _now(),
        ))
        execute(conn, """
            INSERT INTO live_line_movement(game_id, market, selection, line, american_odds, sportsbook, captured_at)
            VALUES(?,?,?,?,?,?,?)
        """, (
            int(row["game_id"]),
            row.get("market"),
            row.get("selection"),
            row.get("line"),
            int(row["american_odds"]),
            row.get("sportsbook", "consensus"),
            _now(),
        ))
        written += 1
    return {"ok": True, "kind": "odds", "rows_written": written}


def _write_player_status(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or [payload]
    written = 0
    for row in rows:
        player_id = int(row["player_id"])
        game_id = int(row["game_id"])
        existing = execute(conn, "SELECT 1 FROM live_player_status WHERE player_id = ? AND game_id = ?", (player_id, game_id)).fetchone()
        cols = ("status", "minutes_played", "minutes_restriction", "fouls",
                "points", "rebounds", "assists", "threes", "starter", "source")
        values = [row.get(c) for c in cols]
        if existing:
            execute(conn, """
                UPDATE live_player_status SET status=?, minutes_played=?, minutes_restriction=?, fouls=?,
                    points=?, rebounds=?, assists=?, threes=?, starter=?, source=?, last_updated=?
                WHERE player_id=? AND game_id=?
            """, (*values, _now(), player_id, game_id))
        else:
            execute(conn, """
                INSERT INTO live_player_status(player_id, game_id, status, minutes_played, minutes_restriction,
                    fouls, points, rebounds, assists, threes, starter, source, last_updated)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (player_id, game_id, *values, _now()))
        written += 1
    return {"ok": True, "kind": "player_status", "rows_written": written}


def _write_injury(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    rows = payload.get("rows") or [payload]
    written = 0
    for row in rows:
        execute(conn, """
            INSERT INTO live_injuries(player_id, designation, note, reported_at, source)
            VALUES(?,?,?,?,?)
        """, (
            int(row["player_id"]),
            row.get("designation", "questionable"),
            row.get("note"),
            row.get("reported_at") or _now(),
            row.get("source", "manual"),
        ))
        written += 1
    return {"ok": True, "kind": "injury", "rows_written": written}


def _write_props(conn: Any, payload: dict[str, Any]) -> dict[str, Any]:
    """Refresh the existing `props` table with provider data + bump updated_at."""
    rows = payload.get("rows") or [payload]
    written = 0
    for row in rows:
        execute(conn, """
            INSERT INTO props(game_id, player_id, market, line, over_odds, under_odds,
                model_probability, expected_value, confidence_tier, source, updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """, (
            int(row["game_id"]),
            int(row["player_id"]) if row.get("player_id") else None,
            row.get("market"),
            row.get("line"),
            row.get("over_odds"),
            row.get("under_odds"),
            row.get("model_probability"),
            row.get("expected_value"),
            row.get("confidence_tier", "MEDIUM"),
            row.get("source", "live"),
            _now(),
        ))
        written += 1
    return {"ok": True, "kind": "props", "rows_written": written}
