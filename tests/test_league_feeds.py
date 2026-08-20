from __future__ import annotations

import unittest
from decimal import Decimal

from kalshi_research_bot.connectors.league_feeds import (
    normalize_mlb_schedule,
    normalize_nhl_scores,
    probe_league_feed,
    render_league_probe,
)


def _mlb_game(
    game_pk: int = 745804,
    *,
    coded_state: str = "F",
    home_score: object = 5,
    away_score: object = 3,
    game_date: str = "2026-04-12T23:10:00Z",
) -> dict:
    return {
        "gamePk": game_pk,
        "gameDate": game_date,
        "status": {"codedGameState": coded_state, "detailedState": "Final"},
        "teams": {
            "home": {"team": {"name": "Seattle Mariners"}, "score": home_score},
            "away": {"team": {"name": "Texas Rangers"}, "score": away_score},
        },
    }


def _mlb_payload(*games: dict) -> dict:
    return {"dates": [{"date": "2026-04-12", "games": list(games)}]}


def _nhl_game(
    game_id: int = 2025020123,
    *,
    state: str = "FINAL",
    home_score: object = 4,
    away_score: object = 2,
    start: str = "2026-01-15T00:00:00Z",
) -> dict:
    return {
        "id": game_id,
        "gameState": state,
        "startTimeUTC": start,
        "homeTeam": {"abbrev": "SEA", "name": {"default": "Seattle Kraken"}, "score": home_score},
        "awayTeam": {"abbrev": "VAN", "name": {"default": "Vancouver Canucks"}, "score": away_score},
    }


class MlbScheduleTests(unittest.TestCase):
    def test_a_final_game_becomes_a_result(self) -> None:
        result = normalize_mlb_schedule(_mlb_payload(_mlb_game()), api_fetched_at="2026-04-13T02:00:00+00:00")

        self.assertEqual(len(result.games), 1)
        game = result.games[0]
        self.assertEqual(game.event_id, "mlb_745804")
        self.assertEqual(game.league, "mlb")
        self.assertEqual(game.home_team, "Seattle Mariners")
        self.assertEqual(game.home_score, Decimal("5"))
        self.assertEqual(game.home_win, 1)
        self.assertEqual(result.rejections, {})

    def test_a_postponed_game_is_refused_by_name_not_read_as_nil_nil(self) -> None:
        """The reason to use the league's own feed is that it says which is which."""
        result = normalize_mlb_schedule(
            _mlb_payload(
                _mlb_game(1, coded_state="D", home_score=None, away_score=None),
                _mlb_game(2, coded_state="I", home_score=2, away_score=1),
                _mlb_game(3),
            )
        )
        self.assertEqual([game.event_id for game in result.games], ["mlb_3"])
        self.assertEqual(result.rejections, {"not_final:D": 1, "not_final:I": 1})

    def test_a_final_game_missing_a_score_is_refused(self) -> None:
        result = normalize_mlb_schedule(_mlb_payload(_mlb_game(home_score=None)))
        self.assertEqual(result.games, [])
        self.assertEqual(result.rejections, {"missing_score": 1})

    def test_an_unusable_start_time_is_refused_rather_than_defaulted(self) -> None:
        result = normalize_mlb_schedule(_mlb_payload(_mlb_game(game_date="not-a-date")))
        self.assertEqual(result.games, [])
        self.assertEqual(result.rejections, {"missing_start_time": 1})

    def test_a_payload_without_dates_says_so(self) -> None:
        result = normalize_mlb_schedule({"totalGames": 0})
        self.assertEqual(result.games, [])
        self.assertEqual(result.rejections, {"no_dates_in_payload": 1})

    def test_games_come_back_in_start_order(self) -> None:
        result = normalize_mlb_schedule(
            _mlb_payload(
                _mlb_game(2, game_date="2026-04-12T23:10:00Z"),
                _mlb_game(1, game_date="2026-04-12T17:05:00Z"),
            )
        )
        self.assertEqual([game.event_id for game in result.games], ["mlb_1", "mlb_2"])


class NhlScoreTests(unittest.TestCase):
    def test_a_final_game_becomes_a_result(self) -> None:
        result = normalize_nhl_scores({"games": [_nhl_game()]})

        self.assertEqual(len(result.games), 1)
        game = result.games[0]
        self.assertEqual(game.event_id, "nhl_2025020123")
        self.assertEqual(game.home_team, "Seattle Kraken")
        self.assertEqual(game.away_team, "Vancouver Canucks")
        self.assertEqual(game.home_score, Decimal("4"))

    def test_an_in_progress_game_is_refused(self) -> None:
        result = normalize_nhl_scores({"games": [_nhl_game(state="LIVE")]})
        self.assertEqual(result.games, [])
        self.assertEqual(result.rejections, {"not_final:LIVE": 1})

    def test_a_team_name_nested_under_a_language_map_is_read(self) -> None:
        result = normalize_nhl_scores({"games": [_nhl_game()]})
        self.assertEqual(result.games[0].home_team, "Seattle Kraken")

    def test_a_team_with_only_an_abbreviation_still_resolves(self) -> None:
        game = _nhl_game()
        del game["homeTeam"]["name"]
        result = normalize_nhl_scores({"games": [game]})
        self.assertEqual(result.games[0].home_team, "SEA")

    def test_a_payload_without_games_says_so(self) -> None:
        result = normalize_nhl_scores({"currentDate": "2026-01-15"})
        self.assertEqual(result.games, [])
        self.assertEqual(result.rejections, {"no_games_in_payload": 1})


class LeagueProbeTests(unittest.TestCase):
    class _Response:
        status = 200
        fetched_at = "2026-04-13T02:00:00+00:00"

        def __init__(self, payload: dict) -> None:
            self._payload = payload

        def json(self) -> dict:
            return self._payload

    def test_the_probe_reports_what_the_normalizer_made_of_a_live_response(self) -> None:
        class _Client:
            def get_text(self, url: str, timeout: int = 20):
                return LeagueProbeTests._Response(_mlb_payload(_mlb_game(), _mlb_game(2, coded_state="D")))

        report = probe_league_feed("mlb", client=_Client(), date="2026-04-12")
        self.assertTrue(report["reachable"])
        self.assertEqual(report["finished_games"], 1)
        self.assertEqual(report["rejection_reasons"], {"not_final:D": 1})
        self.assertEqual(report["sample_game"]["home_team"], "Seattle Mariners")
        self.assertIn("Seattle Mariners", render_league_probe(report))

    def test_an_unreachable_feed_is_reported_not_raised(self) -> None:
        class _Client:
            def get_text(self, url: str, timeout: int = 20):
                raise OSError("connection refused")

        report = probe_league_feed("nhl", client=_Client(), date="2026-01-15")
        self.assertFalse(report["reachable"])
        self.assertEqual(report["error"], "OSError")
        self.assertIn("unreachable", render_league_probe(report))

    def test_an_unsupported_league_is_refused(self) -> None:
        report = probe_league_feed("cricket")
        self.assertFalse(report["reachable"])
        self.assertEqual(report["error"], "unsupported_league")
