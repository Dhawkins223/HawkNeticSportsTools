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
