from __future__ import annotations

import unittest
from decimal import Decimal

from kalshi_research_bot.connectors.nflverse import (
    NFLVERSE_GAMES_URL,
    load_nflverse_games,
    normalize_nflverse_games,
    summarize_dataset,
)
from kalshi_research_bot.sports_board import american_implied_probability
from kalshi_research_bot.sports_ratings import EloConfig, grade_rating_program


HEADER = (
    "game_id,season,game_type,week,gameday,gametime,away_team,away_score,home_team,home_score,"
    "away_moneyline,home_moneyline,spread_line,total_line"
)


def _row(
    game_id: str,
    *,
    season: int = 2024,
    game_type: str = "REG",
    gameday: str = "2024-09-08",
    away: str = "BUF",
    home: str = "NE",
    away_score: str = "17",
    home_score: str = "24",
    away_moneyline: str = "150",
    home_moneyline: str = "-170",
) -> str:
    return (
        f"{game_id},{season},{game_type},1,{gameday},13:00,{away},{away_score},{home},{home_score},"
        f"{away_moneyline},{home_moneyline},-3.5,44.5"
    )


def _csv(*rows: str) -> str:
    return "\n".join((HEADER, *rows)) + "\n"


class NflverseNormalizationTests(unittest.TestCase):
    def test_a_played_game_with_both_closes_becomes_a_game_and_a_market_baseline(self) -> None:
        dataset = normalize_nflverse_games(_csv(_row("2024_01_BUF_NE")))

        self.assertEqual(len(dataset.games), 1)
        game = dataset.games[0]
        self.assertEqual(game.event_id, "2024_01_BUF_NE")
        self.assertEqual(game.league, "nfl")
        self.assertEqual(game.home_team, "NE")
        self.assertEqual(game.home_score, Decimal("24"))
        self.assertEqual(game.home_win, 1)

        probability = dataset.market_probabilities["2024_01_BUF_NE"]
        home_implied = american_implied_probability(Decimal("-170"))
        away_implied = american_implied_probability(Decimal("150"))
        # De-vigged, so strictly below the vigged implied price and above the
        # away side's.
        self.assertLess(probability, home_implied)
        self.assertGreater(probability, Decimal(1) - home_implied - (home_implied + away_implied - Decimal(1)))
        self.assertEqual(dataset.rejections, {})

    def test_an_unplayed_game_is_rejected_rather_than_scored_as_a_tie(self) -> None:
        dataset = normalize_nflverse_games(
            _csv(_row("2024_18_BUF_NE", away_score="", home_score=""))
        )
        self.assertEqual(dataset.games, [])
        self.assertEqual(dataset.rejections, {"no_final_score": 1})

    def test_a_game_without_a_closing_pair_still_trains_the_rating(self) -> None:
        """No market baseline is not the same as no game."""
        dataset = normalize_nflverse_games(
            _csv(_row("2001_01_BUF_NE", season=2001, away_moneyline="", home_moneyline=""))
        )
        self.assertEqual(len(dataset.games), 1)
        self.assertEqual(dataset.market_probabilities, {})
        self.assertEqual(dataset.rejections, {"no_closing_moneyline_pair": 1})

    def test_a_repeated_game_id_is_counted_not_double_loaded(self) -> None:
        dataset = normalize_nflverse_games(
            _csv(_row("2024_01_BUF_NE"), _row("2024_01_BUF_NE", home_score="31"))
        )
        self.assertEqual(len(dataset.games), 1)
        self.assertEqual(dataset.games[0].home_score, Decimal("24"))
        self.assertEqual(dataset.rejections, {"duplicate_game_id": 1})

    def test_a_file_missing_a_required_column_is_refused_outright(self) -> None:
        broken = "game_id,season,gameday,away_team,home_team\n2024_01_BUF_NE,2024,2024-09-08,BUF,NE\n"
        with self.assertRaisesRegex(ValueError, "nflverse_games_missing_columns"):
            normalize_nflverse_games(broken)

    def test_season_and_regular_season_filters_select_rows(self) -> None:
        content = _csv(
            _row("2023_01_BUF_NE", season=2023, gameday="2023-09-10"),
            _row("2024_01_BUF_NE", season=2024),
            _row("2024_21_BUF_NE", season=2024, game_type="SB", gameday="2025-02-09"),
        )
        both_seasons = normalize_nflverse_games(content)
        self.assertEqual(len(both_seasons.games), 3)

        one_season = normalize_nflverse_games(content, seasons=[2024])
        self.assertEqual([game.event_id for game in one_season.games], ["2024_01_BUF_NE", "2024_21_BUF_NE"])

        regular_only = normalize_nflverse_games(content, regular_season_only=True)
        self.assertEqual([game.event_id for game in regular_only.games], ["2023_01_BUF_NE", "2024_01_BUF_NE"])

    def test_games_are_ordered_by_start_and_the_hash_identifies_the_file(self) -> None:
        content = _csv(
            _row("2024_02_BUF_NE", gameday="2024-09-15"),
            _row("2024_01_BUF_NE", gameday="2024-09-08"),
        )
        dataset = normalize_nflverse_games(content)
        self.assertEqual(
            [game.event_id for game in dataset.games],
            ["2024_01_BUF_NE", "2024_02_BUF_NE"],
        )
        self.assertTrue(dataset.content_hash.startswith("sha256:"))
        self.assertEqual(dataset.content_hash, normalize_nflverse_games(content).content_hash)
        self.assertNotEqual(
            dataset.content_hash,
            normalize_nflverse_games(_csv(_row("2024_01_BUF_NE"))).content_hash,
        )
        self.assertIn(dataset.content_hash[:16].removeprefix("sha256:"), dataset.dataset_version())

    def test_evidence_states_that_this_is_not_collected_data(self) -> None:
        dataset = normalize_nflverse_games(_csv(_row("2024_01_BUF_NE")))
        evidence = summarize_dataset(dataset)
        self.assertFalse(evidence["collected_evidence"])
        self.assertEqual(evidence["source_url"], NFLVERSE_GAMES_URL)
        self.assertEqual(evidence["seasons"], {"2024": {"games": 1, "with_closing_market": 1}})

    def test_games_on_one_day_are_graded_as_one_slate(self) -> None:
        """The archive has no kickoff times, so a day is the finest safe grain."""
        content = _csv(
            _row("2024_01_A_B", away="A", home="B"),
            _row("2024_01_C_D", away="C", home="D"),
        )
        dataset = normalize_nflverse_games(content)
        self.assertEqual(
            {game.start_time for game in dataset.games},
            {dataset.games[0].start_time},
        )

    def test_the_archive_grades_through_the_same_program_as_collected_games(self) -> None:
        rows = []
        for week in range(1, 15):
            for away, home in (("BUF", "NE"), ("KC", "DEN")):
                # The home side wins every game, which any rating should learn.
                rows.append(
                    _row(
                        f"2024_{week:02d}_{away}_{home}",
                        gameday=f"2024-09-{week:02d}",
                        away=away,
                        home=home,
                        away_score="17",
                        home_score="24",
                    )
                )
        dataset = normalize_nflverse_games(_csv(*rows))
        report = grade_rating_program(
            dataset.games,
            dataset.market_probabilities,
            config=EloConfig(min_team_games=2),
            min_evaluated_games=10,
            excluded=dataset.rejections,
            source="nflverse_historical_archive",
            dataset_version=dataset.dataset_version(),
            league="nfl",
            market_baseline_name="devigged_reported_close",
        )
        self.assertEqual(report["source"], "nflverse_historical_archive")
        self.assertEqual(report["market_baseline"], "devigged_reported_close")
        self.assertEqual(report["model_state"], "track_only")
        self.assertIn("devigged_reported_close", report["metrics"])
        self.assertIn(report["decision"], {"accepted", "inconclusive", "rejected"})


