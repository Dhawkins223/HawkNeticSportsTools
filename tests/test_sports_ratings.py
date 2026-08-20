from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from kalshi_research_bot.sports_ratings import (
    EloConfig,
    GameResult,
    build_sports_ratings_report,
    elo_win_probability,
    load_settled_games,
    market_home_probabilities,
    paired_comparison,
    record_sports_ratings_experiment,
    render_sports_ratings_report,
    walk_forward,
)
from kalshi_research_bot.sports_clv import capture_sports_closing_lines
from kalshi_research_bot.sports_research import (
    log_sports_predictions,
    normalize_the_odds_api_payload,
    settle_sports_predictions,
)

from kalshi_research_bot.research_registry import read_experiments, verify_registry

from tests.postgres_support import PostgresTestCase


BASE_TIME = datetime(2026, 4, 1, 18, 0, tzinfo=timezone.utc)


def _game(
    index: int,
    *,
    home: str,
    away: str,
    home_score: int,
    away_score: int,
    league: str = "nba",
) -> GameResult:
    return GameResult(
        event_id=f"evt_{index}",
        sport="basketball",
        league=league,
        start_time=BASE_TIME + timedelta(hours=index),
        home_team=home,
        away_team=away,
        home_score=Decimal(home_score),
        away_score=Decimal(away_score),
    )


def _round_robin(rounds: int, *, strong_wins: bool = True) -> list[GameResult]:
    """A schedule where one team is genuinely stronger than the rest.

    Elo can only beat a base rate when strength differs between teams, so the
    fixture has to contain a real signal for the test to mean anything.
    """
    teams = ["Alpha", "Bravo", "Charlie", "Delta"]
    games: list[GameResult] = []
    index = 0
    for _ in range(rounds):
        for home in teams:
            for away in teams:
                if home == away:
                    continue
                index += 1
                if "Alpha" in (home, away) and strong_wins:
                    alpha_is_home = home == "Alpha"
                    home_score, away_score = (110, 100) if alpha_is_home else (100, 110)
                else:
                    home_score, away_score = (105, 100) if index % 2 == 0 else (100, 105)
                games.append(
                    _game(index, home=home, away=away, home_score=home_score, away_score=away_score)
                )
    return games


class EloMathTests(PostgresTestCase):
    def test_home_advantage_moves_an_even_matchup_above_a_coin_flip(self) -> None:
        even = elo_win_probability(Decimal("1500"), Decimal("1500"), home_advantage=Decimal("0"))
        self.assertEqual(even, Decimal("0.5"))
        with_home = elo_win_probability(Decimal("1500"), Decimal("1500"), home_advantage=Decimal("55"))
        self.assertGreater(with_home, Decimal("0.5"))

    def test_a_four_hundred_point_edge_is_ten_to_one(self) -> None:
        probability = elo_win_probability(
            Decimal("1900"), Decimal("1500"), home_advantage=Decimal("0")
        )
        self.assertAlmostEqual(float(probability), 10.0 / 11.0, places=9)

    def test_walk_forward_never_lets_a_game_inform_its_own_forecast(self) -> None:
        """The central leakage guarantee: predict, then update, in start order."""
        games = _round_robin(3)
        rows, _ = walk_forward(games, config=EloConfig(min_team_games=2))

        flipped = list(games)
        last = flipped[-1]
        flipped[-1] = GameResult(
            event_id=last.event_id,
            sport=last.sport,
            league=last.league,
            start_time=last.start_time,
            home_team=last.home_team,
            away_team=last.away_team,
            home_score=last.away_score,
            away_score=last.home_score,
        )
        flipped_rows, _ = walk_forward(flipped, config=EloConfig(min_team_games=2))

        self.assertEqual(
            [row.elo_probability for row in rows],
            [row.elo_probability for row in flipped_rows],
            "reversing the last game's score changed an earlier forecast",
        )
        self.assertEqual(rows[-1].elo_probability, flipped_rows[-1].elo_probability)
        self.assertNotEqual(rows[-1].home_win, flipped_rows[-1].home_win)

    def test_ties_and_unproven_teams_update_ratings_without_being_scored(self) -> None:
        games = [
            _game(1, home="Alpha", away="Bravo", home_score=100, away_score=100),
            _game(2, home="Alpha", away="Bravo", home_score=110, away_score=100),
            _game(3, home="Bravo", away="Alpha", home_score=100, away_score=110),
        ]
        rows, skipped = walk_forward(games, config=EloConfig(min_team_games=2))
        self.assertEqual(skipped["tie_has_no_binary_outcome"], 1)
        self.assertEqual(skipped["team_below_minimum_games"], 1)
        self.assertEqual([row.event_id for row in rows], ["evt_3"])
        # The tie still moved the ratings it was excluded from scoring.
        self.assertNotEqual(rows[0].home_rating_before, rows[0].away_rating_before)

    def test_base_rate_uses_only_games_already_finished(self) -> None:
        games = [
            _game(index, home="Alpha", away="Bravo", home_score=110, away_score=100)
            for index in range(1, 6)
        ]
        rows, _ = walk_forward(games, config=EloConfig(min_team_games=0))
        # First forecast has no history: the uniform prior alone, exactly 1/2.
        self.assertEqual(rows[0].base_rate_probability, Decimal("0.5"))
        # After four home wins: (4 + 1) / (4 + 2).
        self.assertEqual(rows[4].base_rate_probability, Decimal(5) / Decimal(6))

    def test_paired_comparison_reports_direction_and_inconclusiveness(self) -> None:
        outcomes = [1, 0] * 40
        confident = [Decimal("0.9") if outcome else Decimal("0.1") for outcome in outcomes]
        coin_flip = [Decimal("0.5")] * len(outcomes)

        better = paired_comparison(
            model_probabilities=confident, baseline_probabilities=coin_flip, outcomes=outcomes
        )
        self.assertEqual(better["verdict"], "model_better")
        self.assertGreater(better["confidence_interval"][0], 0)

        worse = paired_comparison(
            model_probabilities=coin_flip, baseline_probabilities=confident, outcomes=outcomes
        )
        self.assertEqual(worse["verdict"], "baseline_better")
        self.assertLess(worse["confidence_interval"][1], 0)

        noisy_model = [Decimal("0.52") if index % 3 else Decimal("0.48") for index in range(len(outcomes))]
        unclear = paired_comparison(
            model_probabilities=noisy_model, baseline_probabilities=coin_flip, outcomes=outcomes
        )
        self.assertEqual(unclear["verdict"], "inconclusive")

    def test_identical_forecasts_are_not_reported_as_an_improvement(self) -> None:
        outcomes = [1, 0] * 20
        same = [Decimal("0.5")] * len(outcomes)
        result = paired_comparison(
            model_probabilities=same, baseline_probabilities=same, outcomes=outcomes
        )
        self.assertEqual(result["verdict"], "identical_forecasts")
        self.assertIsNone(result["confidence_interval"])


