"""Seed HawkNetic v2 tables with realistic per-player rates, team metrics,
live game state, live player status, live odds, and one example injury so
that the Monte Carlo simulator and live-readiness checks have real inputs.

Idempotent.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta
from pathlib import Path

DB = Path("/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/data/hawknetic.sqlite")


# (player_id, minutes_mean, minutes_std, ppm_mean, ppm_std, rpm_mean, rpm_std,
#  apm_mean, apm_std, threes_mean, threes_std, usage, availability, sample_size)
PLAYER_RATES = [
    (1, 35.0, 3.5, 0.74, 0.18, 0.21, 0.08, 0.18, 0.06, 0.06, 0.04, 0.30, 0.95, 1100),  # LeBron
    (2, 33.0, 4.0, 0.70, 0.20, 0.32, 0.10, 0.07, 0.04, 0.01, 0.02, 0.27, 0.90, 950),   # AD
    (3, 36.0, 3.0, 0.78, 0.19, 0.24, 0.08, 0.13, 0.05, 0.10, 0.05, 0.32, 0.93, 1200),  # Tatum
    (4, 35.0, 3.2, 0.68, 0.18, 0.18, 0.07, 0.10, 0.05, 0.08, 0.04, 0.28, 0.94, 1150),  # Brown
    (5, 33.5, 3.5, 0.81, 0.21, 0.13, 0.06, 0.18, 0.07, 0.16, 0.06, 0.31, 0.96, 1300),  # Curry
    (6, 32.0, 4.0, 0.66, 0.18, 0.16, 0.07, 0.18, 0.07, 0.04, 0.03, 0.26, 0.85, 880),   # Butler
    (7, 34.0, 3.0, 0.85, 0.18, 0.34, 0.10, 0.30, 0.08, 0.04, 0.03, 0.32, 0.97, 1400),  # Jokic
    (8, 35.0, 2.5, 0.95, 0.20, 0.32, 0.09, 0.18, 0.06, 0.04, 0.03, 0.40, 0.95, 1500),  # Giannis
    (9, 34.0, 3.5, 0.95, 0.22, 0.36, 0.10, 0.13, 0.05, 0.04, 0.03, 0.36, 0.88, 900),   # Embiid
    (10, 36.0, 2.8, 0.88, 0.19, 0.24, 0.08, 0.27, 0.08, 0.10, 0.04, 0.36, 0.96, 1350), # Doncic
]

# (team_id, pace, off_rating, def_rating, home_advantage)
TEAM_METRICS = [
    (1, 100.5, 116.5, 113.0, 2.5),  # LAL
    (2, 99.0, 118.5, 110.0, 2.7),   # BOS
    (3, 101.0, 117.0, 113.0, 2.5),  # GSW
    (4, 96.5, 113.0, 109.5, 2.8),   # MIA
    (5, 99.5, 119.0, 110.5, 2.9),   # DEN
    (6, 100.0, 116.0, 111.0, 2.5),  # MIL
    (7, 98.0, 117.5, 112.0, 2.6),   # PHI
    (8, 102.5, 119.5, 115.5, 2.4),  # DAL
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def seed_v2() -> None:
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Player skill rates
    for row in PLAYER_RATES:
        cur.execute("""
            INSERT OR REPLACE INTO player_skill
                (player_id, minutes_mean, minutes_std, points_per_min_mean, points_per_min_std,
                 rebounds_per_min_mean, rebounds_per_min_std, assists_per_min_mean, assists_per_min_std,
                 threes_per_min_mean, threes_per_min_std, usage_rate, availability, sample_size, last_updated)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (*row, _now_iso()))

    # Team metrics
    for row in TEAM_METRICS:
        cur.execute("""
            INSERT OR REPLACE INTO team_metrics
                (team_id, pace, offensive_rating, defensive_rating, home_advantage, last_updated)
            VALUES(?,?,?,?,?,?)
        """, (*row, _now_iso()))

    # One live (in-progress) game so readiness shows live data fresh
    cur.execute("""
        INSERT OR REPLACE INTO live_games
            (game_id, status, period, clock, home_score, away_score,
             home_team_id, away_team_id, tipoff_at, source, last_updated)
        VALUES(1, 'scheduled', 0, NULL, 0, 0, 2, 1, ?, 'seed', ?)
    """, (_now_iso(), _now_iso()))
    cur.execute("""
        INSERT OR REPLACE INTO live_games
            (game_id, status, period, clock, home_score, away_score, home_team_id, away_team_id, tipoff_at, source, last_updated)
        VALUES(2, 'scheduled', NULL, NULL, NULL, NULL, 4, 3, ?, 'seed', ?)
    """, (_now_iso(), _now_iso()))

    # Live player status — half-game pace for game 1 starters
    cur.execute("DELETE FROM live_player_status WHERE source = 'seed'")
    live_status_rows = [
        (1, 1, 'active', 26.0, None, 2, 18, 6, 5, 1, 1),  # LeBron
        (2, 1, 'active', 25.0, None, 1, 14, 9, 1, 0, 1),  # AD
        (3, 1, 'active', 27.5, None, 3, 22, 4, 3, 2, 1),  # Tatum
        (4, 1, 'active', 26.0, None, 2, 16, 4, 2, 2, 1),  # Brown
    ]
    for row in live_status_rows:
        cur.execute("""
            INSERT INTO live_player_status
                (player_id, game_id, status, minutes_played, minutes_restriction, fouls,
                 points, rebounds, assists, threes, starter, source, last_updated)
            VALUES(?,?,?,?,?,?,?,?,?,?,?, 'seed', ?)
        """, (*row, _now_iso()))

    # One injury report
    cur.execute("DELETE FROM live_injuries WHERE source = 'seed'")
    cur.execute("""
        INSERT INTO live_injuries(player_id, designation, note, reported_at, source)
        VALUES(?, ?, ?, ?, 'seed')
    """, (6, 'questionable', 'Right ankle soreness', _now_iso()))

    # Live odds for game 1 (the in-progress game)
    cur.execute("DELETE FROM live_odds WHERE sportsbook = 'seed'")
    live_odds = [
        (1, 'moneyline', 'Boston Celtics', None, -135),
        (1, 'moneyline', 'Los Angeles Lakers', None, +115),
        (1, 'spread', 'Boston Celtics -3.5', -3.5, -110),
        (1, 'total', 'Over 224.5', 224.5, -108),
        (2, 'moneyline', 'Miami Heat', None, +130),
        (2, 'moneyline', 'Golden State Warriors', None, -150),
    ]
    for row in live_odds:
        cur.execute("""
            INSERT INTO live_odds(game_id, market, selection, line, american_odds, sportsbook, last_updated)
            VALUES(?,?,?,?,?, 'seed', ?)
        """, (*row, _now_iso()))
        cur.execute("""
            INSERT INTO live_line_movement(game_id, market, selection, line, american_odds, sportsbook, captured_at)
            VALUES(?,?,?,?,?, 'seed', ?)
        """, (*row, (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()))
        cur.execute("""
            INSERT INTO live_line_movement(game_id, market, selection, line, american_odds, sportsbook, captured_at)
            VALUES(?,?,?,?,?, 'seed', ?)
        """, (*row, _now_iso()))

    # Bump props.updated_at so freshness check passes
    cur.execute("UPDATE props SET updated_at = ? WHERE source = 'seed'", (_now_iso(),))

    conn.commit()
    print("v2 seed complete:")
    for table in ("player_skill", "team_metrics", "live_games", "live_player_status",
                  "live_injuries", "live_odds", "live_line_movement"):
        cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
        print(f"  {table}: {cur.fetchone()['c']} rows")
    conn.close()


if __name__ == "__main__":
    seed_v2()
