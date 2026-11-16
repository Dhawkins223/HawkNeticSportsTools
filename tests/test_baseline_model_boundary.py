import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from kalshi_research_bot.agents import ModelBot
from kalshi_research_bot.cli import main
from kalshi_research_bot.contracts import Game, MarketQuote
from kalshi_research_bot.pipeline import ResearchPipeline


def game(signals=None):
    return Game("fixture", "nba", "NBA", "Home", "Away", "2026-01-01T00:00:00Z", signals or {})


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