class SportsRatingsDatabaseTests(PostgresTestCase):
    def _log_game(
        self,
        *,
        event_id: str,
        home: str,
        away: str,
        start: datetime,
        prices: dict[str, list[tuple[int, int]]],
        run_id: str = "ratings",
    ) -> None:
        """Record one game's quotes; `prices` maps a book to (home, away) pairs in time order."""
        for bookmaker, quotes in prices.items():
            for offset, (home_price, away_price) in enumerate(quotes):
                fetched = (start - timedelta(minutes=60 - offset * 10)).isoformat()
                records = normalize_the_odds_api_payload(
                    [
                        {
                            "id": event_id,
                            "commence_time": start.isoformat(),
                            "home_team": home,
                            "away_team": away,
                            "bookmakers": [
                                {
                                    "key": bookmaker,
                                    "last_update": fetched,
                                    "markets": [
                                        {
                                            "key": "h2h",
                                            "outcomes": [
                                                {"name": home, "price": home_price},
                                                {"name": away, "price": away_price},
                                            ],
                                        }
                                    ],
                                }
                            ],
                        }
                    ],
                    sport="basketball_nba",
                    league="nba",
                    api_fetched_at=fetched,
                )
                log_sports_predictions(
                    run_id=run_id,
                    payload={
                        "asset_class": "sports",
                        "model_version": "sports_odds_research_v1",
                        "strategy": "pregame_odds_snapshot_v1",
                        "generated_at": fetched,
                        "records": records,
                    },
                )

    def _settle(self, *, event_id: str, home: str, away: str, home_score: int, away_score: int, run_id: str = "ratings") -> None:
        settle_sports_predictions(
            run_id=run_id,
            finals_payload={
                "events": [
                    {
                        "event_id": event_id,
                        "home_team": home,
                        "away_team": away,
                        "home_score": home_score,
                        "away_score": away_score,
                        "status": "final",
                    }
                ]
            },
        )

    def test_settled_rows_reconstruct_the_games_that_produced_them(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(hours=4)
        self._log_game(
            event_id="g1",
            home="Alpha",
            away="Bravo",
            start=start,
            prices={"book_a": [(-150, 130)]},
        )
        self._settle(event_id="g1", home="Alpha", away="Bravo", home_score=110, away_score=100)

        games, excluded = load_settled_games()
        self.assertEqual(excluded, {})
        self.assertEqual(len(games), 1)
        self.assertEqual(games[0].event_id, "g1")
        self.assertEqual(games[0].home_team, "Alpha")
        self.assertEqual(games[0].home_score, Decimal("110"))
        self.assertEqual(games[0].home_win, 1)

    def test_an_event_whose_settled_rows_disagree_is_dropped_not_guessed(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(hours=4)
        self._log_game(
            event_id="g1", home="Alpha", away="Bravo", start=start, prices={"book_a": [(-150, 130)]}
        )
        self._settle(event_id="g1", home="Alpha", away="Bravo", home_score=110, away_score=100)
        # A later revision writes a different final score onto one of the rows.
        self.query_one(
            """
            UPDATE app.sports_prediction_logs
            SET final_score_json = jsonb_set(final_score_json, '{home_score}', '99')
            WHERE id = (SELECT MIN(id) FROM app.sports_prediction_logs)
            RETURNING id
            """
        )

        games, excluded = load_settled_games()
        self.assertEqual(games, [])
        self.assertEqual(excluded, {"conflicting_final_scores": 1})

    def test_market_baseline_devigs_each_book_then_takes_the_consensus(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(hours=4)
        self._log_game(
            event_id="g1",
            home="Alpha",
            away="Bravo",
            start=start,
            prices={"book_a": [(-150, 130)], "book_b": [(-170, 145)]},
        )
        capture_sports_closing_lines(run_id="ratings")

        probabilities = market_home_probabilities()
        self.assertIn("g1", probabilities)
        consensus = probabilities["g1"]
        # Both books favour the home team, and the fair probability sits between
        # the vigged implied prices of the two closes.
        self.assertGreater(consensus, Decimal("0.55"))
        self.assertLess(consensus, Decimal("0.65"))

    def test_an_unpriced_game_has_no_market_baseline_rather_than_a_guess(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(hours=4)
        self._log_game(
            event_id="g1", home="Alpha", away="Bravo", start=start, prices={"book_a": [(-150, 130)]}
        )
        # No closing-line capture has run, so no row carries a close.
        self.assertEqual(market_home_probabilities(), {})

    def test_report_withholds_a_verdict_until_enough_games_are_evaluated(self) -> None:
        start = datetime.now(timezone.utc) - timedelta(hours=4)
        self._log_game(
            event_id="g1", home="Alpha", away="Bravo", start=start, prices={"book_a": [(-150, 130)]}
        )
        self._settle(event_id="g1", home="Alpha", away="Bravo", home_score=110, away_score=100)

        report = build_sports_ratings_report()
        self.assertEqual(report["decision"], "insufficient_evidence")
        self.assertEqual(report["evaluated_games"], 0)
        self.assertEqual(report["model_state"], "track_only")
        self.assertEqual(report["promotion"], "blocked_by_policy")
        self.assertIn("not a validated production model", report["disclaimer"])
        self.assertIn("insufficient_evidence", render_sports_ratings_report(report))

    def test_a_collected_season_produces_a_verdict_and_records_it(self) -> None:
        """End to end: collected quotes and finals become a graded rating."""
        teams = ["Alpha", "Bravo", "Charlie", "Delta"]
        start = datetime.now(timezone.utc) - timedelta(days=30)
        finals = []
        index = 0
        for round_number in range(6):
            for home in teams:
                for away in teams:
                    if home == away:
                        continue
                    index += 1
                    kickoff = start + timedelta(hours=index)
                    # Alpha is genuinely the strongest team; the rest split evenly.
                    if "Alpha" in (home, away):
                        alpha_home = home == "Alpha"
                        home_score, away_score = (110, 100) if alpha_home else (100, 110)
                    else:
                        home_score, away_score = (105, 100) if index % 2 else (100, 105)
                    self._log_game(
                        event_id=f"s{index}",
                        home=home,
                        away=away,
                        start=kickoff,
                        prices={"book_a": [(-110, -110)]},
                    )
                    finals.append(
                        {
                            "event_id": f"s{index}",
                            "home_team": home,
                            "away_team": away,
                            "home_score": home_score,
                            "away_score": away_score,
                            "status": "final",
                        }
                    )
        settle_sports_predictions(run_id="ratings", finals_payload={"events": finals})

        report = build_sports_ratings_report(min_evaluated_games=30)
        self.assertEqual(report["games_reconstructed"], len(finals))
        self.assertGreaterEqual(report["evaluated_games"], 30)
        self.assertIn(report["decision"], {"accepted", "inconclusive", "rejected"})
        self.assertEqual(report["metrics"]["elo"]["sample_size"], report["evaluated_games"])
        # Alpha won every game it played and must top the ratings.
        self.assertEqual(report["ratings"][0]["team"], "Alpha")

        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.jsonl"
            entry = record_sports_ratings_experiment(report, path=registry)
            self.assertIsNotNone(entry)
            self.assertEqual(entry["decision"], report["decision"])
            self.assertEqual(entry["model_version"], "elo_walk_forward_v1")
            recorded = read_experiments(registry)
            self.assertEqual(len(recorded), 1)
            self.assertTrue(verify_registry(registry)["valid"])

    def test_a_run_with_too_few_games_is_not_recorded_as_an_experiment(self) -> None:
        report = build_sports_ratings_report()
        self.assertEqual(report["decision"], "insufficient_evidence")
        with tempfile.TemporaryDirectory() as directory:
            registry = Path(directory) / "registry.jsonl"
            self.assertIsNone(record_sports_ratings_experiment(report, path=registry))
            self.assertFalse(registry.exists())
