"""Read the sports rows the sports-research worker uploads into PostgreSQL.

`sports_research` collects public scoreboards and odds and writes normalized,
content-hashed rows into `app.sports_prediction_logs`. Nothing read them back,
so the hosted dashboard could not show sports at all. This module is the read
side of that upload: it rebuilds the upcoming board, states an explicit
freshness verdict, and derives the two comparisons a researcher would otherwise
redo by hand -- the no-vig fair price of each market and the best price
currently posted across books.

Every number here comes from an observed bookmaker price. That makes the board a
market baseline, never a validated model edge, so the payload keeps the
`baseline_only` / `track_only` contract documented in
`docs/probability-and-decision-policy.md`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Mapping

from .business_store import ensure_database_ready
from .database import DatabaseRow, DatabaseSettings, connection_pool
from .math.devig import DEFAULT_DEVIG_METHOD, method_disagreement, remove_margin


SPORTS_SOURCE_HEALTH_NAMES = ("espn_scoreboard", "the_odds_api", "sports_source")
SPORTS_WORKER_NAME = "sports-research"
BOARD_STALE_SECONDS = 60 * 60
PROBABILITY_SCALE = Decimal("0.000001")
DEFAULT_MAX_EVENTS = 60

MARKET_ORDER = {"moneyline": 0, "h2h": 0, "spread": 1, "spreads": 1, "total": 2, "totals": 2}


def _now(now: datetime | str | None = None) -> datetime:
    if now is None:
        return datetime.now(timezone.utc)
    if isinstance(now, datetime):
        return now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    return datetime.fromisoformat(str(now).replace("Z", "+00:00")).astimezone(timezone.utc)


def _iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _decimal_text(value: Any) -> str | None:
    """Serialize an exact value as a fixed-point string, never a binary float."""
    if value is None:
        return None
    number = value if isinstance(value, Decimal) else Decimal(str(value))
    return format(number, "f")


def _probability_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.quantize(PROBABILITY_SCALE), "f")


def american_implied_probability(odds: Decimal) -> Decimal | None:
    """Exact implied probability of an American price, including its vig."""
    if odds == 0:
        return None
    if odds > 0:
        return Decimal(100) / (odds + Decimal(100))
    magnitude = -odds
    return magnitude / (magnitude + Decimal(100))


def _better_price(candidate: Decimal, incumbent: Decimal) -> bool:
    """American odds pay more as the number rises (-105 beats -110, +150 beats +140)."""
    return candidate > incumbent


def _market_sort_key(market_type: str) -> int:
    return MARKET_ORDER.get(market_type.strip().lower(), 3)


def _rows_for_board(
    connection: Any,
    *,
    now: datetime,
    max_events: int,
) -> list[DatabaseRow]:
    """Latest observation per (event, market, selection, line, book) for upcoming games.

    `DISTINCT ON` keeps the most recent snapshot of each posted price so a market
    that has been re-collected every cycle contributes one current row, not one
    row per cycle.
    """
    return connection.execute(
        """
        SELECT DISTINCT ON (event_id, market_type, selection, line, bookmaker)
               event_id, sport, league, home_team, away_team, bookmaker,
               market_type, selection, line, odds, odds_format,
               game_start_time, odds_timestamp, api_fetched_at,
               prediction_timestamp, confidence_score, source_snapshot_hash,
               run_id, model_version, strategy
        FROM app.sports_prediction_logs
        WHERE validation_status = 'valid'
          AND settlement_state = 'unresolved'
          AND game_start_time > %s
          AND event_id IN (
              SELECT event_id
              FROM app.sports_prediction_logs
              WHERE validation_status = 'valid'
                AND settlement_state = 'unresolved'
                AND game_start_time > %s
              GROUP BY event_id
              ORDER BY MIN(game_start_time)
              LIMIT %s
          )
        ORDER BY event_id, market_type, selection, line, bookmaker,
                 prediction_timestamp DESC, id DESC
        """,
        (now, now, max_events),
    ).fetchall()


def _latest_upload_time(connection: Any) -> datetime | None:
    """When the collector last uploaded any valid sports row.

    Freshness describes the collector, not the slate: a day with no upcoming games
    left must not read as a dead source, and a genuinely empty table must not read
    as a fresh one.
    """
    row = connection.execute(
        """
        SELECT MAX(api_fetched_at) AS latest
        FROM app.sports_prediction_logs
        WHERE validation_status = 'valid'
        """
    ).fetchone()
    return None if row is None else row["latest"]


def _source_health(connection: Any) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT source, last_attempted_at, last_successful_at, freshness_state,
               consecutive_failures, last_error
        FROM ops.source_health
        WHERE source = ANY(%s)
        ORDER BY source
        """,
        (list(SPORTS_SOURCE_HEALTH_NAMES),),
    ).fetchall()
    return [
        {
            "source": str(row["source"]),
            "freshness_state": str(row["freshness_state"]),
            "last_attempted_at": _iso(row["last_attempted_at"]),
            "last_successful_at": _iso(row["last_successful_at"]),
            "consecutive_failures": int(row["consecutive_failures"]),
            "last_error": row["last_error"],
        }
        for row in rows
    ]


