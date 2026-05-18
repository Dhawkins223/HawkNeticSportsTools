from __future__ import annotations

from app.database import execute, get_connection
from app.database import EXPECTED_TABLES, database_readiness, init_db, reset_db


def test_init_db_creates_expected_tables() -> None:
    reset_db()
    readiness = database_readiness()
    assert readiness["missing_expected_tables"] == []
    assert readiness["table_count"] >= len(EXPECTED_TABLES)


def test_database_readiness_reports_key_tables() -> None:
    reset_db()
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
    reset_db()
    readiness = database_readiness()
    assert readiness["dashboard_ready"] is False
    assert readiness["blocking_reasons"]
    assert readiness["table_status"]["historical_games"]["status"] in {"empty", "below_minimum"}
    assert readiness["historical_coverage_status"]["coverage_ready"] is False


def test_database_readiness_missing_table_is_blocking() -> None:
    reset_db()
    with get_connection() as conn:
        execute(conn, "DROP TABLE bdl_games")
    readiness = database_readiness()
    assert readiness["dashboard_ready"] is False
    assert readiness["table_status"]["bdl_games"]["status"] == "missing"
    assert any("Missing required table: bdl_games" in reason for reason in readiness["blocking_reasons"])


def test_database_readiness_threshold_override(monkeypatch) -> None:
    reset_db()
    monkeypatch.setenv("HAWKNETIC_MIN_DATA_QUALITY_REPORTS", "1000")
    readiness = database_readiness()
    assert readiness["table_status"]["data_quality_reports"]["required_minimum"] == 1000
    assert readiness["table_status"]["data_quality_reports"]["status"] in {"below_minimum", "empty"}


def test_historical_coverage_missing_seasons_reported() -> None:
    reset_db()
    with get_connection() as conn:
        execute(conn, "INSERT INTO historical_games(external_id, season, game_date) VALUES('g-2000-coverage-test', 2000, '2000-01-01')")
    readiness = database_readiness()
    coverage = readiness["historical_coverage_status"]
    assert coverage["coverage_ready"] is False
    assert 2000 in coverage["seasons_present"]
    assert 1996 in coverage["missing_seasons"]
    assert 2026 in coverage["missing_seasons"]


def test_historical_coverage_range_override(monkeypatch) -> None:
    reset_db()
    monkeypatch.setenv("HAWKNETIC_HISTORICAL_START_SEASON", "2020")
    monkeypatch.setenv("HAWKNETIC_HISTORICAL_END_SEASON", "2021")
    readiness = database_readiness()
    coverage = readiness["historical_coverage_status"]
    assert coverage["expected_start_season"] == 2020
    assert coverage["expected_end_season"] == 2021
    assert coverage["missing_seasons"] == [2020, 2021]


def test_dashboard_not_ready_when_coverage_not_ready() -> None:
    reset_db()
    with get_connection() as conn:
        execute(conn, "INSERT INTO bdl_games(bdl_game_id, raw_json) VALUES(1, '{}')")
        execute(conn, "INSERT INTO bdl_teams(bdl_team_id, raw_json) VALUES(1, '{}')")
        execute(conn, "INSERT INTO bdl_players(bdl_player_id, raw_json) VALUES(1, '{}')")
        execute(conn, "INSERT INTO odds(market, selection) VALUES('spread', 'A')")
        execute(conn, "INSERT INTO props(market) VALUES('points')")
        execute(conn, "INSERT INTO simulations(result_json) VALUES('{}')")
        execute(conn, "INSERT INTO historical_teams(full_name) VALUES('Team A')")
        execute(conn, "INSERT INTO historical_players(full_name) VALUES('Player A')")
        execute(conn, "INSERT INTO historical_games(external_id, season, game_date) VALUES('g-2020', 2020, '2020-01-01')")
    readiness = database_readiness()
    assert readiness["historical_coverage_status"]["coverage_ready"] is False
    assert readiness["dashboard_ready"] is False
