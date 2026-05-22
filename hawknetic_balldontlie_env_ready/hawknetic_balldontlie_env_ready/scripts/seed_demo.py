"""Seed demo data into HawkNetic SQLite so the dashboard has games, props and odds.

Idempotent: skips inserts where rows with the same key already exist.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from datetime import date, timedelta

DB = Path("/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/data/hawknetic.sqlite")

TEAMS = [
    ("LAL", "Los Angeles", "Lakers", "Los Angeles Lakers", "West", "Pacific"),
    ("BOS", "Boston", "Celtics", "Boston Celtics", "East", "Atlantic"),
    ("GSW", "Golden State", "Warriors", "Golden State Warriors", "West", "Pacific"),
    ("MIA", "Miami", "Heat", "Miami Heat", "East", "Southeast"),
    ("DEN", "Denver", "Nuggets", "Denver Nuggets", "West", "Northwest"),
    ("MIL", "Milwaukee", "Bucks", "Milwaukee Bucks", "East", "Central"),
    ("PHI", "Philadelphia", "76ers", "Philadelphia 76ers", "East", "Atlantic"),
    ("DAL", "Dallas", "Mavericks", "Dallas Mavericks", "West", "Southwest"),
]

PLAYERS = [
    ("LeBron", "James", "F", 1),
    ("Anthony", "Davis", "F-C", 1),
    ("Jayson", "Tatum", "F", 2),
    ("Jaylen", "Brown", "G-F", 2),
    ("Stephen", "Curry", "G", 3),
    ("Jimmy", "Butler", "F", 4),
    ("Nikola", "Jokic", "C", 5),
    ("Giannis", "Antetokounmpo", "F", 6),
    ("Joel", "Embiid", "C", 7),
    ("Luka", "Doncic", "G", 8),
]

# (home_team_id, away_team_id, days_from_today)
GAMES = [
    (1, 2, 0), (3, 4, 0), (5, 6, 0),
    (7, 8, 1), (1, 3, 1), (2, 4, 2), (5, 7, 2),
]

MARKETS = [
    # (game_idx, player_idx_or_None, market, line, over_odds, under_odds, model_prob, ev, tier)
    (1, None, "Moneyline", None, -135, +115, 0.61, 0.04, "HIGH"),
    (1, None, "Spread -3.5", -3.5, -110, -110, 0.55, 0.02, "MEDIUM"),
    (1, None, "Total 224.5", 224.5, -110, -110, 0.54, 0.01, "MEDIUM"),
    (1, 1, "Points (LeBron James)", 25.5, -115, -105, 0.58, 0.07, "HIGH"),
    (1, 2, "Rebounds (Anthony Davis)", 11.5, -120, +100, 0.60, 0.09, "HIGH"),
    (1, 3, "Points (Jayson Tatum)", 28.5, -110, -110, 0.52, 0.01, "LOW"),
    (2, None, "Moneyline", None, -150, +130, 0.63, 0.05, "HIGH"),
    (2, 5, "Threes Made (Stephen Curry)", 4.5, -130, +110, 0.59, 0.06, "MEDIUM"),
    (2, 6, "Assists (Jimmy Butler)", 5.5, -110, -110, 0.57, 0.04, "MEDIUM"),
    (3, None, "Total 232.5", 232.5, -110, -110, 0.53, 0.01, "LOW"),
    (3, 7, "Points (Nikola Jokic)", 27.5, -115, -105, 0.61, 0.08, "HIGH"),
    (3, 8, "Rebounds (Giannis)", 12.5, -125, +105, 0.62, 0.10, "HIGH"),
    (4, None, "Spread +2.5", 2.5, -110, -110, 0.51, 0.00, "FRAGILE"),
    (4, 9, "Points (Joel Embiid)", 30.5, -120, +100, 0.56, 0.03, "MEDIUM"),
    (4, 10, "Triple-Double (Luka)", None, +180, -220, 0.40, 0.02, "MEDIUM"),
    # Tomorrow & day-after games (5, 6, 7) so the default view is populated
    (5, None, "Moneyline", None, -120, +100, 0.55, 0.03, "MEDIUM"),
    (5, 1, "Points (LeBron James)", 26.5, -110, -110, 0.56, 0.05, "MEDIUM"),
    (5, 5, "Threes Made (Stephen Curry)", 5.5, +120, -140, 0.48, -0.02, "LOW"),
    (6, None, "Moneyline", None, -160, +140, 0.65, 0.06, "HIGH"),
    (6, None, "Total 218.5", 218.5, -108, -112, 0.53, 0.01, "MEDIUM"),
    (6, 3, "Points (Jayson Tatum)", 29.5, -115, -105, 0.59, 0.07, "HIGH"),
    (6, 6, "Points (Jimmy Butler)", 22.5, -110, -110, 0.54, 0.02, "MEDIUM"),
    (7, None, "Moneyline", None, +110, -130, 0.45, -0.01, "FRAGILE"),
    (7, 7, "Points (Nikola Jokic)", 28.5, -120, +100, 0.62, 0.09, "HIGH"),
    (7, 9, "Rebounds (Joel Embiid)", 10.5, -115, -105, 0.58, 0.05, "MEDIUM"),
]

ODDS_ROWS = [
    # (game_idx, market, selection, american_odds)
    (1, "moneyline", "Boston Celtics", -135),
    (1, "moneyline", "Los Angeles Lakers", +115),
    (2, "moneyline", "Golden State Warriors", -150),
    (2, "moneyline", "Miami Heat", +130),
    (3, "spread", "Denver Nuggets -4.5", -110),
    (3, "spread", "Milwaukee Bucks +4.5", -110),
    (4, "total", "Over 224.5", -108),
    (4, "total", "Under 224.5", -112),
]


def seed():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # Teams
    for idx, (abbr, city, name, full, conf, div) in enumerate(TEAMS, start=1):
        cur.execute("SELECT id FROM historical_teams WHERE abbreviation = ?", (abbr,))
        if cur.fetchone():
            continue
        cur.execute(
            """INSERT INTO historical_teams
               (id, external_id, abbreviation, city, name, full_name, conference, division, active, team_key, source)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (idx, f"seed-team-{idx}", abbr, city, name, full, conf, div, 1, full.lower().replace(" ", "-"), "seed"),
        )

    # Players
    for idx, (first, last, pos, team_id) in enumerate(PLAYERS, start=1):
        cur.execute("SELECT id FROM historical_players WHERE id = ?", (idx,))
        if cur.fetchone():
            continue
        cur.execute(
            """INSERT INTO historical_players
               (id, external_id, first_name, last_name, full_name, position, active, player_key, source)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (idx, f"seed-player-{idx}", first, last, f"{first} {last}", pos, 1, f"{first}-{last}".lower(), "seed"),
        )

    # Games
    for idx, (home_id, away_id, day_offset) in enumerate(GAMES, start=1):
        cur.execute("SELECT id FROM historical_games WHERE id = ?", (idx,))
        if cur.fetchone():
            continue
        game_date = (date.today() + timedelta(days=day_offset)).isoformat()
        cur.execute(
            """INSERT INTO historical_games
               (id, external_id, season, game_date, home_team_id, away_team_id, home_score, away_score, status, source, game_key)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (idx, f"seed-game-{idx}", 2026, game_date, home_id, away_id, None, None,
             "scheduled" if day_offset >= 0 else "final", "seed", f"seed-game-{idx}"),
        )

    # Props
    cur.execute("DELETE FROM props WHERE source = 'seed'")
    for game_idx, player_idx, market, line, over, under, prob, ev, tier in MARKETS:
        cur.execute(
            """INSERT INTO props
               (game_id, player_id, market, line, over_odds, under_odds, model_probability, expected_value, confidence_tier, source)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (game_idx, player_idx, market, line, over, under, prob, ev, tier, "seed"),
        )

    # Odds
    cur.execute("DELETE FROM odds WHERE sportsbook = 'seed'")
    for game_idx, market, selection, odds_val in ODDS_ROWS:
        implied = 100 / (odds_val + 100) if odds_val > 0 else abs(odds_val) / (abs(odds_val) + 100)
        cur.execute(
            """INSERT INTO odds (game_id, sportsbook, market, selection, odds_value, implied_probability)
               VALUES (?,?,?,?,?,?)""",
            (game_idx, "seed", market, selection, odds_val, round(implied, 4)),
        )

    conn.commit()
    print("Seed complete.")
    for table in ("historical_teams", "historical_players", "historical_games", "props", "odds"):
        cur.execute(f"SELECT COUNT(*) AS c FROM {table}")
        print(f"  {table}: {cur.fetchone()['c']} rows")
    conn.close()


if __name__ == "__main__":
    seed()
