from __future__ import annotations

import random
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kalshi_research_bot.sports_market_model import (
    MarketBlendConfig,
    build_market_blend_report,
    inverse_logit,
    logit,
    render_market_blend_report,
    walk_forward_blend,
)
from kalshi_research_bot.sports_ratings import EloConfig, GameResult, WalkForwardRow, walk_forward


BASE_TIME = datetime(2020, 9, 10, 17, 0, tzinfo=timezone.utc)


def _row(
    event_id: str,
    *,
    season: int,
    offset_days: int,
    home_win: int,
    market: str,
    elo: str = "0.500000",
) -> WalkForwardRow:
    return WalkForwardRow(
        event_id=f"{season}_{event_id}",
        league="nfl",
        start_time=BASE_TIME + timedelta(days=offset_days),
        home_team="H",
        away_team="A",
        home_win=home_win,
        elo_probability=Decimal(elo),
        base_rate_probability=Decimal("0.55"),
        market_probability=Decimal(market),
        home_rating_before=Decimal("1500"),
        away_rating_before=Decimal("1500"),
    )


def _season(season: int, count: int, *, start_day: int, elo: str = "0.500000") -> list[WalkForwardRow]:
    rows = []
    for index in range(count):
        # The market is right two-thirds of the time at a 0.65 price.
        home_win = 1 if index % 3 else 0
        rows.append(
            _row(
                f"g{index}",
                season=season,
                offset_days=start_day + index,
                home_win=home_win,
                market="0.65",
                elo=elo,
            )
        )
    return rows


class LogitTests(unittest.TestCase):
    def test_logit_and_inverse_round_trip(self) -> None:
        for probability in (0.01, 0.25, 0.5, 0.75, 0.99):
            self.assertAlmostEqual(inverse_logit(logit(probability)), probability, places=9)

    def test_certain_probabilities_are_clipped_rather_than_infinite(self) -> None:
        self.assertLess(logit(1.0), 20.0)
        self.assertGreater(logit(0.0), -20.0)


class WalkForwardBlendTests(unittest.TestCase):
    def test_a_period_is_fitted_only_from_periods_that_already_finished(self) -> None:
        """The coefficients used on a season cannot have seen that season."""
        first = _season(2020, 400, start_day=0)
        second = _season(2021, 400, start_day=500)
        blended, fits, _ = walk_forward_blend(
            first + second, config=MarketBlendConfig(min_training_rows=300)
        )

        # 2020 has no earlier season to fit from, so none of it is scored.
        self.assertTrue(all(row.event_id.startswith("2021_") for row, _ in blended))
        self.assertEqual([fit.period for fit in fits], ["2021"])
        self.assertEqual(fits[0].training_rows, 400)

        # Changing a 2021 outcome must not move the coefficients 2021 was scored with.
        mutated = list(second)
        mutated[0] = _row(
            "g0", season=2021, offset_days=500, home_win=1 - second[0].home_win, market="0.65"
        )
        _, mutated_fits, _ = walk_forward_blend(
            first + mutated, config=MarketBlendConfig(min_training_rows=300)
        )
        self.assertEqual(fits[0].as_dict(), mutated_fits[0].as_dict())

    def test_a_third_season_is_fitted_from_both_earlier_ones(self) -> None:
        rows = _season(2020, 200, start_day=0) + _season(2021, 200, start_day=500) + _season(2022, 100, start_day=1000)
        _, fits, _ = walk_forward_blend(rows, config=MarketBlendConfig(min_training_rows=300))
        self.assertEqual([fit.period for fit in fits], ["2022"])
        self.assertEqual(fits[0].training_rows, 400)

    def test_rows_without_a_market_price_are_skipped_not_filled_in(self) -> None:
        priced = _season(2020, 400, start_day=0) + _season(2021, 10, start_day=500)
        unpriced = WalkForwardRow(
            event_id="2021_no_price",
            league="nfl",
            start_time=BASE_TIME + timedelta(days=520),
            home_team="H",
            away_team="A",
            home_win=1,
            elo_probability=Decimal("0.6"),
            base_rate_probability=Decimal("0.55"),
            market_probability=None,
            home_rating_before=Decimal("1500"),
            away_rating_before=Decimal("1500"),
        )
        blended, _, skipped = walk_forward_blend(
            priced + [unpriced], config=MarketBlendConfig(min_training_rows=300)
        )
        self.assertEqual(skipped["no_market_price"], 1)
        self.assertNotIn("2021_no_price", {row.event_id for row, _ in blended})

    def test_a_history_too_short_to_fit_scores_nothing(self) -> None:
        blended, fits, skipped = walk_forward_blend(
            _season(2020, 50, start_day=0) + _season(2021, 50, start_day=500),
            config=MarketBlendConfig(min_training_rows=300),
        )
        self.assertEqual(blended, [])
        self.assertEqual(fits, [])
        self.assertEqual(skipped["period_below_minimum_training_rows"], 100)


