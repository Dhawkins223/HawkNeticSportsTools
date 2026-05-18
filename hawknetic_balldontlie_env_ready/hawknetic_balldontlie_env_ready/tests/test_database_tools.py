from __future__ import annotations

from app.database import execute, get_connection
from app.database import EXPECTED_TABLES, database_readiness, init_db


def test_init_db_creates_expected_tables() -> None:
    init_db()
    readiness = database_readiness()
    assert readiness["missing_expected_tables"] == []
    assert readiness["table_count"] >= len(EXPECTED_TABLES)


def test_database_readiness_reports_key_tables() -> None:
    init_db()
    readiness = database_readiness()
    assert readiness["database_url_present"] in {True, False}
    for table in (
        "historical_teams",
        "historical_players",
        "historical_games",
        "historical_player_game_stats",
        "historical_team_game_stats",
        "bdl_teams",
        "bdl_players",
        "bdl_games",
        "bdl_ingestion_logs",
        "odds",
        "props",
        "simulations",
        "parlays",
        "parlay_legs",
        "data_quality_reports",
    ):
        assert table in readiness["row_counts"]


def test_database_readiness_empty_db_not_dashboard_ready() -> None:
    init_db()
    readiness = database_readiness()
    assert readiness["dashboard_ready"] is False
    assert readiness["blocking_reasons"]
    assert readiness["table_status"]["historical_games"]["status"] in {"empty", "below_minimum"}


def test_database_readiness_missing_table_is_blocking() -> None:
    init_db()
    with get_connection() as conn:
        execute(conn, "DROP TABLE bdl_games")
    readiness = database_readiness()
    assert readiness["dashboard_ready"] is False
    assert readiness["table_status"]["bdl_games"]["status"] == "missing"
    assert any("Missing required table: bdl_games" in reason for reason in readiness["blocking_reasons"])


def test_database_readiness_threshold_override(monkeypatch) -> None:
    init_db()
    monkeypatch.setenv("HAWKNETIC_MIN_DATA_QUALITY_REPORTS", "1000")
    readiness = database_readiness()
    assert readiness["table_status"]["data_quality_reports"]["required_minimum"] == 1000
    assert readiness["table_status"]["data_quality_reports"]["status"] in {"below_minimum", "empty"}
