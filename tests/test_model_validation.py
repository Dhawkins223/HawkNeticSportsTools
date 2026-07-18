from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kalshi_research_bot.evaluation.model_validation import (
    EvaluationRecord,
    calibration_buckets,
    dataset_version,
    detect_probability_drift,
    evaluate_category_model,
    leakage_failures,
    persist_category_evaluation,
    probability_metrics,
    time_aware_split,
    walk_forward_splits,
)

from tests.postgres_support import PostgresTestCase


def _records(count: int, *, category: str = "sports", model_probability=None) -> list[EvaluationRecord]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = []
    for index in range(count):
        outcome = 0 if index % 5 == 0 else 1
        probability = model_probability(outcome, index) if callable(model_probability) else model_probability
        rows.append(EvaluationRecord(
            record_id=f"record-{index}", category=category,
            prediction_timestamp=(start + timedelta(hours=index)).isoformat(),
            settlement_timestamp=(start + timedelta(hours=index + 2)).isoformat(),
            outcome=outcome, market_probability=0.58, model_probability=probability,
            model_version="candidate", feature_version="features-v1",
            features={"signal": index}, feature_observed_at={"signal": (start + timedelta(hours=index - 1)).isoformat()},
        ))
    return rows


class ModelValidationTests(PostgresTestCase):
    def test_metrics_splits_and_leakage_detection(self) -> None:
        metrics = probability_metrics([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0])
        split = time_aware_split(list(reversed(_records(20))))
        folds = walk_forward_splits(_records(20), minimum_train_rows=10, test_rows=4, step_rows=3)
        contaminated = _records(1)[0]
        contaminated = EvaluationRecord(**{**contaminated.__dict__, "features": {"final_score": "4-2"}})
        self.assertEqual(metrics["sample_size"], 4)
        self.assertLess(metrics["brier_score"], 0.03)
        self.assertLess(split["train"][-1].prediction_timestamp, split["validation"][0].prediction_timestamp)
        self.assertTrue(folds)
        self.assertIn("target_leakage_field:final_score", leakage_failures(contaminated))

    def test_out_of_sample_baseline_gate_and_persistence(self) -> None:
        rows = _records(600, model_probability=lambda outcome, _: 0.9 if outcome else 0.1)
        result = evaluate_category_model(rows, category="sports")
        persisted = persist_category_evaluation(rows, result)
        self.assertEqual(result["model_state"], "validated_research")
        self.assertTrue(persisted["evaluation_inserted"])
        self.assertGreater(self.query_one("SELECT COUNT(*) AS total FROM app.model_evaluation_predictions")["total"], 0)

    def test_mixed_categories_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "mixed_or_mismatched_categories"):
            evaluate_category_model(_records(10, category="crypto"), category="sports")

    def test_probability_metrics_include_scores_intervals_and_all_rows(self) -> None:
        metrics = probability_metrics([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0])
        self.assertEqual(metrics["sample_size"], 4)
        self.assertEqual(metrics["brier_score"], Decimal("0.025"))
        self.assertLess(metrics["log_loss"], Decimal("0.2"))
        self.assertEqual(metrics["accuracy"], Decimal("1"))
        self.assertEqual(len(metrics["accuracy_ci95"]), 2)
        self.assertEqual(sum(bucket["count"] for bucket in metrics["calibration_buckets"]), 4)

    def test_calibration_buckets_keep_empty_bucket_counts(self) -> None:
        buckets = calibration_buckets([0.15, 0.85], [0, 1])
        self.assertEqual(len(buckets), 10)
        self.assertEqual(sum(bucket["count"] for bucket in buckets), 2)
        self.assertTrue(any(bucket["count"] == 0 for bucket in buckets))

    def test_time_split_and_walk_forward_never_look_ahead(self) -> None:
        split = time_aware_split(list(reversed(_records(20))))
        folds = walk_forward_splits(_records(20), minimum_train_rows=10, test_rows=4, step_rows=3)
        self.assertLess(split["train"][-1].prediction_timestamp, split["validation"][0].prediction_timestamp)
        self.assertLess(split["validation"][-1].prediction_timestamp, split["test"][0].prediction_timestamp)
        self.assertTrue(folds)
        for fold in folds:
            self.assertLess(fold["train"][-1].prediction_timestamp, fold["test"][0].prediction_timestamp)

    def test_target_and_future_features_fail_validation(self) -> None:
        record = _records(1)[0]
        contaminated = EvaluationRecord(
            **{
                **record.__dict__,
                "features": {"signal": 1, "final_score": "4-2"},
                "feature_observed_at": {"signal": "2026-01-02T00:00:00+00:00"},
            }
        )
        failures = leakage_failures(contaminated)
        result = evaluate_category_model([contaminated, *_records(9)[1:]], category="sports", minimum_test_rows=1)
        self.assertIn("target_leakage_field:final_score", failures)
        self.assertIn("future_feature:signal", failures)
        self.assertEqual(result["model_state"], "failed_validation")
        self.assertEqual(result["reason"], "leakage_detected")

    def test_small_out_of_sample_set_cannot_be_marked_validated(self) -> None:
        result = evaluate_category_model(
            _records(100, model_probability=lambda outcome, _: 0.9 if outcome else 0.1),
            category="sports",
        )
        self.assertEqual(result["model_state"], "insufficient_sample")
        self.assertEqual(result["periods"]["test"]["sample_size"], 20)
        self.assertIn("market_implied", result["test_metrics"])

    def test_candidate_requires_out_of_sample_baseline_improvement(self) -> None:
        result = evaluate_category_model(
            _records(600, model_probability=lambda outcome, _: 0.9 if outcome else 0.1),
            category="sports",
        )
        self.assertEqual(result["model_state"], "validated_research")
        self.assertGreater(result["baseline_comparison"]["brier_improvement"], 0)
        self.assertGreater(result["baseline_comparison"]["log_loss_improvement"], 0)
        self.assertEqual(result["periods"]["test"]["sample_size"], 120)

    def test_poor_candidate_fails_market_baseline(self) -> None:
        result = evaluate_category_model(
            _records(
                600,
                model_probability=lambda outcome, index: (0.9 if outcome else 0.1)
                if index < 480
                else (0.1 if outcome else 0.9),
            ),
            category="sports",
        )
        self.assertEqual(result["model_state"], "failed_validation")
        self.assertEqual(result["reason"], "challenger_did_not_beat_market_baseline")

    def test_dataset_version_is_order_independent(self) -> None:
        records = _records(10)
        self.assertEqual(dataset_version(records), dataset_version(list(reversed(records))))

    def test_probability_drift_state_is_explicit(self) -> None:
        result = detect_probability_drift(
            [0.9, 0.8, 0.2, 0.1],
            [1, 1, 0, 0],
            [0.1, 0.2, 0.8, 0.9],
            [1, 1, 0, 0],
        )
        self.assertEqual(result["model_state"], "drift_detected")

    def test_evaluation_persistence_is_idempotent_and_keeps_probability_difference(self) -> None:
        rows = _records(600, model_probability=lambda outcome, _: 0.9 if outcome else 0.1)
        result = evaluate_category_model(rows, category="sports")
        first = persist_category_evaluation(rows, result)
        second = persist_category_evaluation(rows, result)
        row = self.query_one(
            "SELECT model_probability, market_implied_probability, probability_difference FROM app.model_evaluation_predictions LIMIT 1"
        )
        count = self.query_one("SELECT COUNT(*) AS total FROM app.model_evaluation_predictions")["total"]
        self.assertTrue(first["evaluation_inserted"])
        self.assertFalse(second["evaluation_inserted"])
        self.assertEqual(count, 600)
        self.assertEqual(row["probability_difference"], row["model_probability"] - row["market_implied_probability"])