def _worker_state(connection: Any) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT worker_name, status, last_attempted_at, last_successful_at,
               consecutive_failures, last_error_code, data_fresh_at,
               source_fresh_at, heartbeat_at, model_state
        FROM ops.worker_status
        WHERE worker_name = %s
        """,
        (SPORTS_WORKER_NAME,),
    ).fetchone()
    if row is None:
        return None
    return {
        "worker_name": str(row["worker_name"]),
        "status": str(row["status"]),
        "last_attempted_at": _iso(row["last_attempted_at"]),
        "last_successful_at": _iso(row["last_successful_at"]),
        "consecutive_failures": int(row["consecutive_failures"]),
        "last_error_code": row["last_error_code"],
        "data_fresh_at": _iso(row["data_fresh_at"]),
        "source_fresh_at": _iso(row["source_fresh_at"]),
        "heartbeat_at": _iso(row["heartbeat_at"]),
        "model_state": row["model_state"],
    }


def _line_group(market_type: str, line: Any) -> Any:
    """Group the two sides of a market so they can be de-vigged together.

    Totals share one line (o8.5 / u8.5), but a spread's sides are mirrored
    (home -1.5 / away +1.5). Grouping spreads on the magnitude keeps that pair
    together; each selection still reports its own signed line.
    """
    if line is None:
        return None
    if "spread" in market_type.strip().lower():
        return abs(Decimal(str(line)))
    return Decimal(str(line))


def _selection_entry(row: DatabaseRow) -> dict[str, Any]:
    odds = Decimal(str(row["odds"]))
    implied = american_implied_probability(odds)
    return {
        "selection": str(row["selection"]),
        "line": _decimal_text(row["line"]),
        "bookmaker": str(row["bookmaker"]),
        "odds": _decimal_text(odds),
        "odds_format": str(row["odds_format"]),
        "implied_probability": _probability_text(implied),
        "odds_timestamp": _iso(row["odds_timestamp"]),
        "api_fetched_at": _iso(row["api_fetched_at"]),
        "source_snapshot_hash": str(row["source_snapshot_hash"]),
        "_odds": odds,
        "_implied": implied,
    }


def _build_market(
    *,
    market_type: str,
    line: Any,
    quotes: list[dict[str, Any]],
) -> dict[str, Any]:
    """Collapse every posted quote for one market into a comparable view.

    Each distinct selection keeps its best available price, so `best_odds` is a
    real line-shopping result rather than whichever book happened to sort first.
    The no-vig probabilities are then computed from those best prices, which is
    the fairest reading of the market a bettor can actually reach.
    """
    best_by_selection: dict[str, dict[str, Any]] = {}
    books: set[str] = set()
    for quote in quotes:
        books.add(quote["bookmaker"])
        selection = quote["selection"]
        incumbent = best_by_selection.get(selection)
        if incumbent is None or _better_price(quote["_odds"], incumbent["_odds"]):
            best_by_selection[selection] = quote

    selections = sorted(best_by_selection.values(), key=lambda entry: entry["selection"])
    implied_values = [entry["_implied"] for entry in selections]
    overround: Decimal | None = None
    no_vig: list[Decimal | None] = [None] * len(selections)
    devig_method: str | None = None
    devig_disagreement: Decimal | None = None
    if len(selections) >= 2 and all(value is not None for value in implied_values):
        total = sum(implied_values, Decimal(0))
        if total > 0:
            overround = total - Decimal(1)
            # Shin removes proportionally more margin from longshots than
            # proportional normalization does, which is the direction the
            # favourite-longshot literature supports. The disagreement across
            # methods is published alongside it: on skewed markets it can exceed
            # a candidate edge, and an "edge" smaller than it is a statement
            # about the de-vig assumption rather than about the game.
            try:
                result = remove_margin(implied_values, method=DEFAULT_DEVIG_METHOD)
                no_vig = list(result.probabilities)
                devig_method = result.method
                devig_disagreement = method_disagreement(implied_values)
            except (ValueError, ArithmeticError):
                no_vig = [value / total for value in implied_values]
                devig_method = "multiplicative"

    priced_selections = []
    for entry, fair in zip(selections, no_vig, strict=True):
        matching = [quote for quote in quotes if quote["selection"] == entry["selection"]]
        worst = min(matching, key=lambda quote: quote["_odds"])
        # What shopping is worth: the implied probability a bettor stops paying by
        # taking the best posted price instead of the worst one.
        shopping_gain = None
        if worst["_implied"] is not None and entry["_implied"] is not None:
            shopping_gain = worst["_implied"] - entry["_implied"]
        priced_selections.append(
            {
                "selection": entry["selection"],
                "line": entry["line"],
                "best_odds": entry["odds"],
                "best_bookmaker": entry["bookmaker"],
                "worst_odds": worst["odds"],
                "worst_bookmaker": worst["bookmaker"],
                "line_shopping_gain_probability": _probability_text(shopping_gain),
                "odds_format": entry["odds_format"],
                "implied_probability": entry["implied_probability"],
                "no_vig_probability": _probability_text(fair),
                "quoted_by": sorted({quote["bookmaker"] for quote in matching}),
                "quote_count": len(matching),
                "odds_timestamp": entry["odds_timestamp"],
                "api_fetched_at": entry["api_fetched_at"],
                "source_snapshot_hash": entry["source_snapshot_hash"],
            }
        )

    return {
        "market_type": market_type,
        "line": _decimal_text(line),
        "bookmakers": sorted(books),
        "bookmaker_count": len(books),
        "overround": _probability_text(overround),
        "no_vig_available": overround is not None,
        "no_vig_method": devig_method,
        "no_vig_method_disagreement": _probability_text(devig_disagreement),
        "selections": priced_selections,
    }


def _build_events(rows: list[DatabaseRow], *, now: datetime) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        event_id = str(row["event_id"])
        event = grouped.get(event_id)
        if event is None:
            start_time = row["game_start_time"]
            event = grouped[event_id] = {
                "event_id": event_id,
                "sport": str(row["sport"]),
                "league": str(row["league"]),
                "home_team": str(row["home_team"]),
                "away_team": str(row["away_team"]),
                "game_start_time": _iso(start_time),
                "_start": start_time,
                "_markets": {},
            }
        market_type = str(row["market_type"])
        key = (market_type, _line_group(market_type, row["line"]))
        event["_markets"].setdefault(key, []).append(_selection_entry(row))

    events: list[dict[str, Any]] = []
    for event in grouped.values():
        start_time = event.pop("_start")
        markets_by_key: dict[tuple[str, Any], list[dict[str, Any]]] = event.pop("_markets")
        markets = [
            _build_market(market_type=market_type, line=line, quotes=quotes)
            for (market_type, line), quotes in markets_by_key.items()
        ]
        markets.sort(key=lambda market: (_market_sort_key(market["market_type"]), market["market_type"], market["line"] or ""))
        seconds_to_start = int((start_time - now).total_seconds()) if start_time else None
        events.append(
            {
                **event,
                "seconds_to_start": seconds_to_start,
                "market_count": len(markets),
                "markets": markets,
            }
        )
    events.sort(key=lambda event: (event["game_start_time"] or "", event["event_id"]))
    return events


def _board_state(
    *,
    events: list[dict[str, Any]],
    latest_source_fetched_at: datetime | None,
    source_health: list[dict[str, Any]],
    now: datetime,
    stale_after_seconds: int,
) -> tuple[str, str]:
    """Name the board's condition explicitly; a stale cache is never 'fresh'."""
    blocked = [entry for entry in source_health if entry["freshness_state"] in {"blocked", "failed"}]
    if blocked:
        reason = blocked[0]["last_error"] or blocked[0]["freshness_state"]
        return "blocked", f"sports_source_{blocked[0]['freshness_state']}:{reason}"
    if latest_source_fetched_at is None:
        return "unavailable", "no_sports_rows_uploaded"
    age_seconds = (now - latest_source_fetched_at).total_seconds()
    if age_seconds > stale_after_seconds:
        return "stale", f"sports_source_older_than_{stale_after_seconds}s"
    if not events:
        return "empty", "no_upcoming_events_with_posted_odds"
    return "fresh", "sports_source_within_freshness_window"


