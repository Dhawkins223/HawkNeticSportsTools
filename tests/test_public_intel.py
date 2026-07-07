import unittest

from kalshi_research_bot.agents import PublicIntelBot


class PublicIntelBotTests(unittest.TestCase):
    def test_blocks_private_or_untraceable_signals(self):
        bot = PublicIntelBot()
        summary = bot.build_summary(
            [],
            [
                {"source": "private", "platform": "discord", "is_public": False, "url": "https://example.com/private"},
                {"source": "missing-url", "platform": "x", "is_public": True},
            ],
        )
        self.assertEqual(summary["trusted_signal_count"], 0)
        self.assertEqual(summary["blocked_signal_count"], 2)

    def test_scores_and_matches_public_signal_to_leg(self):
        bot = PublicIntelBot()
        markets = [
            {
                "leg_details": [
                    {
                        "market_ticker": "KXMLBTOTAL-26JUL022005DETTEX-5",
                        "event_ticker": "KXMLBTOTAL-26JUL022005DETTEX",
                        "display_event": "Detroit vs Texas",
                        "subtitle": "Over 4.5 runs scored",
                        "title": "Detroit vs Texas Total Runs?",
                    }
                ]
            }
        ]
        summary = bot.build_summary(
            markets,
            [
                {
                    "source": "public-sharp",
                    "platform": "x",
                    "url": "https://example.com/post",
                    "is_public": True,
                    "market_hint": "Detroit vs Texas",
                    "selection_hint": "Over 4.5 runs",
                    "confidence": 0.8,
                    "historical_wins": 70,
                    "historical_total": 100,
                    "roi_percent": 5,
                }
            ],
            overlap_key_fn=lambda leg: "pro baseball:det-tex",
        )
        self.assertEqual(summary["trusted_signal_count"], 1)
        self.assertEqual(summary["top_matches"][0]["overlap_key"], "pro baseball:det-tex")
        self.assertGreater(summary["intel_by_overlap_key"]["pro baseball:det-tex"], 0)


if __name__ == "__main__":
    unittest.main()
