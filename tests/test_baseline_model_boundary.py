import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from kalshi_research_bot.agents import ModelBot
from kalshi_research_bot.cli import main
from kalshi_research_bot.contracts import Game, MarketQuote
from kalshi_research_bot.pipeline import ResearchPipeline


def game(signals=None):
    return Game("fixture", "nba", "NBA", "Home", "Away", "2026-01-01T00:00:00Z", signals or {})


OVERFLOW_SIGNALS = (
    {"home_rating": 0, "away_rating": 1e308},
    {"home_expected_goals": 1e308, "away_expected_goals": 1},
    {"home_expected_goals": 1, "away_expected_goals": 1e308},
    {"home_rating": 1e308, "away_rating": 0, "home_field_points": 1e308},
    {"home_rating": 1e308, "away_rating": -1e308},
    {"home_rating": -1e308, "away_rating": 1e308},
)


class BaselineModelBoundaryTests(unittest.TestCase):
    def run_cli(self, arguments):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            code = main(arguments)
        return code, buffer.getvalue()

    def write_inputs(self, signals):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        base = Path(temporary.name)
        games = base / "games.json"
        quotes = base / "quotes.json"
        games.write_text(json.dumps({"games": [game(signals).__dict__]}), encoding="utf-8")
        quotes.write_text(json.dumps({"quotes": [{
            "ticker": "FIXTURE", "game_id": "fixture", "title": "Home win", "yes_ask": 20.0,
        }]}), encoding="utf-8")
        return ["run", "--games", str(games), "--quotes", str(quotes)]

    def test_pipeline_requires_explicit_baseline_selection(self):
        with self.assertRaisesRegex(ValueError, "baseline"):
            ResearchPipeline().run([game({"home_rating": 1600, "away_rating": 1500})], [])

    def test_cli_blocks_before_loading_or_persisting_an_implicit_model(self):
        with patch("kalshi_research_bot.cli.load_games") as load, patch("kalshi_research_bot.cli.create_store") as store:
            code, output = self.run_cli(["run", "--games", "unused", "--quotes", "unused", "--save-db"])
        self.assertEqual(code, 2)
        self.assertIn("canonical", output.lower())
        load.assert_not_called()
        store.assert_not_called()

    def test_explicit_baseline_carries_unvalidated_and_market_context_labels(self):
        code, output = self.run_cli(self.write_inputs({"market_prior_home_prob": 0.7}) + ["--baseline-only"])
        self.assertEqual(code, 0)
        self.assertIn("unvalidated_baseline", output)
        self.assertIn("market_conditioned", output)
        self.assertIn("canonical_model_selection=unresolved", output)

    def test_baseline_prediction_labels_survive_edge_calculation(self):
        edges = ResearchPipeline(baseline_only=True).run(
            [game({"home_rating": 1600, "away_rating": 1500})],
            [MarketQuote("FIXTURE", "fixture", "Home win", yes_ask=20.0)],
        )
        self.assertTrue(edges)
        for edge in edges:
            self.assertIn("model_status=unvalidated_baseline", edge.notes)
            self.assertIn("canonical_model_selection=unresolved", edge.notes)

    def test_missing_signals_do_not_manufacture_a_neutral_forecast(self):
        with self.assertRaisesRegex(ValueError, "No supported model signals"):
            ModelBot().predict_home_win(game())

    def test_cli_missing_signals_returns_blocked_without_results(self):
        code, output = self.run_cli(self.write_inputs({}) + ["--baseline-only"])
        self.assertEqual(code, 2)
        self.assertIn("No supported model signals", output)
        self.assertNotIn("50.00%", output)

    def test_invalid_supplied_signals_are_refused_even_in_an_unused_pair(self):
        names = (
            "home_expected_goals", "away_expected_goals", "home_rating", "away_rating",
            "home_field_points", "market_prior_home_prob",
        )
        invalid = (None, float("nan"), float("inf"), -float("inf"), "0.5", True, False, [], {}, 10**400)
        for name in names:
            for value in invalid:
                with self.subTest(name=name, value=value):
                    signals = {"market_prior_home_prob": 0.6, name: value}
                    with self.assertRaisesRegex(ValueError, f"Invalid model signal {name}"):
                        ModelBot().predict_home_win(game(signals))

    def test_cli_invalid_signals_block_forecasts_and_database_access(self):
        names = (
            "home_expected_goals", "away_expected_goals", "home_rating", "away_rating",
            "home_field_points", "market_prior_home_prob",
        )
        invalid = (None, float("nan"), float("inf"), -float("inf"), "0.5", True, False, [], {}, 10**400)
        with patch("kalshi_research_bot.cli.create_store") as store:
            for name in names:
                for value in invalid:
                    with self.subTest(name=name, value=value):
                        arguments = self.write_inputs({"market_prior_home_prob": 0.6, name: value})
                        code, output = self.run_cli(arguments + ["--baseline-only"])
                        self.assertEqual(code, 2)
                        self.assertIn(f"Invalid model signal {name}", output)
                        self.assertIn("no probability was generated", output)
                        self.assertNotIn("canonical_model_selection=unresolved", output)
            store.assert_not_called()

    def test_invalid_signal_domains_are_refused_instead_of_clamped(self):
        for signals in (
            {"market_prior_home_prob": -0.01},
            {"market_prior_home_prob": 1.01},
            {"home_expected_goals": -0.1, "away_expected_goals": 1.0},
            {"home_expected_goals": 1.0, "away_expected_goals": -0.1},
        ):
            with self.subTest(signals=signals):
                with self.assertRaisesRegex(ValueError, "Invalid model signal"):
                    ModelBot().predict_home_win(game(signals))

    def test_cli_invalid_domains_block_forecasts_and_database_access(self):
        with patch("kalshi_research_bot.cli.create_store") as store:
            for signals in (
                {"market_prior_home_prob": -0.01},
                {"market_prior_home_prob": 1.01},
                {"home_expected_goals": -0.1, "away_expected_goals": 1.0},
                {"home_expected_goals": 1.0, "away_expected_goals": -0.1},
            ):
                with self.subTest(signals=signals):
                    code, output = self.run_cli(self.write_inputs(signals) + ["--baseline-only"])
                    self.assertEqual(code, 2)
                    self.assertIn("no probability was generated", output)
                    self.assertNotIn("canonical_model_selection=unresolved", output)
            store.assert_not_called()

    def test_component_overflow_and_nonfinite_derived_ratings_are_refused(self):
        for signals in OVERFLOW_SIGNALS:
            with self.subTest(signals=signals):
                with self.assertRaisesRegex(ValueError, "no probability was generated"):
                    ModelBot().predict_home_win(game(signals))

    def test_cli_component_overflow_blocks_forecasts_and_database_access(self):
        with patch("kalshi_research_bot.cli.create_store") as store:
            for signals in OVERFLOW_SIGNALS:
                with self.subTest(signals=signals):
                    code, output = self.run_cli(self.write_inputs(signals) + ["--baseline-only"])
                    self.assertEqual(code, 2)
                    self.assertIn("no probability was generated", output)
                    self.assertNotIn("canonical_model_selection=unresolved", output)
            store.assert_not_called()

    def test_signal_container_must_be_an_object(self):
        for invalid in (None, False, [], "signals"):
            with self.subTest(signals=invalid):
                with self.assertRaisesRegex(ValueError, "expected an object"):
                    ModelBot().predict_home_win(replace(game(), signals=invalid))

    def test_zero_signals_and_probability_endpoints_are_valid(self):
        for signals, expected in (
            ({"market_prior_home_prob": 0}, 0.0),
            ({"market_prior_home_prob": 1}, 1.0),
            ({"home_expected_goals": 0, "away_expected_goals": 0}, 0.0),
            ({"home_rating": 0, "away_rating": 0, "home_field_points": 0}, 0.5),
        ):
            with self.subTest(signals=signals):
                prediction = ModelBot().predict_home_win(game(signals))
                self.assertEqual(prediction.probability, expected)
                self.assertIn("model_status=unvalidated_baseline", prediction.notes)

    def test_incomplete_valid_pairs_are_explicitly_skipped_with_another_signal(self):
        for name, skipped in (
            ("home_expected_goals", "skipped poisson: incomplete expected-score pair"),
            ("away_expected_goals", "skipped poisson: incomplete expected-score pair"),
            ("home_rating", "skipped elo: incomplete rating pair"),
            ("away_rating", "skipped elo: incomplete rating pair"),
            ("home_field_points", "skipped elo: incomplete rating pair"),
        ):
            with self.subTest(name=name):
                prediction = ModelBot().predict_home_win(game({name: 0, "market_prior_home_prob": 0.6}))
                self.assertAlmostEqual(prediction.probability, 0.6)
                self.assertIn(skipped, prediction.notes)
                self.assertIn("information_mode=market_conditioned", prediction.notes)

    def test_incomplete_valid_pairs_without_another_signal_are_refused(self):
        for name in ("home_expected_goals", "away_expected_goals", "home_rating", "away_rating", "home_field_points"):
            with self.subTest(name=name):
                with self.assertRaisesRegex(ValueError, "No supported model signals"):
                    ModelBot().predict_home_win(game({name: 0}))

    def test_demo_remains_a_labeled_offline_example(self):
        code, output = self.run_cli(["demo"])
        self.assertEqual(code, 0)
        self.assertIn("unvalidated_baseline", output)
        self.assertIn("canonical_model_selection=unresolved", output)

    def test_baseline_examples_cannot_enter_research_database(self):
        arguments = self.write_inputs({"market_prior_home_prob": 0.7})
        with patch("kalshi_research_bot.cli.create_store") as store:
            code, output = self.run_cli(arguments + ["--baseline-only", "--save-db"])
            demo_code, _ = self.run_cli(["demo", "--save-db"])
        self.assertEqual(code, 2)
        self.assertEqual(demo_code, 2)
        self.assertIn("persist", output.lower())
        store.assert_not_called()


if __name__ == "__main__":
    unittest.main()
