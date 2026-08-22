import unittest
from decimal import Decimal

from kalshi_research_bot.math.devig import (
    DEVIG_METHODS,
    additive_probabilities,
    booksum,
    compare_methods,
    method_disagreement,
    multiplicative_probabilities,
    odds_ratio_probabilities,
    overround,
    power_probabilities,
    remove_margin,
    shin_probabilities,
    solver_cache_info,
    clear_solver_cache,
)


def american_implied(odds: int) -> Decimal:
    value = Decimal(str(odds))
    if value < 0:
        return abs(value) / (abs(value) + Decimal(100))
    return Decimal(100) / (value + Decimal(100))


BALANCED = [american_implied(-110), american_implied(-110)]
SKEWED = [american_implied(-900), american_implied(600)]
THREE_WAY = [Decimal("0.50"), Decimal("0.30"), Decimal("0.25")]
# A high-margin futures book with a genuine longshot. Additive de-vig subtracts a
# flat share from every selection, so it can only go non-positive when some
# selection is smaller than that share. In a two-way market that is impossible
# (it would need the longshot to be below the favourite minus one), which is why
# the failure has to be demonstrated on a multi-outcome book.
FUTURES = [
    Decimal("0.30"),
    Decimal("0.25"),
    Decimal("0.20"),
    Decimal("0.15"),
    Decimal("0.10"),
    Decimal("0.08"),
    Decimal("0.06"),
    Decimal("0.01"),
]


class DevigTest(unittest.TestCase):
    def test_every_method_returns_a_proper_distribution(self) -> None:
        for book in (BALANCED, SKEWED, THREE_WAY):
            for name, result in compare_methods(book).items():
                with self.subTest(method=name, book=book):
                    self.assertTrue(result.converged, f"{name} failed to converge")
                    self.assertEqual(len(result.probabilities), len(book))
                    self.assertAlmostEqual(float(sum(result.probabilities)), 1.0, places=12)
                    self.assertTrue(all(value > 0 for value in result.probabilities))

    def test_methods_agree_exactly_on_a_balanced_two_way_market(self) -> None:
        # With identical prices there is no favourite-longshot asymmetry to
        # resolve, so any disagreement would be a solver artifact.
        for name, result in compare_methods(BALANCED).items():
            with self.subTest(method=name):
                self.assertAlmostEqual(float(result.probabilities[0]), 0.5, places=9)
        self.assertAlmostEqual(float(method_disagreement(BALANCED)), 0.0, places=9)

    def test_shin_gives_the_favourite_more_than_proportional_normalization(self) -> None:
        # The core empirical claim behind preferring Shin: books load
        # proportionally more margin onto longshots, so removing it
        # proportionally leaves the favourite understated.
        proportional = multiplicative_probabilities(SKEWED).probabilities[0]
        shin = shin_probabilities(SKEWED).probabilities[0]
        self.assertGreater(shin, proportional)

    def test_method_choice_can_exceed_the_minimum_edge_gate_on_skewed_markets(self) -> None:
        # Documented in docs/sports-prediction-research-program.md: on a
        # -900/+600 market the de-vig assumption alone moves fair probability by
        # more than the one-cent edge the decision gate requires.
        self.assertGreater(method_disagreement(SKEWED), Decimal("0.01"))
        self.assertLess(method_disagreement(BALANCED), Decimal("0.0001"))

    def test_shin_reports_a_plausible_insider_share(self) -> None:
        result = shin_probabilities(SKEWED)
        self.assertIsNotNone(result.parameter)
        self.assertGreater(result.parameter, Decimal("0"))
        self.assertLess(result.parameter, Decimal("0.2"))

    def test_power_exponent_is_at_least_one_when_a_margin_exists(self) -> None:
        result = power_probabilities(THREE_WAY)
        self.assertGreaterEqual(result.parameter, Decimal("1"))

    def test_odds_ratio_parameter_is_below_one_when_a_margin_exists(self) -> None:
        result = odds_ratio_probabilities(THREE_WAY)
        self.assertLess(result.parameter, Decimal("1"))
        self.assertGreater(result.parameter, Decimal("0"))

    def test_booksum_and_overround_describe_the_margin(self) -> None:
        self.assertAlmostEqual(float(booksum(BALANCED)), 1.0476190476, places=8)
        self.assertAlmostEqual(float(overround(BALANCED)), 0.0476190476, places=8)

    def test_additive_flags_a_non_positive_longshot_instead_of_hiding_it(self) -> None:
        # The flat margin share (0.15 / 8) is larger than the longshot's 0.01.
        result = additive_probabilities(FUTURES)
        self.assertFalse(result.converged)
        self.assertIn("additive_produced_non_positive_probability", result.notes)

    def test_additive_cannot_fail_on_a_two_way_market(self) -> None:
        for book in (BALANCED, SKEWED):
            with self.subTest(book=book):
                self.assertTrue(additive_probabilities(book).converged)

    def test_remove_margin_falls_back_and_records_the_substitution(self) -> None:
        result = remove_margin(FUTURES, method="additive", fallback_method="multiplicative")
        self.assertEqual(result.method, "multiplicative")
        self.assertTrue(result.converged)
        self.assertIn("fell_back_from_additive", result.notes)

    def test_remove_margin_without_fallback_reports_the_failure(self) -> None:
        result = remove_margin(FUTURES, method="additive", fallback_method=None)
        self.assertFalse(result.converged)

    def test_market_without_a_margin_is_normalized_rather_than_solved(self) -> None:
        arbitrage = [Decimal("0.48"), Decimal("0.48")]
        for method in ("shin", "power", "odds_ratio"):
            with self.subTest(method=method):
                result = remove_margin(arbitrage, method=method)
                self.assertTrue(result.converged)
                self.assertIn("non_positive_overround_normalized", result.notes)
                self.assertAlmostEqual(float(result.probabilities[0]), 0.5, places=9)

    def test_invalid_markets_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            multiplicative_probabilities([Decimal("0.5")])
        with self.assertRaises(ValueError):
            multiplicative_probabilities([Decimal("0.5"), Decimal("0")])
        with self.assertRaises(ValueError):
            multiplicative_probabilities([Decimal("1.2"), Decimal("0.5")])
        with self.assertRaises(ValueError):
            remove_margin(BALANCED, method="not_a_method")

    def test_result_serializes_without_binary_float_loss(self) -> None:
        payload = shin_probabilities(THREE_WAY).as_dict()
        self.assertEqual(payload["method"], "shin")
        self.assertTrue(all(isinstance(value, str) for value in payload["probabilities"]))
        self.assertTrue(payload["converged"])

    def test_american_prices_convert_to_implied_probabilities(self) -> None:
        from kalshi_research_bot.math.devig import american_odds_to_implied

        self.assertAlmostEqual(float(american_odds_to_implied(-110)), 0.5238095238, places=9)
        self.assertAlmostEqual(float(american_odds_to_implied(100)), 0.5, places=9)
        self.assertAlmostEqual(float(american_odds_to_implied(600)), 0.1428571429, places=9)
        with self.assertRaises(ValueError):
            american_odds_to_implied(0)

    def test_decimal_prices_convert_to_implied_probabilities(self) -> None:
        from kalshi_research_bot.math.devig import decimal_odds_to_implied

        self.assertAlmostEqual(float(decimal_odds_to_implied(2.0)), 0.5, places=9)
        self.assertAlmostEqual(float(decimal_odds_to_implied(4.0)), 0.25, places=9)
        for invalid in (1.0, 0.5, 0):
            with self.subTest(odds=invalid):
                with self.assertRaises(ValueError):
                    decimal_odds_to_implied(invalid)

    def test_every_named_method_is_reachable(self) -> None:
        results = compare_methods(THREE_WAY)
        self.assertEqual(set(results), set(DEVIG_METHODS))