def load_sports_board(
    *,
    settings: DatabaseSettings | None = None,
    now: datetime | str | None = None,
    max_events: int = DEFAULT_MAX_EVENTS,
    stale_after_seconds: int = BOARD_STALE_SECONDS,
) -> dict[str, Any]:
    """Build the current sports board from rows already uploaded to PostgreSQL."""
    configured = ensure_database_ready(settings)
    moment = _now(now)
    bounded_events = max(1, min(int(max_events), 500))
    with connection_pool(configured).connection() as connection:
        rows = _rows_for_board(connection, now=moment, max_events=bounded_events)
        latest_fetched = _latest_upload_time(connection)
        source_health = _source_health(connection)
        worker = _worker_state(connection)

    events = _build_events(rows, now=moment)
    state, reason = _board_state(
        events=events,
        latest_source_fetched_at=latest_fetched,
        source_health=source_health,
        now=moment,
        stale_after_seconds=stale_after_seconds,
    )
    is_current = state == "fresh"
    return {
        "asset_class": "sports",
        "generated_at": moment.isoformat(),
        "board_state": state,
        "state_reason": reason,
        "is_current": is_current,
        "stale_after_seconds": stale_after_seconds,
        "latest_source_fetched_at": _iso(latest_fetched),
        "source_age_seconds": int((moment - latest_fetched).total_seconds()) if latest_fetched else None,
        "events": events if is_current else [],
        "withheld_event_count": 0 if is_current else len(events),
        "event_count": len(events) if is_current else 0,
        "quote_count": len(rows) if is_current else 0,
        "source_health": source_health,
        "worker": worker,
        "model_state": "baseline_only",
        "decision_status": "track_only",
        "probability_source": "bookmaker_implied",
        "disclaimer": (
            "No-vig probabilities and best available prices are observations of posted "
            "bookmaker markets. They are a baseline, not a validated model edge, and "
            "never a betting recommendation."
        ),
    }


