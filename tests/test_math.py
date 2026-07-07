import unittest

from kalshi_research_bot.math import (
    american_odds_to_probability,
    binary_no_vig_probability,
    buy_no_ev_cents,
    buy_yes_ev_cents,
    decimal_odds_to_probability,
    elo_home_probability,
    no_vig_probabilities,
    parlay_decimal_odds,
    poisson_home_win_probability,
    probability_to_american_odds,
    probability_to_decimal_odds,
    payout_for_stake,
    weighted_probability,
)


class MathTests(unittest.TestCase):
    def test_elo_probability_moves_with_rating(self):
        self.assertGreater(elo_home_probability(1600, 1500), 0.5)
        self.assertLess(elo_home_probability(1400, 1500), 0.5)

    def test_poisson_home_win_probability(self):
        self.assertGreater(poisson_home_win_probability(2.0, 1.0), 0.5)

    def test_weighted_probability(self):
        self.assertAlmostEqual(weighted_probability([(0.60, 2), (0.30, 1)]), 0.50)

    def test_expected_value(self):
        self.assertEqual(buy_yes_ev_cents(0.60, 55), 5.0)
        self.assertEqual(buy_no_ev_cents(0.40, 55), 5.0)

    def test_odds_conversion(self):
        self.assertAlmostEqual(decimal_odds_to_probability(2.0), 0.5)
        self.assertAlmostEqual(probability_to_decimal_odds(0.25), 4.0)
        self.assertAlmostEqual(american_odds_to_probability(-150), 0.6)
        self.assertEqual(probability_to_american_odds(0.6), -150)

    def test_no_vig_probability(self):
        self.assertEqual([round(value, 4) for value in no_vig_probabilities([0.55, 0.55])], [0.5, 0.5])
        self.assertAlmostEqual(binary_no_vig_probability(60, 45), 60 / 105)

    def test_payout_and_parlay_calculation(self):
        self.assertAlmostEqual(parlay_decimal_odds([0.8, 0.5]), 2.5)
        self.assertEqual(payout_for_stake(5, 0.20), 25.0)


if __name__ == "__main__":
    unittest.main()
