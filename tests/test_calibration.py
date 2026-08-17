import random
import unittest
from decimal import Decimal
from math import exp, log

from kalshi_research_bot.evaluation.calibration import (
    BetaCalibrator,
    IdentityCalibrator,
    IsotonicCalibrator,
    PlattCalibrator,
    calibration_report,
    calibration_slope_intercept,
    expected_calibration_error,
    log_loss,
    maximum_calibration_error,
    select_calibrator,
)


def _distorted(probability: float, factor: float) -> float:
    """Stretch a probability's logit. factor > 1 makes the model overconfident."""
    return 1.0 / (1.0 + exp(-log(probability / (1.0 - probability)) * factor))


def _sample(count: int, *, factor: float = 1.0, seed: int = 11) -> tuple[list[float], list[int]]:
    """Probabilities whose true generating rate is known, so the answer is known."""
    generator = random.Random(seed)
    truths = [generator.uniform(0.05, 0.95) for _ in range(count)]
    outcomes = [1 if generator.random() < truth else 0 for truth in truths]
    stated = [_distorted(truth, factor) for truth in truths]
    return stated, outcomes


class CalibrationMetricsTest(unittest.TestCase):
    def test_perfectly_calibrated_probabilities_score_near_slope_one(self) -> None:
        probabilities, outcomes = _sample(4000)
        report = calibration_report(probabilities, outcomes)
        self.assertAlmostEqual(float(report["calibration_slope"]), 1.0, delta=0.15)
        self.assertAlmostEqual(float(report["calibration_intercept"]), 0.0, delta=0.15)
        self.assertLess(float(report["expected_calibration_error"]), 0.03)

    def test_overconfidence_shows_up_as_a_slope_below_one(self) -> None:
        probabilities, outcomes = _sample(4000, factor=1.8)
        fit = calibration_slope_intercept(probabilities, outcomes)
        self.assertLess(float(fit["slope"]), 0.8)
        self.assertTrue(fit["converged"])

    def test_underconfidence_shows_up_as_a_slope_above_one(self) -> None:
        probabilities, outcomes = _sample(4000, factor=0.55)
        fit = calibration_slope_intercept(probabilities, outcomes)
        self.assertGreater(float(fit["slope"]), 1.2)

    def test_expected_calibration_error_grows_with_miscalibration(self) -> None:
        honest, outcomes = _sample(3000)
        skewed = [_distorted(value, 2.2) for value in honest]
        self.assertGreater(
            expected_calibration_error(skewed, outcomes),
            expected_calibration_error(honest, outcomes),
        )

    def test_maximum_calibration_error_is_at_least_the_average(self) -> None:
        probabilities, outcomes = _sample(2000, factor=1.6)
        self.assertGreaterEqual(
            maximum_calibration_error(probabilities, outcomes),
            expected_calibration_error(probabilities, outcomes),
        )

    def test_log_loss_punishes_confident_errors(self) -> None:
        self.assertGreater(log_loss([0.99], [0]), log_loss([0.6], [0]))
        self.assertAlmostEqual(float(log_loss([0.5, 0.5], [1, 0])), 0.6931471805, places=6)

    def test_metrics_reject_malformed_input(self) -> None:
        with self.assertRaises(ValueError):
            log_loss([0.5, 0.5], [1])
        with self.assertRaises(ValueError):
            log_loss([0.5], [2])
        with self.assertRaises(ValueError):
            log_loss([], [])


class CalibratorTest(unittest.TestCase):
    def test_platt_restores_a_stretched_model_to_slope_one(self) -> None:
        probabilities, outcomes = _sample(4000, factor=1.8)
        calibrated = PlattCalibrator().fit(probabilities, outcomes).predict(probabilities)
        fit = calibration_slope_intercept(calibrated, outcomes)
        self.assertAlmostEqual(float(fit["slope"]), 1.0, delta=0.1)
        self.assertLess(log_loss(calibrated, outcomes), log_loss(probabilities, outcomes))

    def test_beta_can_represent_the_identity_map(self) -> None:
        # The property that motivates beta calibration over Platt: recalibrating
        # an already-honest model must not distort it.
        probabilities, outcomes = _sample(4000)
        calibrated = BetaCalibrator().fit(probabilities, outcomes).predict(probabilities)
        drift = max(abs(float(new) - old) for new, old in zip(calibrated, probabilities))
        self.assertLess(drift, 0.1)

    def test_isotonic_output_is_monotone(self) -> None:
        probabilities, outcomes = _sample(3000, factor=1.5)
        calibrator = IsotonicCalibrator().fit(probabilities, outcomes)
        grid = [0.05, 0.2, 0.4, 0.6, 0.8, 0.95]
        predicted = [float(value) for value in calibrator.predict(grid)]
        self.assertEqual(predicted, sorted(predicted))

    def test_identity_returns_its_input(self) -> None:
        calibrated = IdentityCalibrator().predict([Decimal("0.25"), Decimal("0.75")])
        self.assertAlmostEqual(float(calibrated[0]), 0.25, places=9)
        self.assertAlmostEqual(float(calibrated[1]), 0.75, places=9)

    def test_unfitted_calibrators_refuse_to_predict(self) -> None:
        for calibrator in (PlattCalibrator(), BetaCalibrator(), IsotonicCalibrator()):
            with self.subTest(calibrator=calibrator.name):
                with self.assertRaises(RuntimeError):
                    calibrator.predict([0.5])


class CalibratorSelectionTest(unittest.TestCase):
    def test_an_already_calibrated_model_is_left_alone(self) -> None:
        probabilities, outcomes = _sample(3000)
        selection = select_calibrator(probabilities, outcomes)
        self.assertEqual(selection.method, "identity")

    def test_a_miscalibrated_model_is_corrected(self) -> None:
        probabilities, outcomes = _sample(3000, factor=1.9)
        selection = select_calibrator(probabilities, outcomes)
        self.assertNotEqual(selection.method, "identity")
        self.assertLess(
            selection.out_of_fold_log_loss[selection.method],
            selection.out_of_fold_log_loss["identity"],
        )

    def test_small_samples_are_not_calibrated_at_all(self) -> None:
        probabilities, outcomes = _sample(80, factor=2.0)
        selection = select_calibrator(probabilities, outcomes)
        self.assertEqual(selection.method, "identity")
        self.assertIn("insufficient_rows", selection.reason)

    def test_isotonic_is_withheld_below_its_row_threshold(self) -> None:
        probabilities, outcomes = _sample(400, factor=1.8)
        selection = select_calibrator(probabilities, outcomes)
        self.assertNotIn("isotonic", selection.out_of_fold_log_loss)

    def test_isotonic_is_offered_once_there_are_enough_rows(self) -> None:
        probabilities, outcomes = _sample(2000, factor=1.8)
        selection = select_calibrator(probabilities, outcomes)
        self.assertIn("isotonic", selection.out_of_fold_log_loss)

    def test_single_class_outcomes_are_not_calibrated(self) -> None:
        selection = select_calibrator([0.6] * 300, [1] * 300)
        self.assertEqual(selection.method, "identity")
        self.assertEqual(selection.reason, "single_outcome_class")

    def test_selection_serializes_for_the_model_registry(self) -> None:
        probabilities, outcomes = _sample(3000, factor=1.9)
        payload = select_calibrator(probabilities, outcomes).as_dict()
        self.assertIn("method", payload)
        self.assertIn("parameters", payload)
        self.assertIn("identity", payload["out_of_fold_log_loss"])


if __name__ == "__main__":
    unittest.main()