def summarize_sports_board(board: Mapping[str, Any]) -> dict[str, Any]:
    """Compact counters for status panels that should not embed the full board."""
    events = board.get("events") or []
    market_count = sum(int(event.get("market_count") or 0) for event in events)
    no_vig_markets = sum(
        1
        for event in events
        for market in event.get("markets") or []
        if market.get("no_vig_available")
    )
    multi_book_markets = sum(
        1
        for event in events
        for market in event.get("markets") or []
        if int(market.get("bookmaker_count") or 0) > 1
    )
    disagreements = [
        Decimal(str(market.get("no_vig_method_disagreement")))
        for event in events
        for market in event.get("markets") or []
        if market.get("no_vig_method_disagreement") is not None
    ]
    next_event = events[0] if events else None
    return {
        "board_state": board.get("board_state"),
        "state_reason": board.get("state_reason"),
        "is_current": bool(board.get("is_current")),
        "event_count": len(events),
        "market_count": market_count,
        "no_vig_market_count": no_vig_markets,
        "no_vig_method": DEFAULT_DEVIG_METHOD,
        "max_no_vig_method_disagreement": None if not disagreements else format(max(disagreements), "f"),
        "line_shopping_market_count": multi_book_markets,
        "latest_source_fetched_at": board.get("latest_source_fetched_at"),
        "source_age_seconds": board.get("source_age_seconds"),
        "next_event": None
        if next_event is None
        else {
            "event_id": next_event.get("event_id"),
            "league": next_event.get("league"),
            "home_team": next_event.get("home_team"),
            "away_team": next_event.get("away_team"),
            "game_start_time": next_event.get("game_start_time"),
        },
    }
