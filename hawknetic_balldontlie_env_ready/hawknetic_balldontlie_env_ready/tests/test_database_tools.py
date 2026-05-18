from __future__ import annotations

from app.database import execute, get_connection
from app.database import EXPECTED_TABLES, database_readiness, init_db, reset_db
from scripts.historical_backfill import parse_args


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


def test_historical_backfill_parse_args_season() -> None:
    args = parse_args(["--season", "2024", "--sleep-seconds", "3"])
    assert args.season == 2024
    assert args.sleep_seconds == 3


def test_historical_backfill_job_table_exists_after_init() -> None:
    reset_db()
    with get_connection() as conn:
        row = execute(conn, "SELECT 1 AS ok FROM sqlite_master WHERE type = 'table' AND name = 'historical_backfill_jobs'").fetchone()
    assert row is not None


def test_historical_backfill_job_insert_update() -> None:
    reset_db()
    with get_connection() as conn:
        cur = execute(conn, """
            INSERT INTO historical_backfill_jobs(season, mode, status, started_at)
            VALUES(2024, 'scrape_import', 'running', '2026-01-01T00:00:00+00:00')
        """)
        job_id = int(cur.lastrowid)
        execute(conn, """
            UPDATE historical_backfill_jobs
               SET status = 'completed',
                   finished_at = '2026-01-01T00:10:00+00:00',
                   games_count = 1230,
                   players_count = 500,
                   teams_count = 30,
                   player_game_stats_count = 30000,
                   team_game_stats_count = 2460
             WHERE id = ?
        """, (job_id,))
        row = execute(conn, "SELECT * FROM historical_backfill_jobs WHERE id = ?", (job_id,)).fetchone()
    assert row is not None
    assert row["status"] == "completed"
    assert int(row["games_count"]) == 1230


def test_readiness_includes_historical_backfill_job_summary() -> None:
    reset_db()
    with get_connection() as conn:
        execute(conn, """
            INSERT INTO historical_backfill_jobs(season, mode, status, started_at, finished_at, games_count)
            VALUES(2024, 'scrape_import', 'completed', '2026-01-01T00:00:00+00:00', '2026-01-01T00:05:00+00:00', 1230)
        """)
        execute(conn, """
            INSERT INTO historical_backfill_jobs(season, mode, status, started_at, finished_at, error_message)
            VALUES(2025, 'scrape_import', 'failed', '2026-01-02T00:00:00+00:00', '2026-01-02T00:03:00+00:00', 'network')
        """)
    readiness = database_readiness()
    summary = readiness["historical_backfill_jobs"]
    assert summary is not None
    assert 2024 in summary["completed_seasons"]
    assert 2025 in summary["failed_seasons"]
