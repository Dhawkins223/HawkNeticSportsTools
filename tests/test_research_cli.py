import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from kalshi_research_bot.cli import main
from kalshi_research_bot.research_registry import ExperimentRecord, record_experiment


def run(argv: list[str]) -> tuple[int, str]:
    buffer = io.StringIO()
    with redirect_stdout(buffer):
        code = main(argv)
    return code, buffer.getvalue()


class DevigCommandTest(unittest.TestCase):
    def test_compares_every_method_and_reports_disagreement(self) -> None:
        code, output = run(["devig-compare", "--american", "-900", "600"])

        self.assertEqual(code, 0)
        for method in ("multiplicative", "additive", "power", "shin", "odds_ratio"):
            self.assertIn(method, output)
        self.assertIn("Largest disagreement between methods", output)
        self.assertIn("2.51 probability points", output)

    def test_balanced_market_shows_no_disagreement(self) -> None:
        code, output = run(["devig-compare", "--american", "-110", "-110"])

        self.assertEqual(code, 0)
        self.assertIn("0.00 probability points", output)

    def test_accepts_decimal_prices(self) -> None:
        code, output = run(["devig-compare", "--decimal", "2.10", "3.40", "3.90"])

        self.assertEqual(code, 0)
        self.assertIn("Selections: 3", output)

    def test_single_selection_is_refused(self) -> None:
        code, output = run(["devig-compare", "--american", "-110"])

        self.assertEqual(code, 2)
        self.assertIn("At least two selections", output)

    def test_writes_json_when_asked(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "devig.json"
            code, _ = run(["devig-compare", "--american", "-150", "130", "--output", str(target)])

            self.assertEqual(code, 0)
            self.assertTrue(target.exists())
            self.assertIn("shin", target.read_text(encoding="utf-8"))


class PowerCommandTest(unittest.TestCase):
    def test_reports_required_sample_for_an_edge(self) -> None:
        code, output = run(["research-power", "--edge", "0.01"])

        self.assertEqual(code, 0)
        self.assertIn("19,565", output)

    def test_reports_minimum_detectable_edge_for_a_sample(self) -> None:
        code, output = run(["research-power", "--sample-size", "300"])

        self.assertEqual(code, 0)
        self.assertIn("8.078%", output)
        self.assertIn("invisible", output)

    def test_reports_paired_score_requirements(self) -> None:
        code, output = run(["research-power", "--score-improvement", "0.002", "--score-std", "0.05"])

        self.assertEqual(code, 0)
        self.assertIn("4,906", output)

    def test_discounts_clustered_predictions(self) -> None:
        code, output = run(
            ["research-power", "--sample-size", "1000", "--cluster-size", "5", "--intraclass-correlation", "0.3"]
        )

        self.assertEqual(code, 0)
        self.assertIn("454.5", output)

    def test_requires_at_least_one_question(self) -> None:
        code, output = run(["research-power"])

        self.assertEqual(code, 2)
        self.assertIn("Provide --edge", output)


class RegistryCommandTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.path = Path(self._directory.name) / "registry.jsonl"

    def tearDown(self) -> None:
        self._directory.cleanup()

    def _record(self, hypothesis: str, decision: str, effect: float, interval: list[float]) -> None:
        record_experiment(
            ExperimentRecord(
                hypothesis=hypothesis,
                rationale="recorded by test",
                dataset_version="v1",
                target="moneyline_win",
                baseline="closing_no_vig_probability",
                test_method="walk_forward_by_season",
                decision=decision,
                effect_size=effect,
                confidence_interval=interval,
                sample_size=3000,
            ),
            path=self.path,
        )

    def test_empty_registry_reports_cleanly(self) -> None:
        code, output = run(["research-registry", "--path", str(self.path)])

        self.assertEqual(code, 0)
        self.assertIn("Entries:  0", output)

    def test_demotes_a_finding_selected_from_many_nulls(self) -> None:
        self._record("Borderline feature improves Brier", "accepted", 0.004, [0.0001, 0.0079])
        for index in range(40):
            self._record(f"Null feature {index}", "rejected", 0.001, [-0.004, 0.006])

        code, output = run(["research-registry", "--path", str(self.path)])

        self.assertEqual(code, 0)
        self.assertIn("DEMOTED", output)
        self.assertIn("Borderline feature improves Brier", output)

    def test_a_strong_finding_is_not_demoted(self) -> None:
        self._record("Strong feature improves Brier", "accepted", 0.05, [0.04, 0.06])
        for index in range(10):
            self._record(f"Null feature {index}", "rejected", 0.001, [-0.004, 0.006])

        code, output = run(["research-registry", "--path", str(self.path)])

        self.assertEqual(code, 0)
        self.assertIn("No accepted finding was demoted", output)

    def test_lists_negative_results_on_request(self) -> None:
        self._record("Twitter sentiment improves win probability", "rejected", -0.001, [-0.004, 0.002])

        code, output = run(["research-registry", "--path", str(self.path), "--negative-results"])

        self.assertEqual(code, 0)
        self.assertIn("Rejected hypotheses:", output)
        self.assertIn("Twitter sentiment", output)

    def test_reports_a_broken_hash_chain(self) -> None:
        self._record("First", "rejected", 0.001, [-0.004, 0.006])
        self._record("Second", "rejected", 0.001, [-0.004, 0.006])
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text(lines[1] + "\n", encoding="utf-8")

        code, output = run(["research-registry", "--path", str(self.path)])

        self.assertEqual(code, 0)
        self.assertIn("Chain valid: False", output)
        self.assertIn("edited or truncated", output)


if __name__ == "__main__":
    unittest.main()