if __name__ == "__main__":
    unittest.main()


class SolverCacheTests(unittest.TestCase):
    """Remembering a solve must not change what the solve says."""

    def setUp(self) -> None:
        clear_solver_cache()

    def test_a_cached_solve_returns_the_same_numbers(self) -> None:
        prices = [Decimal("0.55"), Decimal("0.50")]
        for method in DEVIG_METHODS:
            with self.subTest(method=method):
                clear_solver_cache()
                first = remove_margin(list(prices), method=method)
                cached = remove_margin(list(prices), method=method)
                self.assertEqual(first.as_dict(), cached.as_dict())
                self.assertEqual(solver_cache_info()["hits"], 1)

    def test_different_markets_are_not_confused_for_each_other(self) -> None:
        one = remove_margin([Decimal("0.55"), Decimal("0.50")])
        two = remove_margin([Decimal("0.60"), Decimal("0.48")])
        self.assertNotEqual(one.probabilities, two.probabilities)
        self.assertEqual(solver_cache_info()["misses"], 2)

    def test_equal_values_of_different_scale_are_one_market(self) -> None:
        """Decimal("0.50") and Decimal("0.5") are the same probability."""
        remove_margin([Decimal("0.55"), Decimal("0.50")])
        remove_margin([Decimal("0.55"), Decimal("0.5")])
        self.assertEqual(solver_cache_info()["misses"], 1)
        self.assertEqual(solver_cache_info()["hits"], 1)

    def test_comparing_methods_reuses_the_solve_a_devig_already_did(self) -> None:
        prices = [Decimal("0.55"), Decimal("0.50")]
        remove_margin(list(prices), method="shin")
        before = solver_cache_info()["hits"]
        compare_methods(list(prices))
        # Four new methods, and the shin solve already done is reused.
        self.assertEqual(solver_cache_info()["hits"], before + 1)

    def test_the_cache_is_bounded(self) -> None:
        self.assertGreater(solver_cache_info()["maxsize"], 0)
