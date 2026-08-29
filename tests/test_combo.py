import unittest
from math import asin, pi

from kalshi_research_bot.agents import ComboBot
from kalshi_research_bot.agents.combo_bot import _synthetic_cost_cents
from kalshi_research_bot.contracts import TotalLeg


class ComboTests(unittest.TestCase):
    def test_correlation_raises_the_joint_rather_than_lowering_it(self):
        """The sign the superseded penalty had backwards.

        Two standard normals both below their medians co-occur with probability
        ``1/4 + arcsin(rho)/(2*pi)``. That is a closed form, not a simulation
        result, and it says correlation moves a two-leg "both must hit"
        probability *up* from the 0.25 product. The old model multiplied by
        (1 - 0.03) and moved it down to 0.2425.
        """

        from kalshi_research_bot.slip_analysis import (
            CorrelationModel,
            SlipLeg,
            simulate_slip,
        )

        rho = 0.40
        exact = 0.25 + asin(rho) / (2 * pi)
        self.assertGreater(exact, 0.25)
        legs = [
            SlipLeg("a", "A", 2.0, 0.5, event_id="e1", market="m1"),
            SlipLeg("b", "B", 2.0, 0.5, event_id="e1", market="m2"),
        ]
        simulated = simulate_slip(
            legs, model=CorrelationModel(same_event=rho), draws=40_000, seed=11
        )["hit_probability"]
        self.assertAlmostEqual(simulated, exact, delta=0.01)

    def test_synthetic_cost_is_the_product_of_leg_prices(self):
        legs = [
            TotalLeg("a", "mlb", "MLB", "A", "A total", "over", 8.5, 0.95, 90),
            TotalLeg("b", "nba", "NBA", "B", "B total", "under", 220.5, 0.95, 80),
        ]
        # 0.90 * 0.80 = 0.72, so the pair costs 72c bought as one unit -- not
        # the 85c average of the two leg prices.
        self.assertAlmostEqual(_synthetic_cost_cents(legs), 72.0)

    def test_combo_bot_filters_to_target(self):
        legs = [
            TotalLeg("a", "mlb", "MLB", "A", "A total", "over", 8.5, 0.95, 90),
            TotalLeg("b", "nba", "NBA", "B", "B total", "under", 220.5, 0.95, 90),
            TotalLeg("c", "nfl", "NFL", "C", "C total", "over", 45.5, 0.70, 68),
        ]
        combos = ComboBot().build_ranked_combos(
            legs,
            target_probability=0.80,
            min_legs=2,
            max_legs=2,
            min_leg_probability=0.75,
        )
        self.assertEqual(len(combos), 1)
        self.assertTrue(combos[0].meets_target)

    def test_uncorrelated_combo_is_exact_not_simulated(self):
        """No relationship to model means the product is the answer.

        Legs with no shared event, team or slate have an all-zero correlation
        matrix, where the joint is exactly the product. Simulating it would
        replace an exact number with a noisy one, so the assertion here is
        exact equality rather than a tolerance.
        """

        legs = [
            TotalLeg("a", "mlb", "MLB", "A", "A total", "over", 8.5, 0.95, 90),
            TotalLeg("b", "nba", "NBA", "B", "B total", "under", 220.5, 0.90, 85),
        ]
        combos = ComboBot().build_ranked_combos(
            legs, target_probability=0.80, min_legs=2, max_legs=2, min_leg_probability=0.75
        )
        self.assertEqual(len(combos), 1)
        combo = combos[0]
        self.assertEqual(combo.adjusted_probability, 0.95 * 0.90)
        self.assertEqual(combo.correlation_adjustment, 0.0)
        self.assertIn("joint=exact_product_no_modelled_correlation", combo.notes)

    def test_same_event_combos_are_excluded_from_the_ranking(self):
        """Their expected value is not takeable, so they are not ranked.

        Correlation genuinely lifts a same-event combo's hit probability, but
        the value beside it comes from standalone leg prices and no book sells
        the combo at their product. Ranking on that would put the least
        achievable combos at the top.
        """

        legs = [
            TotalLeg("a", "nba", "NBA", "Lakers vs Suns", "Total", "over", 220.5, 0.95, 90),
            TotalLeg("b", "nba", "NBA", "Lakers vs Suns", "Spread", "home", -3.5, 0.95, 90),
        ]
        combos = ComboBot().build_ranked_combos(
            legs, target_probability=0.80, min_legs=2, max_legs=2, min_leg_probability=0.75
        )
        self.assertEqual(combos, [])

    def test_expected_value_is_fair_value_less_the_cost_as_a_unit(self):
        legs = [
            TotalLeg("a", "mlb", "MLB", "A", "A total", "over", 8.5, 0.95, 90),
            TotalLeg("b", "nba", "NBA", "B", "B total", "under", 220.5, 0.95, 90),
        ]
        combo = ComboBot().build_ranked_combos(
            legs, target_probability=0.80, min_legs=2, max_legs=2, min_leg_probability=0.75
        )[0]
        # Fair 100 * 0.95 * 0.95 = 90.25c against a cost of 100 * 0.9 * 0.9 = 81c.
        self.assertAlmostEqual(combo.fair_price_cents, 90.25)
        self.assertAlmostEqual(combo.synthetic_cost_cents, 81.0)
        self.assertAlmostEqual(combo.expected_value_cents, 9.25)

    def test_leg_with_no_upside_is_refused(self):
        """A contract at 100c has decimal odds of 1.0 and cannot contribute value."""

        legs = [
            TotalLeg("a", "mlb", "MLB", "A", "A total", "over", 8.5, 0.99, 100),
            TotalLeg("b", "nba", "NBA", "B", "B total", "under", 220.5, 0.95, 90),
        ]
        self.assertEqual(
            ComboBot().build_ranked_combos(
                legs, target_probability=0.80, min_legs=2, max_legs=2, min_leg_probability=0.75
            ),
            [],
        )

    def test_weakest_leg_bounds_the_combo(self):
        """Every leg must hit, so no combo can beat a target its weakest leg misses."""

        legs = [
            TotalLeg("a", "mlb", "MLB", "A", "A total", "over", 8.5, 0.99, 90),
            TotalLeg("b", "nba", "NBA", "B", "B total", "under", 220.5, 0.79, 70),
        ]
        self.assertEqual(
            ComboBot().build_ranked_combos(
                legs, target_probability=0.80, min_legs=2, max_legs=2, min_leg_probability=0.75
            ),
            [],
        )

    def test_incomplete_ranking_says_so(self):
        """A truncated candidate pool is declared, not silently returned as a full list."""

        legs = [
            TotalLeg(f"l{index}", "mlb", "MLB", f"E{index}", "Total", "over", 8.5, 0.99, 90)
            for index in range(12)
        ]
        combos = ComboBot().build_ranked_combos(
            legs,
            target_probability=0.90,
            min_legs=2,
            max_legs=3,
            max_results=5,
            min_leg_probability=0.75,
        )
        self.assertTrue(combos)
        self.assertTrue(
            any(note.startswith("ranking_refined_top=") for note in combos[0].notes)
        )


if __name__ == "__main__":
    unittest.main()
