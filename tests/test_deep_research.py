import unittest

from kalshi_research_bot.agents import DeepResearchBot


class DeepResearchBotTests(unittest.TestCase):
    def test_build_summary_tracks_tiers_and_market_scan(self):
        markets = [
            {
                "leg_details": [
                    {
                        "market_ticker": "KXMLBTOTAL-26JUL022005DETTEX-5",
                        "subtitle": "Over 4.5 runs scored",
                        "status": "active",
                        "market_implied_probability": 0.82,
                        "bid_cents": 81,
                        "ask_cents": 83,
                    },
                    {
                        "market_ticker": "KXWCTOTAL-26JUL02ESPAUT-2",
                        "subtitle": "Reg Time: Over 1.5 goals scored",
                        "status": "active",
                        "market_implied_probability": 0.76,
                        "bid_cents": 75,
                        "ask_cents": 77,
                    },
                ]
            }
        ]
        primary = {
            "action": "BUILD_SLIP",
            "min_leg_probability": 0.80,
            "leg_count": 1,
            "adjusted_probability": 0.82,
            "estimated_payout_if_right": 6.1,
        }
        leverage = {
            "action": "BUILD_SLIP",
            "min_leg_probability": 0.75,
            "leg_count": 2,
            "adjusted_probability": 0.62,
            "estimated_payout_if_right": 8.06,
        }
        summary = DeepResearchBot().build_summary(markets, primary, leverage)
        self.assertEqual(summary["status"], "ACTIVE")
        self.assertEqual(summary["market_scan"]["priced_legs"], 2)
        self.assertEqual(summary["slip_tiers"][1]["name"], "Leverage 75%")
        self.assertTrue(summary["research_queue"])


if __name__ == "__main__":
    unittest.main()
