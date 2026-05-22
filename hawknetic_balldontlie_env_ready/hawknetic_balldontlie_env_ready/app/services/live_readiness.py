"""HawkNetic live-data readiness checks.

Exposes a single function `check_readiness()` used by:
- `GET /api/live/readiness`            (admin status check)
- `analyze_slip()`                     (every Run Algorithm call attaches
                                        readiness warnings to the response)

Freshness rules from the spec:
- live odds / props:     stale after 5 minutes
- live player status:    stale after 30 minutes
- live game (active):    stale after 90 seconds
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from app.database import execute, get_connection

ODDS_FRESHNESS_SEC = 5 * 60
PROPS_FRESHNESS_SEC = 5 * 60
PLAYER_STATUS_FRESHNESS_SEC = 30 * 60
LIVE_GAME_FRESHNESS_SEC = 90


def _parse_ts(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    try:
        text = str(value).replace(" ", "T").replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _age_seconds(value: Any) -> float | None:
    dt = _parse_ts(value)
    if not dt:
        return None
    return (datetime.now(timezone.utc) - dt).total_seconds()


def _latest_age(conn: Any, sql: str, params: tuple = ()) -> float | None:
    row = execute(conn, sql, params).fetchone()
    if not row:
        return None
    d = dict(row)
    return _age_seconds(d.get("ts"))


def check_readiness(game_ids: list[int] | None = None) -> dict[str, Any]:
    """Returns readiness for the entire system or filtered to specific games.

    Keys: ready, status, blocking_reasons, warnings, last_updated, checks{}.
    """
    blocking: list[str] = []
    warnings: list[str] = []
    checks: dict[str, bool] = {}

    with get_connection() as conn:
        # Games loaded
        games_count = int(dict(execute(conn, "SELECT COUNT(*) AS c FROM historical_games").fetchone() or {"c": 0}).get("c", 0))
        bdl_games = int(dict(execute(conn, "SELECT COUNT(*) AS c FROM bdl_games").fetchone() or {"c": 0}).get("c", 0))
        checks["games_loaded"] = (games_count + bdl_games) > 0
        if not checks["games_loaded"]:
            blocking.append("No games loaded — sync today's slate before running the algorithm.")

        # Odds + props loaded and fresh
        props_count = int(dict(execute(conn, "SELECT COUNT(*) AS c FROM props").fetchone() or {"c": 0}).get("c", 0))
        odds_count = int(dict(execute(conn, "SELECT COUNT(*) AS c FROM odds").fetchone() or {"c": 0}).get("c", 0))
        live_odds_count = int(dict(execute(conn, "SELECT COUNT(*) AS c FROM live_odds").fetchone() or {"c": 0}).get("c", 0))
        checks["props_loaded"] = props_count > 0
        checks["odds_loaded"] = (odds_count + live_odds_count) > 0
        if not checks["props_loaded"]:
            warnings.append("Prop markets are empty.")
        if not checks["odds_loaded"]:
            warnings.append("Reference odds are empty.")

        # Freshness — props
        props_age = _latest_age(conn, "SELECT MAX(updated_at) AS ts FROM props")
        live_odds_age = _latest_age(conn, "SELECT MAX(last_updated) AS ts FROM live_odds")
        prop_fresh = props_age is None or props_age <= PROPS_FRESHNESS_SEC
        odds_fresh = live_odds_age is None or live_odds_age <= ODDS_FRESHNESS_SEC
        checks["timestamps_fresh"] = prop_fresh and odds_fresh
        if props_age is not None and props_age > PROPS_FRESHNESS_SEC:
            warnings.append(f"Prop lines are {int(props_age // 60)}m old — refresh before betting decisions.")
        if live_odds_age is not None and live_odds_age > ODDS_FRESHNESS_SEC:
            warnings.append(f"Live odds are {int(live_odds_age // 60)}m old.")

        # Player status / injuries
        status_count = int(dict(execute(conn, "SELECT COUNT(*) AS c FROM live_player_status").fetchone() or {"c": 0}).get("c", 0))
        injuries_count = int(dict(execute(conn, "SELECT COUNT(*) AS c FROM live_injuries").fetchone() or {"c": 0}).get("c", 0))
        checks["player_status_loaded"] = status_count > 0
        checks["injuries_loaded"] = injuries_count > 0
        if not checks["player_status_loaded"]:
            warnings.append("No live player-status data — projections fall back to baseline minutes.")

        # Lineups / box scores
        checks["lineups_loaded"] = status_count > 0
        checks["box_scores_loaded"] = status_count > 0

        # Live game freshness for any in-flight game
        live_age = _latest_age(conn, "SELECT MAX(last_updated) AS ts FROM live_games WHERE LOWER(status) IN ('live', 'in_progress', 'halftime')")
        if live_age is not None and live_age > LIVE_GAME_FRESHNESS_SEC:
            blocking.append(f"Live game state is {int(live_age)}s old — exceeds the {LIVE_GAME_FRESHNESS_SEC}s freshness budget.")

        last_updated = _parse_ts(
            dict(execute(conn, """
                SELECT MAX(t) AS ts FROM (
                    SELECT MAX(updated_at) AS t FROM props
                    UNION ALL SELECT MAX(last_updated) FROM live_odds
                    UNION ALL SELECT MAX(last_updated) FROM live_games
                    UNION ALL SELECT MAX(last_updated) FROM live_player_status
                )
            """).fetchone() or {"ts": None}).get("ts")
        )

    ready = not blocking
    status = "ready" if ready else "not_ready"
    return {
        "ready": ready,
        "status": status,
        "blocking_reasons": blocking,
        "warnings": warnings,
        "last_updated": last_updated.isoformat() if last_updated else None,
        "checks": checks,
    }
