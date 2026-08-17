import json
import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.research_registry import (
    ExperimentRecord,
    hypothesis_key,
    negative_results,
    previously_rejected,
    read_experiments,
    record_experiment,
    registry_summary,
    significance_review,
    verify_registry,
)


def _record(**overrides) -> ExperimentRecord:
    fields = {
        "hypothesis": "Trailing five-game form beats season-long rating",
        "rationale": "Recency is widely assumed to carry signal.",
        "dataset_version": "sports_2024_2026_v3",
        "target": "moneyline_win",
        "baseline": "closing_no_vig_probability",
        "test_method": "walk_forward_by_season",
        "decision": "rejected",
        "effect_size": -0.0011,
        "effect_metric": "brier_improvement",
        "confidence_interval": [-0.004, 0.002],
        "sample_size": 4200,
        "researcher": "research-agent",
    }
    fields.update(overrides)
    return ExperimentRecord(**fields)


class RegistryTest(unittest.TestCase):
    def setUp(self) -> None:
        self._directory = tempfile.TemporaryDirectory()
        self.path = Path(self._directory.name) / "experiment_registry.jsonl"

    def tearDown(self) -> None:
        self._directory.cleanup()

    def test_missing_registry_reads_as_empty(self) -> None:
        self.assertEqual(read_experiments(self.path), [])
        self.assertTrue(verify_registry(self.path)["valid"])

    def test_recording_appends_without_rewriting_history(self) -> None:
        first = record_experiment(_record(), path=self.path)
        second = record_experiment(_record(hypothesis="Referee crew predicts total fouls"), path=self.path)

        rows = read_experiments(self.path)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["entry_hash"], first["entry_hash"])
        self.assertEqual(second["previous_hash"], first["entry_hash"])
        self.assertTrue(verify_registry(self.path)["valid"])

    def test_an_edited_entry_breaks_the_chain(self) -> None:
        record_experiment(_record(), path=self.path)
        record_experiment(_record(hypothesis="Weather improves NFL totals"), path=self.path)

        lines = self.path.read_text(encoding="utf-8").splitlines()
        tampered = json.loads(lines[0])
        tampered["decision"] = "accepted"
        lines[0] = json.dumps(tampered, sort_keys=True)
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        integrity = verify_registry(self.path)
        self.assertFalse(integrity["valid"])
        self.assertEqual(integrity["broken_at_index"], 0)

    def test_a_deleted_entry_breaks_the_chain(self) -> None:
        record_experiment(_record(), path=self.path)
        record_experiment(_record(hypothesis="Steam moves predict outcomes"), path=self.path)
        lines = self.path.read_text(encoding="utf-8").splitlines()
        self.path.write_text(lines[1] + "\n", encoding="utf-8")

        self.assertFalse(verify_registry(self.path)["valid"])

    def test_acceptance_requires_an_interval_that_excludes_zero(self) -> None:
        with self.assertRaises(ValueError):
            record_experiment(
                _record(decision="accepted", confidence_interval=[-0.001, 0.004]),
                path=self.path,
            )

    def test_acceptance_requires_an_interval_at_all(self) -> None:
        with self.assertRaises(ValueError):
            record_experiment(_record(decision="accepted", confidence_interval=None), path=self.path)

    def test_a_genuine_improvement_can_be_accepted(self) -> None:
        entry = record_experiment(
            _record(
                hypothesis="Shin de-vig beats proportional normalization as the baseline",
                decision="accepted",
                effect_size=0.0031,
                confidence_interval=[0.0012, 0.0050],
            ),
            path=self.path,
        )
        self.assertEqual(entry["decision"], "accepted")

    def test_unknown_decisions_and_missing_fields_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            record_experiment(_record(decision="promising"), path=self.path)
        with self.assertRaises(ValueError):
            record_experiment(_record(baseline=""), path=self.path)

    def test_inverted_intervals_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            record_experiment(_record(confidence_interval=[0.05, 0.01]), path=self.path)

    def test_previously_rejected_survives_rewording(self) -> None:
        record_experiment(_record(hypothesis="Twitter sentiment improves win probability"), path=self.path)
        matches = previously_rejected("  twitter sentiment improves win probability!  ", path=self.path)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["decision"], "rejected")

    def test_untested_hypotheses_return_no_prior_rejection(self) -> None:
        record_experiment(_record(), path=self.path)
        self.assertEqual(previously_rejected("Altitude affects NHL shot volume", path=self.path), [])

    def test_negative_results_collects_only_rejections(self) -> None:
        record_experiment(_record(), path=self.path)
        record_experiment(
            _record(
                hypothesis="Shin de-vig improves the baseline",
                decision="accepted",
                effect_size=0.003,
                confidence_interval=[0.001, 0.005],
            ),
            path=self.path,
        )
        record_experiment(_record(hypothesis="Rest advantage survives market control", decision="inconclusive"), path=self.path)

        self.assertEqual(len(negative_results(self.path)), 1)

    def test_summary_counts_decisions_and_reports_integrity(self) -> None:
        record_experiment(_record(), path=self.path)
        record_experiment(_record(hypothesis="Head-to-head record adds signal"), path=self.path)
        summary = registry_summary(self.path)

        self.assertEqual(summary["entry_count"], 2)
        self.assertEqual(summary["decisions"]["rejected"], 2)
        self.assertEqual(summary["distinct_hypotheses"], 2)
        self.assertTrue(summary["chain_valid"])

    def test_significance_review_demotes_a_finding_selected_from_many(self) -> None:
        # One borderline acceptance recorded alongside the nulls it was chosen
        # from should not survive family-wise correction.
        record_experiment(
            _record(
                hypothesis="Borderline feature improves Brier",
                decision="accepted",
                effect_size=0.004,
                confidence_interval=[0.0001, 0.0079],
            ),
            path=self.path,
        )
        for index in range(40):
            record_experiment(
                _record(hypothesis=f"Null feature {index}", effect_size=0.001, confidence_interval=[-0.004, 0.006]),
                path=self.path,
            )

        review = significance_review(self.path)
        self.assertEqual(review["family_size"], 41)
        self.assertEqual(len(review["demoted"]), 1)
        self.assertEqual(review["demoted"][0]["hypothesis"], "Borderline feature improves Brier")

    def test_significance_review_handles_an_empty_registry(self) -> None:
        review = significance_review(self.path)
        self.assertEqual(review["family_size"], 0)
        self.assertEqual(review["demoted"], [])

    def test_hypothesis_key_normalizes_punctuation_and_case(self) -> None:
        self.assertEqual(
            hypothesis_key("Last-Three-Games Trend!"),
            hypothesis_key("last three games trend"),
        )


if __name__ == "__main__":
    unittest.main()
