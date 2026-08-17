import unittest

from kalshi_research_bot.evaluation.power import (
    STANDARD_BREAK_EVEN,
    benjamini_hochberg,
    bonferroni,
    effective_sample_size,
    minimum_detectable_edge,
    normal_cdf,
    normal_quantile,
    p_value_from_interval,
    required_sample_for_edge,
    required_sample_for_score_improvement,
    review_experiment_significance,
    two_sided_p_value,
)


class NormalTest(unittest.TestCase):
    def test_quantiles_match_published_values(self) -> None:
        for probability, expected in (
            (0.975, 1.9599639845),
            (0.95, 1.6448536270),
            (0.80, 0.8416212336),
            (0.50, 0.0),
            (0.01, -2.3263478740),
        ):
            with self.subTest(probability=probability):
                self.assertAlmostEqual(normal_quantile(probability), expected, places=8)

    def test_quantile_and_cdf_are_inverses(self) -> None:
        for probability in (0.001, 0.05, 0.3, 0.5, 0.7, 0.95, 0.999):
            with self.subTest(probability=probability):
                self.assertAlmostEqual(normal_cdf(normal_quantile(probability)), probability, places=9)

    def test_quantile_rejects_degenerate_input(self) -> None:
        for probability in (0.0, 1.0, -0.1, 1.5):
            with self.subTest(probability=probability):
                with self.assertRaises(ValueError):
                    normal_quantile(probability)

    def test_two_sided_p_value_matches_known_points(self) -> None:
        self.assertAlmostEqual(two_sided_p_value(1.959963985), 0.05, places=8)
        self.assertAlmostEqual(two_sided_p_value(0.0), 1.0, places=12)


class SampleSizeTest(unittest.TestCase):
    def test_required_sample_scales_with_inverse_square_of_edge(self) -> None:
        # The defining property: halving the edge roughly quadruples the
        # evidence required.
        large = required_sample_for_edge(edge=0.02).required_sample
        small = required_sample_for_edge(edge=0.01).required_sample
        self.assertAlmostEqual(small / large, 4.0, delta=0.1)

    def test_required_sample_matches_the_documented_figures(self) -> None:
        # These exact numbers appear in docs/sports-prediction-research-program.md.
        self.assertEqual(required_sample_for_edge(edge=0.05).required_sample, 779)
        self.assertEqual(required_sample_for_edge(edge=0.02).required_sample, 4887)
        self.assertEqual(required_sample_for_edge(edge=0.01).required_sample, 19565)

    def test_a_season_sized_sample_cannot_detect_a_small_edge(self) -> None:
        # ~1,300 NBA games a season. The point of the whole module.
        self.assertGreater(minimum_detectable_edge(sample_size=1300), 0.03)

    def test_minimum_detectable_edge_shrinks_with_sample_size(self) -> None:
        self.assertGreater(
            minimum_detectable_edge(sample_size=300),
            minimum_detectable_edge(sample_size=25000),
        )

    def test_minimum_detectable_edge_inverts_required_sample(self) -> None:
        required = required_sample_for_edge(edge=0.02).required_sample
        detectable = minimum_detectable_edge(sample_size=required)
        self.assertAlmostEqual(detectable, 0.02, delta=0.002)

    def test_paired_score_improvement_needs_more_rows_for_noisier_differences(self) -> None:
        quiet = required_sample_for_score_improvement(mean_difference=0.002, difference_std=0.02)
        noisy = required_sample_for_score_improvement(mean_difference=0.002, difference_std=0.05)
        self.assertGreater(noisy.required_sample, quiet.required_sample)

    def test_sample_size_inputs_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            required_sample_for_edge(edge=0.0)
        with self.assertRaises(ValueError):
            required_sample_for_edge(edge=0.9, break_even_probability=0.9)
        with self.assertRaises(ValueError):
            required_sample_for_score_improvement(mean_difference=-0.1, difference_std=0.05)
        with self.assertRaises(ValueError):
            required_sample_for_score_improvement(mean_difference=0.1, difference_std=0.0)
        with self.assertRaises(ValueError):
            minimum_detectable_edge(sample_size=0)

    def test_break_even_default_matches_a_minus_110_price(self) -> None:
        self.assertAlmostEqual(STANDARD_BREAK_EVEN, 0.5238095238, places=9)


class ClusteringTest(unittest.TestCase):
    def test_correlated_observations_are_worth_less_than_their_count(self) -> None:
        effective = effective_sample_size(sample_size=1000, cluster_size=5, intraclass_correlation=0.3)
        self.assertLess(effective, 1000)
        self.assertAlmostEqual(effective, 1000 / 2.2, places=6)

    def test_independent_observations_are_not_discounted(self) -> None:
        self.assertEqual(effective_sample_size(sample_size=500, cluster_size=1, intraclass_correlation=0.9), 500)
        self.assertEqual(effective_sample_size(sample_size=500, cluster_size=8, intraclass_correlation=0.0), 500)

    def test_clustering_inputs_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            effective_sample_size(sample_size=-1, cluster_size=2, intraclass_correlation=0.1)
        with self.assertRaises(ValueError):
            effective_sample_size(sample_size=10, cluster_size=0.5, intraclass_correlation=0.1)
        with self.assertRaises(ValueError):
            effective_sample_size(sample_size=10, cluster_size=2, intraclass_correlation=1.5)


