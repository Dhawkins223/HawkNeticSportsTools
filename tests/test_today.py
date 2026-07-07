import unittest

from kalshi_research_bot.today import (
    all_day_candidate_legs,
    build_bet_candidates,
    build_all_day_slip,
    build_custom_slip,
    build_research_edge_slip,
    cents_from_dollars,
    date_key_from_iso,
    date_key_from_ticker,
    display_event_from_rules,
    enrich_combo_market,
    leg_risk_flags,
    midpoint_cents,
    overlap_key_for_leg,
    product_probability,
    repeated_event_penalty,
    required_leg_probability,
    side_quote_from_market,
    split_market_title,
)
from kalshi_research_bot.connectors.http import HttpResponse


class TodayTests(unittest.TestCase):
    def test_cents_from_dollars(self):
        self.assertEqual(cents_from_dollars("0.8750"), 87.5)
        self.assertIsNone(cents_from_dollars(""))

    def test_split_market_title(self):
        self.assertEqual(split_market_title("yes Over 1.5 goals, no Over 4.5 goals"), ["yes Over 1.5 goals", "no Over 4.5 goals"])

    def test_side_quote_from_market(self):
        market = {
            "yes_bid_dollars": "0.7900",
            "yes_ask_dollars": "0.8000",
            "no_bid_dollars": "0.2000",
            "no_ask_dollars": "0.2100",
        }
        quote = side_quote_from_market(market, "yes")
        self.assertEqual(quote["midpoint_cents"], 79.5)
        self.assertAlmostEqual(quote["market_implied_probability"], 0.795)

    def test_repeated_event_penalty(self):
        self.assertEqual(repeated_event_penalty(["a", "b"]), 0)
        self.assertGreater(repeated_event_penalty(["a", "a"]), 0)

    def test_product_probability(self):
        self.assertAlmostEqual(product_probability([0.8, 0.9]), 0.72)
        self.assertIsNone(product_probability([]))

    def test_midpoint_cents(self):
        self.assertEqual(midpoint_cents(79, 80), 79.5)
        self.assertEqual(midpoint_cents(None, 80), 80)

    def test_display_event_from_rules(self):
        rules = "If Detroit and Texas collectively score more 1.5 runs in the Detroit vs Texas professional baseball game originally scheduled for Jul 2, 2026 at 8:05 PM EDT, then the market resolves to Yes."
        self.assertEqual(display_event_from_rules(rules), "Detroit vs Texas")

    def test_build_bet_candidates_requires_edge_and_target(self):
        markets = [
            {
                "ticker": "A",
                "title": "yes Over",
                "real_data_ready": True,
                "adjusted_market_implied_probability": 0.85,
                "yes_ask_cents": 80,
                "combo_ev_cents": 5,
            },
            {
                "ticker": "B",
                "title": "yes Over",
                "real_data_ready": True,
                "adjusted_market_implied_probability": 0.70,
                "yes_ask_cents": 60,
                "combo_ev_cents": 10,
            },
        ]
        candidates = build_bet_candidates(markets)
        self.assertEqual([candidate["ticker"] for candidate in candidates], ["A"])

    def test_build_custom_slip_uses_multiple_sports(self):
        def leg(ticker, event, subtitle, probability):
            return {
                "market_ticker": ticker,
                "event_ticker": event,
                "side": "yes",
                "title": "Will this happen?",
                "subtitle": subtitle,
                "status": "active",
                "market_implied_probability": probability,
                "bid_cents": probability * 100 - 1,
                "ask_cents": probability * 100 + 1,
                "open_interest": "100",
                "volume_24h": "10",
            }

        markets = [
            {
                "leg_details": [
                    leg("KXMLBTOTAL-A", "A", "Over 3.5 runs scored", 0.95),
                    leg("KXWNBATOTAL-B", "B", "Over 152.5 points scored", 0.94),
                    leg("KXWCTOTAL-C", "C", "Reg Time: Over 0.5 goals scored", 0.93),
                    leg("KXMLBTOTAL-D", "D", "Over 4.5 runs scored", 0.92),
                ]
            }
        ]
        slip = build_custom_slip(markets, target_probability=0.80, min_legs=3, max_legs=4)
        self.assertEqual(slip["action"], "BUILD_SLIP")
        self.assertGreaterEqual(len(slip["sports"]), 2)
        self.assertEqual(slip["leg_count"], 4)
        self.assertTrue(all(leg["probability"] >= 0.80 for leg in slip["legs"]))
        self.assertTrue(slip["overlap_safe"])

    def test_build_custom_slip_blocks_same_game_overlap(self):
        def leg(ticker, event, subtitle, probability):
            return {
                "market_ticker": ticker,
                "event_ticker": event,
                "side": "yes",
                "title": "Will this happen?",
                "subtitle": subtitle,
                "status": "active",
                "market_implied_probability": probability,
                "bid_cents": probability * 100 - 1,
                "ask_cents": probability * 100 + 1,
                "open_interest": "100",
                "volume_24h": "10",
            }

        markets = [
            {
                "leg_details": [
                    leg("KXMLBTOTAL-26JUL022005DETTEX-5", "A", "Over 4.5 runs scored", 0.80),
                    leg("KXMLBSPREAD-26JUL022005DETTEX-DET4", "B", "Detroit wins by over 3.5 runs", 0.81),
                    leg("KXWCTOTAL-26JUL02ESPAUT-2", "C", "Reg Time: Over 1.5 goals scored", 0.82),
                ]
            }
        ]
        slip = build_custom_slip(markets, target_probability=0.80, min_legs=2, max_legs=3)
        self.assertEqual(slip["action"], "BUILD_SLIP")
        self.assertEqual(slip["leg_count"], 2)
        self.assertTrue(slip["overlap_safe"])
        self.assertEqual(slip["skipped_overlap_count"], 1)

    def test_overlap_key_normalizes_market_family(self):
        total = {
            "sport": "Pro Baseball",
            "market_ticker": "KXMLBTOTAL-26JUL022005DETTEX-5",
            "event_ticker": "KXMLBTOTAL-26JUL022005DETTEX",
        }
        spread = {
            "sport": "Pro Baseball",
            "market_ticker": "KXMLBSPREAD-26JUL022005DETTEX-DET4",
            "event_ticker": "KXMLBSPREAD-26JUL022005DETTEX",
        }
        self.assertEqual(overlap_key_for_leg(total), overlap_key_for_leg(spread))

    def test_flags_failed_miami_colorado_under_tail(self):
        leg = {
            "sport": "Pro Baseball",
            "market_ticker": "KXMLBTOTAL-26JUL021510MIACOL-17",
            "event_ticker": "KXMLBTOTAL-26JUL021510MIACOL",
            "display_event": "Miami vs Colorado",
            "side": "no",
            "subtitle": "Over 16.5 runs scored",
            "title": "Miami vs Colorado Total Runs?",
        }
        flags = leg_risk_flags(leg)
        self.assertIn("high_scoring_mlb_total_under_blocked", flags)
        self.assertIn("extreme_mlb_total_under_tail_risk", flags)
        self.assertIn("coors_or_colorado_total_under_tail_risk", flags)

    def test_high_scoring_colorado_over_requires_90_percent(self):
        leg = {
            "sport": "Pro Baseball",
            "market_ticker": "KXMLBTOTAL-26JUL021510MIACOL-8",
            "event_ticker": "KXMLBTOTAL-26JUL021510MIACOL",
            "display_event": "Miami vs Colorado",
            "side": "yes",
            "subtitle": "Over 7.5 runs scored",
            "title": "Miami vs Colorado Total Runs?",
        }
        self.assertEqual(required_leg_probability(leg, 0.80), 0.90)

    def test_high_scoring_non_colorado_over_requires_85_percent(self):
        leg = {
            "sport": "Pro Baseball",
            "market_ticker": "KXMLBTOTAL-26JUL021940TBKC-12",
            "event_ticker": "KXMLBTOTAL-26JUL021940TBKC",
            "display_event": "Tampa Bay vs Kansas City",
            "side": "yes",
            "subtitle": "Over 11.5 runs scored",
            "title": "Tampa Bay vs Kansas City Total Runs?",
        }
        self.assertEqual(required_leg_probability(leg, 0.80), 0.85)

    def test_build_custom_slip_excludes_failed_miami_colorado_pattern(self):
        def leg(ticker, event, subtitle, probability, side="yes"):
            return {
                "market_ticker": ticker,
                "event_ticker": event,
                "side": side,
                "title": "Will this happen?",
                "subtitle": subtitle,
                "status": "active",
                "market_implied_probability": probability,
                "bid_cents": probability * 100 - 1,
                "ask_cents": probability * 100 + 1,
                "open_interest": "100",
                "volume_24h": "10",
            }

        markets = [
            {
                "leg_details": [
                    leg("KXMLBTOTAL-26JUL021510MIACOL-17", "A", "Over 16.5 runs scored", 0.90, "no"),
                    leg("KXMLBTOTAL-26JUL022005DETTEX-5", "B", "Over 4.5 runs scored", 0.80),
                    leg("KXWCTOTAL-26JUL02ESPAUT-2", "C", "Reg Time: Over 1.5 goals scored", 0.82),
                ]
            }
        ]
        slip = build_custom_slip(markets, target_probability=0.80, min_legs=2, max_legs=3)
        selected_tickers = {leg["market_ticker"] for leg in slip["legs"]}
        self.assertNotIn("KXMLBTOTAL-26JUL021510MIACOL-17", selected_tickers)

    def test_build_custom_slip_excludes_colorado_over_below_90(self):
        def leg(ticker, event, subtitle, probability, side="yes"):
            return {
                "market_ticker": ticker,
                "event_ticker": event,
                "side": side,
                "title": "Will this happen?",
                "subtitle": subtitle,
                "status": "active",
                "market_implied_probability": probability,
                "bid_cents": probability * 100 - 1,
                "ask_cents": probability * 100 + 1,
                "open_interest": "100",
                "volume_24h": "10",
            }

        markets = [
            {
                "leg_details": [
                    leg("KXMLBTOTAL-26JUL021510MIACOL-8", "A", "Over 7.5 runs scored", 0.89),
                    leg("KXMLBTOTAL-26JUL022005DETTEX-5", "B", "Over 4.5 runs scored", 0.80),
                    leg("KXWCTOTAL-26JUL02ESPAUT-2", "C", "Reg Time: Over 1.5 goals scored", 0.82),
                ]
            }
        ]
        slip = build_custom_slip(markets, target_probability=0.80, min_legs=2, max_legs=3)
        selected_tickers = {leg["market_ticker"] for leg in slip["legs"]}
        self.assertNotIn("KXMLBTOTAL-26JUL021510MIACOL-8", selected_tickers)

    def test_date_key_from_ticker(self):
        self.assertEqual(date_key_from_ticker("KXMLBTOTAL-26JUL022005DETTEX-5"), "20260702")
        self.assertEqual(date_key_from_ticker("KXWCTOTAL-26JUL04PARFRA-2"), "20260704")

    def test_date_key_from_iso_uses_new_york_day(self):
        self.assertEqual(date_key_from_iso("2026-07-04T02:30:00Z"), "20260703")

    def test_all_day_candidate_legs_filters_same_day_probability_range(self):
        markets = [
            {
                "ticker": "KXBTC-26JUL03-A",
                "event_ticker": "KXBTC-26JUL03",
                "title": "Will Bitcoin finish above 100k?",
                "status": "open",
                "occurrence_datetime": "2026-07-03T20:00:00-04:00",
                "close_time": "2026-07-03T20:00:00-04:00",
                "updated_time": "2026-07-03T15:55:00-04:00",
                "_api_fetched_at": "2026-07-03T16:00:00-04:00",
                "yes_bid_dollars": "0.7600",
                "yes_ask_dollars": "0.7800",
                "no_bid_dollars": "0.2200",
                "no_ask_dollars": "0.2400",
                "open_interest_fp": "100",
                "volume_24h_fp": "20",
            },
            {
                "ticker": "KXBTC-26JUL04-A",
                "event_ticker": "KXBTC-26JUL04",
                "title": "Will Bitcoin finish above 110k?",
                "status": "open",
                "close_time": "2026-07-04T20:00:00-04:00",
                "yes_bid_dollars": "0.7600",
                "yes_ask_dollars": "0.7800",
            },
        ]
        legs = all_day_candidate_legs(markets, "20260703")
        self.assertEqual(len(legs), 1)
        self.assertEqual(legs[0]["market_ticker"], "KXBTC-26JUL03-A")
        self.assertEqual(legs[0]["sport"], "Crypto")
        self.assertAlmostEqual(legs[0]["probability"], 0.77)
        self.assertEqual(legs[0]["event_start_time"], "2026-07-03T20:00:00-04:00")
        self.assertEqual(legs[0]["market_close_time"], "2026-07-03T20:00:00-04:00")
        self.assertEqual(legs[0]["api_fetched_at"], "2026-07-03T16:00:00-04:00")
        self.assertEqual(legs[0]["source_updated_at"], "2026-07-03T15:55:00-04:00")

    def test_enrich_combo_market_maps_kalshi_timing_fields_to_leg_details(self):
        class FakeHttp:
            def get_text(self, url):
                payload = {
                    "market": {
                        "ticker": "MKT1",
                        "event_ticker": "EVT1",
                        "title": "Will over 3.5 runs be scored?",
                        "yes_sub_title": "Over 3.5 runs scored",
                        "no_sub_title": "No",
                        "rules_primary": "If Detroit and Texas collectively score more 3.5 runs in the Detroit vs Texas professional baseball game originally scheduled for Jul 3, 2026 at 8:00 PM EDT, then the market resolves to Yes.",
                        "status": "active",
                        "occurrence_datetime": "2026-07-04T00:00:00Z",
                        "close_time": "2026-07-04T00:00:00Z",
                        "expected_expiration_time": "2026-07-04T00:00:00Z",
                        "expiration_time": "2026-07-04T00:00:00Z",
                        "updated_time": "2026-07-03T19:55:00Z",
                        "volume_24h_fp": "100",
                        "open_interest_fp": "200",
                        "yes_bid_dollars": "0.8000",
                        "yes_ask_dollars": "0.8200",
                        "no_bid_dollars": "0.1800",
                        "no_ask_dollars": "0.2000",
                    }
                }
                import json

                return HttpResponse(url=url, status=200, text=json.dumps(payload), fetched_at="2026-07-03T19:56:00Z")

        combo = {"legs": [{"market_ticker": "MKT1", "side": "yes"}], "yes_ask_cents": 50}
        enriched = enrich_combo_market(FakeHttp(), combo, {})
        leg = enriched["leg_details"][0]
        self.assertEqual(leg["event_start_time"], "2026-07-04T00:00:00Z")
        self.assertEqual(leg["market_close_time"], "2026-07-04T00:00:00Z")
        self.assertEqual(leg["api_fetched_at"], "2026-07-03T19:56:00Z")
        self.assertEqual(leg["source_updated_at"], "2026-07-03T19:55:00Z")
        self.assertEqual(leg["market_ticker"], "MKT1")
        self.assertEqual(leg["event_ticker"], "EVT1")

    def test_build_all_day_slip_blocks_same_event_family(self):
        def market(ticker, event, title, probability):
            return {
                "ticker": ticker,
                "event_ticker": event,
                "title": title,
                "status": "open",
                "close_time": "2026-07-03T20:00:00-04:00",
                "yes_bid_dollars": f"{probability - 0.01:.4f}",
                "yes_ask_dollars": f"{probability + 0.01:.4f}",
                "no_bid_dollars": "0.1900",
                "no_ask_dollars": "0.2100",
                "open_interest_fp": "100",
                "volume_24h_fp": "20",
            }

        markets = [
            market("KXBTC-26JUL03-A", "KXBTC-26JUL03", "Bitcoin above 100k?", 0.76),
            market("KXBTC-26JUL03-B", "KXBTC-26JUL03", "Bitcoin above 90k?", 0.77),
            market("KXMLB-26JUL03-A", "KXMLB-26JUL03", "Baseball team wins?", 0.78),
        ]
        slip = build_all_day_slip(markets, "20260703", min_legs=2, max_legs=3)
        self.assertEqual(slip["action"], "BUILD_SLIP")
        self.assertEqual(slip["leg_count"], 2)
        self.assertTrue(slip["overlap_safe"])
        self.assertEqual(slip["skipped_overlap_count"], 1)

    def test_research_edge_slip_refuses_empty_market_universe(self):
        slip = build_research_edge_slip([], "20260703", [])
        self.assertEqual(slip["action"], "NO_SLIP")
        self.assertEqual(slip["evidence_signal_count"], 0)

    def test_research_edge_slip_builds_market_only_scout_mode(self):
        def market(ticker, event, title, probability):
            return {
                "ticker": ticker,
                "event_ticker": event,
                "title": title,
                "yes_sub_title": "Yes",
                "no_sub_title": "No",
                "status": "open",
                "close_time": "2026-07-03T20:00:00-04:00",
                "yes_bid_dollars": f"{probability - 0.01:.4f}",
                "yes_ask_dollars": f"{probability + 0.01:.4f}",
                "no_bid_dollars": "0.1000",
                "no_ask_dollars": "0.1200",
                "open_interest_fp": "500",
                "volume_24h_fp": "200",
            }

        markets = [
            market("KXBTC-26JUL03-A", "KXBTC-26JUL03A", "Bitcoin price up in next 15 mins?", 0.84),
            market("KXETH-26JUL03-A", "KXETH-26JUL03A", "Ethereum price up in next 15 mins?", 0.83),
            market("KXMLB-26JUL03-A", "KXMLB-26JUL03A", "Atlanta score over 2.5 runs?", 0.82),
            market("KXWEATHER-26JUL03-A", "KXWEATHER-26JUL03A", "NYC temperature above 90?", 0.81),
        ]
        slip = build_research_edge_slip(markets, "20260703", [], min_legs=4, max_legs=4)
        self.assertEqual(slip["action"], "BUILD_SLIP")
        self.assertEqual(slip["research_mode"], "market_only_scout")
        self.assertEqual(slip["evidence_signal_count"], 0)
        self.assertTrue(all(leg["evidence_count"] == 0 for leg in slip["legs"]))

    def test_research_edge_slip_builds_from_source_backed_signals(self):
        def market(ticker, event, title, probability):
            return {
                "ticker": ticker,
                "event_ticker": event,
                "title": title,
                "yes_sub_title": "Yes",
                "no_sub_title": "No",
                "status": "open",
                "close_time": "2026-07-03T20:00:00-04:00",
                "yes_bid_dollars": f"{probability - 0.01:.4f}",
                "yes_ask_dollars": f"{probability + 0.01:.4f}",
                "no_bid_dollars": "0.1800",
                "no_ask_dollars": "0.2000",
                "open_interest_fp": "500",
                "volume_24h_fp": "200",
            }

        markets = [
            market("KXBTC-26JUL03-A", "KXBTC-26JUL03A", "Bitcoin price up in next 15 mins?", 0.72),
            market("KXETH-26JUL03-A", "KXETH-26JUL03A", "Ethereum price up in next 15 mins?", 0.71),
            market("KXMLB-26JUL03-A", "KXMLB-26JUL03A", "Atlanta score over 2.5 runs?", 0.70),
            market("KXWEATHER-26JUL03-A", "KXWEATHER-26JUL03A", "NYC temperature above 90?", 0.69),
        ]
        signals = [
            {
                "source": "SourceA",
                "platform": "official",
                "url": "https://example.com/a",
                "source_type": "primary_source",
                "market_hint": "Bitcoin price up",
                "selection_hint": "yes",
                "model_probability": 0.91,
                "confidence": 0.9,
                "historical_wins": 80,
                "historical_total": 100,
                "source_quality": 0.95,
            },
            {
                "source": "SourceB",
                "platform": "official",
                "url": "https://example.com/b",
                "source_type": "primary_source",
                "market_hint": "Ethereum price up",
                "selection_hint": "yes",
                "model_probability": 0.90,
                "confidence": 0.9,
                "historical_wins": 80,
                "historical_total": 100,
                "source_quality": 0.95,
            },
            {
                "source": "SourceC",
                "platform": "official",
                "url": "https://example.com/c",
                "source_type": "primary_source",
                "market_hint": "Atlanta score over 2.5 runs",
                "selection_hint": "yes",
                "model_probability": 0.89,
                "confidence": 0.9,
                "historical_wins": 80,
                "historical_total": 100,
                "source_quality": 0.95,
            },
            {
                "source": "SourceD",
                "platform": "official",
                "url": "https://example.com/d",
                "source_type": "primary_source",
                "market_hint": "NYC temperature above 90",
                "selection_hint": "yes",
                "model_probability": 0.88,
                "confidence": 0.9,
                "historical_wins": 80,
                "historical_total": 100,
                "source_quality": 0.95,
            },
        ]
        slip = build_research_edge_slip(markets, "20260703", signals, min_legs=4, max_legs=4)
        self.assertEqual(slip["action"], "BUILD_SLIP")
        self.assertEqual(slip["leg_count"], 4)
        self.assertTrue(all(leg["evidence_count"] >= 1 for leg in slip["legs"]))
        self.assertTrue(all(leg["research_probability"] >= 0.76 for leg in slip["legs"]))


if __name__ == "__main__":
    unittest.main()