class MarketBlendReportTests(unittest.TestCase):
    def _games(
        self,
        count: int,
        *,
        season: int,
        start_day: int,
        home_win_rate: float = 0.6,
        seed: int = 7,
    ) -> list[GameResult]:
        """Outcomes drawn at a fixed rate, uncorrelated with which teams played.

        A deterministic win pattern would be learnable structure, and the blend
        would rightly find it. The question here is what the blend does when
        there is nothing to find beyond the price.
        """
        generator = random.Random(seed + season)
        games = []
        for index in range(count):
            home_win = generator.random() < home_win_rate
            games.append(
                GameResult(
                    event_id=f"{season}_g{index:04d}",
                    sport="football",
                    league="nfl",
                    start_time=BASE_TIME + timedelta(days=start_day + index),
                    home_team=f"H{generator.randrange(8)}",
                    away_team=f"A{generator.randrange(7)}",
                    home_score=Decimal(24 if home_win else 17),
                    away_score=Decimal(17 if home_win else 24),
                )
            )
        return games

    def test_a_blend_that_cannot_improve_on_the_price_says_so(self) -> None:
        """A market already carrying the answer leaves nothing for the model."""
        games = self._games(600, season=2020, start_day=0) + self._games(600, season=2021, start_day=900)
        # The price is the rate the outcomes were actually drawn at, and nothing
        # else in the fixture predicts them, so there is no edge to find.
        market = {game.event_id: Decimal("0.600000") for game in games}

        report = build_market_blend_report(
            games,
            market,
            config=MarketBlendConfig(min_training_rows=300, elo=EloConfig(min_team_games=2)),
            source="fixture",
            dataset_version="fixture:1",
            league="nfl",
            market_baseline_name="devigged_reported_close",
        )
        self.assertIn(report["decision"], {"inconclusive", "rejected"})
        self.assertEqual(report["model_state"], "track_only")
        self.assertEqual(report["promotion"], "blocked_by_policy")
        self.assertEqual(report["market_baseline"], "devigged_reported_close")
        self.assertGreater(report["evaluated_games"], 0)
        self.assertIn("devigged_reported_close", report["metrics"])
        self.assertIn("not a validated production model", report["disclaimer"])

    def test_the_report_names_the_coefficient_that_carries_any_claim_of_edge(self) -> None:
        games = self._games(400, season=2020, start_day=0) + self._games(400, season=2021, start_day=900)
        market = {game.event_id: Decimal("0.6") for game in games}
        report = build_market_blend_report(
            games,
            market,
            config=MarketBlendConfig(min_training_rows=300, elo=EloConfig(min_team_games=2)),
        )
        summary = report["coefficient_summary"]
        self.assertIsNotNone(summary["model_weight_mean"])
        self.assertIsNotNone(summary["market_weight_last"])
        rendered = render_market_blend_report(report)
        self.assertIn("model weight", rendered)
        self.assertIn("adds nothing", rendered)

    def test_no_priced_games_means_no_verdict_rather_than_a_default_one(self) -> None:
        games = self._games(50, season=2020, start_day=0)
        report = build_market_blend_report(games, {}, config=MarketBlendConfig(min_training_rows=300))
        self.assertEqual(report["decision"], "insufficient_evidence")
        self.assertEqual(report["evaluated_games"], 0)
        self.assertEqual(report["comparisons"], [])