class MultipleTestingTest(unittest.TestCase):
    def test_benjamini_hochberg_matches_a_worked_example(self) -> None:
        adjusted = [test.adjusted_p_value for test in benjamini_hochberg([0.01, 0.02, 0.03, 0.04, 0.05])]
        for value in adjusted:
            self.assertAlmostEqual(value, 0.05, places=10)

    def test_benjamini_hochberg_enforces_monotonicity(self) -> None:
        tests = benjamini_hochberg([0.001, 0.5, 0.7])
        self.assertAlmostEqual(tests[0].adjusted_p_value, 0.003, places=10)
        self.assertAlmostEqual(tests[1].adjusted_p_value, 0.7, places=10)
        self.assertAlmostEqual(tests[2].adjusted_p_value, 0.7, places=10)
        self.assertTrue(tests[0].significant)
        self.assertFalse(tests[1].significant)

    def test_results_are_returned_in_input_order(self) -> None:
        tests = benjamini_hochberg([0.9, 0.001], labels=["late", "early"])
        self.assertEqual([test.label for test in tests], ["late", "early"])
        self.assertTrue(tests[1].significant)

    def test_a_lone_borderline_result_does_not_survive_a_large_family(self) -> None:
        # The backlog problem: one p=0.04 among fifty nulls is noise.
        p_values = [0.04] + [0.5] * 49
        tests = benjamini_hochberg(p_values)
        self.assertFalse(tests[0].significant)

    def test_bonferroni_is_stricter_than_benjamini_hochberg(self) -> None:
        p_values = [0.001, 0.01, 0.02, 0.04]
        strict = sum(test.significant for test in bonferroni(p_values))
        lenient = sum(test.significant for test in benjamini_hochberg(p_values))
        self.assertLessEqual(strict, lenient)

    def test_empty_families_are_handled(self) -> None:
        self.assertEqual(benjamini_hochberg([]), [])
        self.assertEqual(bonferroni([]), [])

    def test_correction_inputs_are_validated(self) -> None:
        with self.assertRaises(ValueError):
            benjamini_hochberg([0.5, 1.5])
        with self.assertRaises(ValueError):
            benjamini_hochberg([0.5], false_discovery_rate=0.0)
        with self.assertRaises(ValueError):
            benjamini_hochberg([0.5, 0.2], labels=["only_one"])


class IntervalScreeningTest(unittest.TestCase):
    def test_p_value_from_interval_is_small_when_zero_is_far_outside(self) -> None:
        self.assertLess(p_value_from_interval(0.003, [0.001, 0.005]), 0.01)

    def test_p_value_from_interval_is_large_when_zero_is_inside(self) -> None:
        self.assertGreater(p_value_from_interval(0.001, [-0.004, 0.006]), 0.5)

    def test_degenerate_intervals_return_none(self) -> None:
        self.assertIsNone(p_value_from_interval(0.01, [0.01, 0.01]))
        self.assertIsNone(p_value_from_interval(0.01, None))
        self.assertIsNone(p_value_from_interval(0.01, [0.05, 0.01]))


class RegistryReviewTest(unittest.TestCase):
    def _entry(self, hypothesis, decision, effect, interval):
        return {
            "hypothesis": hypothesis,
            "hypothesis_key": hypothesis.lower().replace(" ", "-"),
            "decision": decision,
            "effect_size": effect,
            "confidence_interval": interval,
        }

    def test_a_borderline_acceptance_is_demoted_by_the_family(self) -> None:
        # The realistic backlog failure: one result at p≈0.04 that looks
        # convincing alone, surrounded by the nulls it was selected out of. A
        # strong result in the same family still survives, so the correction is
        # discriminating rather than uniformly punitive.
        entries = [
            self._entry("strong effect", "accepted", 0.05, [0.04, 0.06]),
            self._entry("borderline effect", "accepted", 0.004, [0.0001, 0.0079]),
        ]
        entries += [self._entry(f"null {index}", "rejected", 0.001, [-0.004, 0.006]) for index in range(40)]
        review = review_experiment_significance(entries)

        self.assertEqual(review["family_size"], 42)
        by_hypothesis = {row["hypothesis"]: row for row in review["results"]}
        self.assertTrue(by_hypothesis["strong effect"]["significant"])
        self.assertFalse(by_hypothesis["borderline effect"]["significant"])
        self.assertEqual([row["hypothesis"] for row in review["demoted"]], ["borderline effect"])

    def test_a_strong_result_survives_correction(self) -> None:
        entries = [self._entry("strong", "accepted", 0.05, [0.04, 0.06])]
        entries += [self._entry(f"null {index}", "rejected", 0.0001, [-0.004, 0.0042]) for index in range(30)]
        review = review_experiment_significance(entries)

        self.assertEqual(review["demoted"], [])

    def test_entries_without_intervals_are_counted_not_dropped(self) -> None:
        entries = [
            self._entry("scored", "accepted", 0.02, [0.015, 0.025]),
            {"hypothesis": "unscored", "decision": "inconclusive", "effect_size": None, "confidence_interval": None},
        ]
        review = review_experiment_significance(entries)

        self.assertEqual(review["family_size"], 2)
        self.assertEqual(review["scored_count"], 1)
        self.assertEqual(review["unscored_count"], 1)

    def test_expected_false_positives_are_reported(self) -> None:
        entries = [self._entry(f"h{index}", "rejected", 0.001, [-0.001, 0.003]) for index in range(40)]
        review = review_experiment_significance(entries)
        self.assertAlmostEqual(review["expected_false_positives_uncorrected"], 2.0, places=6)

    def test_an_empty_registry_reviews_cleanly(self) -> None:
        review = review_experiment_significance([])
        self.assertEqual(review["family_size"], 0)
        self.assertEqual(review["results"], [])
        self.assertEqual(review["demoted"], [])


if __name__ == "__main__":
    unittest.main()
