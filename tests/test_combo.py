import unittest

from kalshi_research_bot.agents import ComboBot
from kalshi_research_bot.contracts import TotalLeg
from kalshi_research_bot.math import adjusted_combo_probability, combined_probability


class ComboTests(unittest.TestCase):
    def test_combined_probability_multiplies_legs(self):
        self.assertAlmostEqual(combined_probability([0.9, 0.9]), 0.81)

    def test_adjusted_probability_penalizes_same_context(self):
        raw, adjusted, penalty = adjusted_combo_probability([0.95, 0.95], ["mlb:a", "mlb:a"])
        self.assertAlmostEqual(raw, 0.9025)
        self.assertGreater(penalty, 0)
        self.assertLess(adjusted, raw)

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


if __name__ == "__main__":
    unittest.main()
