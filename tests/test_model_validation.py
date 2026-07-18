import unittest
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, timezone

from kalshi_research_bot.evaluation.model_validation import (
    EvaluationRecord,
    calibration_buckets,
    dataset_version,
    detect_probability_drift,
    evaluate_category_model,
    leakage_failures,
    probability_metrics,
    persist_category_evaluation,
    time_aware_split,
    walk_forward_splits,
)
from kalshi_research_bot.business_store import open_runtime_connection


def _records(count, *, model_probability=None, category="sports"):
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        outcome = 1 if index % 5 else 0
        supplied = model_probability(outcome, index) if callable(model_probability) else model_probability
        rows.append(
            EvaluationRecord(
                record_id=f"row-{index:04d}",
                category=category,
                prediction_timestamp=(start + timedelta(hours=index)).isoformat(),
                settlement_timestamp=(start + timedelta(hours=index + 2)).isoformat(),
                outcome=outcome,
                market_probability=0.58,
                model_probability=supplied,
                model_version="candidate-v1",
                feature_version=f"{category}-features-v1",
                features={f"{category}_signal": index / max(1, count)},
                feature_observed_at={f"{category}_signal": (start + timedelta(hours=index - 1)).isoformat()},
            )
        )
    return rows


class ModelValidationTests(unittest.TestCase):
    def test_probability_metrics_include_required_scores_and_intervals(self):
        metrics = probability_metrics([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0])
        self.assertEqual(metrics["sample_size"], 4)
        self.assertAlmostEqual(metrics["brier_score"], 0.025)
        self.assertLess(metrics["log_loss"], 0.2)
        self.assertEqual(metrics["accuracy"], 1.0)
        self.assertEqual(len(metrics["accuracy_ci95"]), 2)
        self.assertEqual(sum(bucket["count"] for bucket in metrics["calibration_buckets"]), 4)

    def test_calibration_buckets_preserve_empty_bucket_sample_sizes(self):
        buckets = calibration_buckets([0.15, 0.85], [0, 1])
        self.assertEqual(len(buckets), 10)
        self.assertEqual(sum(bucket["count"] for bucket in buckets), 2)
        self.assertTrue(any(bucket["count"] == 0 for bucket in buckets))

    def test_time_split_is_strictly_ordered_and_walk_forward_never_looks_ahead(self):
        rows = list(reversed(_records(20)))
        split = time_aware_split(rows)
        self.assertLess(split["train"][-1].prediction_timestamp, split["validation"][0].prediction_timestamp)
        self.assertLess(split["validation"][-1].prediction_timestamp, split["test"][0].prediction_timestamp)
        folds = walk_forward_splits(rows, minimum_train_rows=10, test_rows=4, step_rows=3)
        self.assertEqual(len(folds), 3)
        for fold in folds:
            self.assertLess(fold["train"][-1].prediction_timestamp, fold["test"][0].prediction_timestamp)

    def test_leakage_detection_blocks_target_and_future_features(self):
        record = _records(1)[0]
        contaminated = EvaluationRecord(
            **{
                **record.__dict__,
                "features": {"sports_signal": 1.0, "final_score": "4-2"},
                "feature_observed_at": {"sports_signal": "2026-01-02T00:00:00Z"},
            }
        )
        failures = leakage_failures(contaminated)
        self.assertIn("target_leakage_field:final_score", failures)
        self.assertIn("future_feature:sports_signal", failures)
        result = evaluate_category_model([contaminated, *_records(9)[1:]], category="sports", minimum_test_rows=1)
        self.assertEqual(result["model_state"], "failed_validation")
        self.assertEqual(result["reason"], "leakage_detected")

    def test_category_mismatch_is_rejected_instead_of_using_generic_model(self):
        with self.assertRaisesRegex(ValueError, "mixed_or_mismatched_categories"):
            evaluate_category_model(_records(10, category="crypto"), category="sports")

    def test_small_out_of_sample_set_cannot_be_marked_validated(self):
        result = evaluate_category_model(
            _records(100, model_probability=lambda outcome, _: 0.9 if outcome else 0.1),
            category="sports",
        )
        self.assertEqual(result["model_state"], "insufficient_sample")
        self.assertEqual(result["periods"]["test"]["sample_size"], 20)
        self.assertIn("market_implied", result["test_metrics"])
        self.assertTrue(result["dataset_version"].startswith("sha256:"))

    def test_candidate_only_validates_after_oos_baseline_improvement(self):
        rows = _records(600, model_probability=lambda outcome, _: 0.9 if outcome else 0.1)
        result = evaluate_category_model(rows, category="sports")
        self.assertEqual(result["model_state"], "validated_research")
        self.assertGreater(result["baseline_comparison"]["brier_improvement"], 0)
        self.assertGreater(result["baseline_comparison"]["log_loss_improvement"], 0)
        self.assertEqual(result["periods"]["test"]["sample_size"], 120)

    def test_poor_candidate_fails_market_baseline(self):
        rows = _records(
            600,
            model_probability=lambda outcome, index: (
                (0.9 if outcome else 0.1)
                if index < 480
                else (0.1 if outcome else 0.9)
            ),
        )
        result = evaluate_category_model(rows, category="sports")
        self.assertEqual(result["model_state"], "failed_validation")
        self.assertEqual(result["reason"], "challenger_did_not_beat_market_baseline")

    def test_dataset_version_is_deterministic(self):
        rows = _records(10)
        self.assertEqual(dataset_version(rows), dataset_version(list(reversed(rows))))

    def test_drift_state_is_explicit(self):
        result = detect_probability_drift(
            [0.9, 0.8, 0.2, 0.1],
            [1, 1, 0, 0],
            [0.1, 0.2, 0.8, 0.9],
            [1, 1, 0, 0],
        )
        self.assertEqual(result["model_state"], "drift_detected")

    def test_evaluation_evidence_and_probability_differences_persist_idempotently(self):
        rows = _records(600, model_probability=lambda outcome, _: 0.9 if outcome else 0.1)
        result = evaluate_category_model(rows, category="sports")
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "evaluation-runtime"
            first = persist_category_evaluation(str(database), rows, result)
            second = persist_category_evaluation(str(database), rows, result)
            connection = open_runtime_connection(database)
            try:
                aggregate = connection.execute(
                    "SELECT model_state, brier_score, log_loss, calibration_error, accuracy FROM model_evaluations"
                ).fetchall()
                prediction = connection.execute(
                    """
                    SELECT prediction_timestamp, model_probability,
                           market_implied_probability, probability_difference,
                           model_version, dataset_version, feature_version
                    FROM model_evaluation_predictions
                    LIMIT 1
                    """
                ).fetchone()
                prediction_count = connection.execute("SELECT COUNT(*) FROM model_evaluation_predictions").fetchone()[0]
            finally:
                connection.close()
        self.assertTrue(first["evaluation_inserted"])
        self.assertFalse(second["evaluation_inserted"])
        self.assertEqual(len(aggregate), 1)
        self.assertEqual(aggregate[0][0], "validated_research")
        self.assertEqual(prediction_count, 600)
        self.assertAlmostEqual(prediction[3], prediction[1] - prediction[2])
        self.assertEqual(prediction[4], "candidate-v1")
        self.assertTrue(prediction[5].startswith("sha256:"))


if __name__ == "__main__":
    unittest.main()