class NflverseLiveProbeTests(unittest.TestCase):
    class _Response:
        status = 200
        fetched_at = "2026-08-20T19:00:00+00:00"
        from_cache = False
        stale = False
        stale_reason = ""

        def __init__(self, text: str) -> None:
            self.text = text

    def _client(self, **flags):
        response = NflverseLiveProbeTests._Response(_csv(_row("2024_01_BUF_NE")))
        for name, value in flags.items():
            setattr(response, name, value)

        class _Client:
            def get_text(self, url: str, timeout: int = 60):
                return response

        return _Client()

    def test_a_research_load_may_use_the_cache(self) -> None:
        """Re-reading one archive from cache is what keeps a verdict on one hash."""
        dataset = load_nflverse_games(client=self._client(from_cache=True))
        self.assertEqual(len(dataset.games), 1)

    def test_a_probe_refuses_a_cached_or_stale_body(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "nflverse_games_not_live:served_from_cache"):
            load_nflverse_games(client=self._client(from_cache=True), require_live=True)
        with self.assertRaisesRegex(RuntimeError, "nflverse_games_not_live:stale_response:upstream_error"):
            load_nflverse_games(
                client=self._client(stale=True, stale_reason="upstream_error"), require_live=True
            )

    def test_a_live_body_passes_the_probe(self) -> None:
        dataset = load_nflverse_games(client=self._client(), require_live=True)
        self.assertEqual(len(dataset.games), 1)
