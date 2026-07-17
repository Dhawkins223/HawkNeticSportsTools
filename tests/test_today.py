import unittest

from kalshi_research_bot.combo_safety import VERIFIED_COMBO_EVIDENCE, VERIFIED_COMBO_SOURCE, combo_leg_signature
from kalshi_research_bot.today import (
    all_day_candidate_legs,
    build_bet_candidates,
    build_all_day_slip,
    build_combo_source_summary,
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


def _verified_combo_market(
    legs,
    *,
    ticker="KXMVECROSSCATEGORY-TEST",
    event_ticker="KXMVECROSSCATEGORY-TEST-EVENT",
    yes_ask_cents=50,
):
    signature = combo_leg_signature(legs)
    fetched_at = "2026-07-03T16:00:00Z"
    snapshot_hash = "sha256:test-combo-snapshot"
    enriched = []
    for leg in legs:
        enriched.append(
            {
                "event_start_time": "2026-07-03T20:00:00-04:00",
                "market_close_time": "2026-07-03T20:00:00-04:00",
                "api_fetched_at": fetched_at,
                "market_updated_at": "2026-07-03T15:55:00Z",
                **leg,
                "combo_market_ticker": ticker,
                "combo_event_ticker": event_ticker,
                "combo_market_status": "active",
                "combo_market_yes_ask_cents": yes_ask_cents,
                "combo_market_yes_bid_cents": max(1, yes_ask_cents - 1),
                "combo_market_fetched_at": fetched_at,
                "combo_market_snapshot_hash": snapshot_hash,
                "combo_market_leg_signature": signature,
                "combo_exact_leg_count": len(legs),
                "combo_evidence_status": VERIFIED_COMBO_EVIDENCE,
                "combo_source": VERIFIED_COMBO_SOURCE,
            }
        )
    return {
        "ticker": ticker,
        "event_ticker": event_ticker,
        "status": "active",
        "real_data_ready": True,
        "yes_bid_cents": max(1, yes_ask_cents - 1),
        "yes_ask_cents": yes_ask_cents,
        "api_fetched_at": fetched_at,
        "source_snapshot_hash": snapshot_hash,
        "leg_details": enriched,
    }


def _priced_leg(ticker, event, title, probability, *, subtitle=None, side="yes"):
    return {
        "market_ticker": ticker,
        "event_ticker": event,
        "side": side,
        "title": title,
        "subtitle": subtitle or title,
        "status": "active",
        "market_implied_probability": probability,
        "bid_cents": probability * 100 - 1,
        "ask_cents": probability * 100 + 1,
        "open_interest": "500",
        "volume_24h": "200",
        "source_updated_at": "2026-07-03T15:55:00-04:00",
    }


class TodayTests(unittest.TestCase):
    def test_combo_source_summary_keeps_loaded_contracts_distinct_from_tier_candidates(self):
        legs = [
            _priced_leg(
                f"MKT-{index}",
                f"EVT-{index}",
                "Over 3.5 runs scored",
                0.50,
            )
            for index in range(8)
        ]
        market = _verified_combo_market(legs)

        summary = build_combo_source_summary(
            [market],
            "20260703",
            primary_min_leg_probability=0.80,
            primary_max_leg_probability=0.985,
            primary_min_legs=8,
            primary_max_legs=20,
            leverage_min_leg_probability=0.75,
        )

        self.assertEqual(summary["active_kxmve_market_count"], 1)
        self.assertEqual(summary["verified_current_day_contract_count"], 1)
        self.assertEqual(summary["tiers"]["primary"]["eligible_exact_combo_count"], 0)
        self.assertEqual(summary["tiers"]["leverage"]["eligible_exact_combo_count"], 0)

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
            _verified_combo_market(
                [
                    leg("KXMLBTOTAL-A", "A", "Over 3.5 runs scored", 0.95),
                    leg("KXWNBATOTAL-B", "B", "Over 152.5 points scored", 0.94),
                    leg("KXWCTOTAL-C", "C", "Reg Time: Over 0.5 goals scored", 0.93),
                    leg("KXMLBTOTAL-D", "D", "Over 4.5 runs scored", 0.92),
                ]
            )
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
            _verified_combo_market(
                [
                    leg("KXMLBTOTAL-26JUL022005DETTEX-5", "A", "Over 4.5 runs scored", 0.80),
                    leg("KXMLBSPREAD-26JUL022005DETTEX-DET4", "B", "Detroit wins by over 3.5 runs", 0.81),
                    leg("KXWCTOTAL-26JUL02ESPAUT-2", "C", "Reg Time: Over 1.5 goals scored", 0.82),
                ]
            )
        ]
        slip = build_custom_slip(markets, target_probability=0.80, min_legs=2, max_legs=3)
        self.assertEqual(slip["action"], "NO_SLIP")
        self.assertEqual(slip["legs"], [])
        self.assertEqual(slip["eligible_combo_count"], 0)

    def test_custom_slip_excludes_manual_combo_ineligible_legs(self):
        def leg(ticker, event, subtitle, probability, *, ask_cents=None, status="active"):
            ask = probability * 100 + 1 if ask_cents is None else ask_cents
            return {
                "market_ticker": ticker,
                "event_ticker": event,
                "side": "yes",
                "title": "Will this happen?",
                "subtitle": subtitle,
                "status": status,
                "market_implied_probability": probability,
                "bid_cents": probability * 100 - 1,
                "ask_cents": ask,
                "open_interest": "100",
                "volume_24h": "10",
            }

        invalid_market = _verified_combo_market(
            [
                leg("KXMLBTOTAL-A", "A", "Over 3.5 runs scored", 0.82),
                leg("KXMLBTOTAL-D", "D", "Over 4.5 runs scored", 0.85, status="closed"),
            ],
            ticker="KXMVECROSSCATEGORY-INVALID",
        )
        invalid_market["leg_details"][0]["ask_cents"] = None
        valid_market = _verified_combo_market(
            [
                leg("KXWNBATOTAL-B", "B", "Over 152.5 points scored", 0.83),
                leg("KXWCTOTAL-C", "C", "Reg Time: Over 0.5 goals scored", 0.84),
            ],
            ticker="KXMVECROSSCATEGORY-VALID",
        )
        markets = [invalid_market, valid_market]
        slip = build_custom_slip(markets, target_probability=0.80, min_legs=2, max_legs=4)

        self.assertEqual(slip["action"], "BUILD_SLIP")
        selected_tickers = {leg["market_ticker"] for leg in slip["legs"]}
        self.assertNotIn("KXMLBTOTAL-A", selected_tickers)
        self.assertNotIn("KXMLBTOTAL-D", selected_tickers)
        self.assertEqual(selected_tickers, {"KXWNBATOTAL-B", "KXWCTOTAL-C"})
        self.assertEqual(slip["combo_compatibility"]["status"], "compatible")

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
            _verified_combo_market(
                [
                    leg("KXMLBTOTAL-26JUL021510MIACOL-17", "A", "Over 16.5 runs scored", 0.90, "no"),
                    leg("KXMLBTOTAL-26JUL022005DETTEX-5", "B", "Over 4.5 runs scored", 0.80),
                    leg("KXWCTOTAL-26JUL02ESPAUT-2", "C", "Reg Time: Over 1.5 goals scored", 0.82),
                ]
            )
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
            _verified_combo_market(
                [
                    leg("KXMLBTOTAL-26JUL021510MIACOL-8", "A", "Over 7.5 runs scored", 0.89),
                    leg("KXMLBTOTAL-26JUL022005DETTEX-5", "B", "Over 4.5 runs scored", 0.80),
                    leg("KXWCTOTAL-26JUL02ESPAUT-2", "C", "Reg Time: Over 1.5 goals scored", 0.82),
                ]
            )
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
            _verified_combo_market(
                [_priced_leg("KXBTC-26JUL03-A", "KXBTC-26JUL03", "Will Bitcoin finish above 100k?", 0.77)],
                ticker="KXMVECROSSCATEGORY-DAY3",
            ),
            _verified_combo_market(
                [_priced_leg("KXBTC-26JUL04-A", "KXBTC-26JUL04", "Will Bitcoin finish above 110k?", 0.77)],
                ticker="KXMVECROSSCATEGORY-DAY4",
            ),
        ]
        legs = all_day_candidate_legs(markets, "20260703")
        self.assertEqual(len(legs), 1)
        self.assertEqual(legs[0]["market_ticker"], "KXBTC-26JUL03-A")
        self.assertEqual(legs[0]["sport"], "Crypto")
        self.assertAlmostEqual(legs[0]["probability"], 0.77)
        self.assertEqual(legs[0]["event_start_time"], "2026-07-03T20:00:00-04:00")
        self.assertEqual(legs[0]["market_close_time"], "2026-07-03T20:00:00-04:00")
        self.assertEqual(legs[0]["api_fetched_at"], "2026-07-03T16:00:00Z")
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

        combo = {
            "ticker": "KXMVECROSSCATEGORY-TEST",
            "event_ticker": "KXMVECROSSCATEGORY-TEST-EVENT",
            "status": "active",
            "api_fetched_at": "2026-07-03T19:56:00Z",
            "source_snapshot_hash": "sha256:combo",
            "legs": [{"market_ticker": "MKT1", "side": "yes"}],
            "yes_bid_cents": 49,
            "yes_ask_cents": 50,
        }
        enriched = enrich_combo_market(FakeHttp(), combo, {})
        leg = enriched["leg_details"][0]
        self.assertEqual(leg["event_start_time"], "2026-07-04T00:00:00Z")
        self.assertEqual(leg["market_close_time"], "2026-07-04T00:00:00Z")
        self.assertEqual(leg["api_fetched_at"], "2026-07-03T19:56:00Z")
        self.assertEqual(leg["source_updated_at"], "2026-07-03T19:55:00Z")
        self.assertEqual(leg["market_ticker"], "MKT1")
        self.assertEqual(leg["event_ticker"], "EVT1")
        self.assertEqual(leg["combo_market_ticker"], "KXMVECROSSCATEGORY-TEST")
        self.assertEqual(leg["combo_evidence_status"], VERIFIED_COMBO_EVIDENCE)

    def test_build_all_day_slip_blocks_same_event_family(self):
        markets = [
            _verified_combo_market(
                [
                    _priced_leg("KXBTC-26JUL03-A", "KXBTC-26JUL03", "Bitcoin above 100k?", 0.76),
                    _priced_leg("KXBTC-26JUL03-B", "KXBTC-26JUL03", "Bitcoin above 90k?", 0.77),
                    _priced_leg("KXMLB-26JUL03-A", "KXMLB-26JUL03", "Baseball team wins?", 0.78),
                ]
            )
        ]
        slip = build_all_day_slip(markets, "20260703", min_legs=2, max_legs=3)
        self.assertEqual(slip["action"], "NO_SLIP")
        self.assertEqual(slip["legs"], [])

    def test_all_day_slip_can_mix_combo_eligible_categories(self):
        markets = [
            _verified_combo_market(
                [
                    _priced_leg("KXBTC-26JUL03-A", "KXBTC-26JUL03A", "Bitcoin above 100k?", 0.76),
                    _priced_leg("KXWEATHER-26JUL03-A", "KXWEATHER-26JUL03A", "NYC temperature above 90?", 0.77),
                    _priced_leg("KXMLB-26JUL03-A", "KXMLB-26JUL03A", "Baseball team wins?", 0.78),
                ]
            )
        ]
        slip = build_all_day_slip(markets, "20260703", min_legs=3, max_legs=3)

        self.assertEqual(slip["action"], "BUILD_SLIP")
        self.assertEqual(slip["combo_compatibility"]["status"], "compatible")
        self.assertTrue(slip["combo_compatibility"]["exact_listed_combo"])
        self.assertTrue(slip["combo_compatibility"]["can_mix_categories"])
        self.assertEqual(set(slip["combo_categories"]), {"Crypto", "Sports", "Weather"})
        self.assertTrue(all(leg["manual_entry"]["market_ticker"] for leg in slip["legs"]))

    def test_research_edge_slip_refuses_empty_market_universe(self):
        slip = build_research_edge_slip([], "20260703", [])
        self.assertEqual(slip["action"], "NO_SLIP")
        self.assertEqual(slip["evidence_signal_count"], 0)

    def test_research_edge_slip_builds_market_only_scout_mode(self):
        markets = [
            _verified_combo_market(
                [
                    _priced_leg("KXBTC-26JUL03-A", "KXBTC-26JUL03A", "Bitcoin price up in next 15 mins?", 0.84),
                    _priced_leg("KXETH-26JUL03-A", "KXETH-26JUL03A", "Ethereum price up in next 15 mins?", 0.83),
                    _priced_leg("KXMLB-26JUL03-A", "KXMLB-26JUL03A", "Atlanta score over 2.5 runs?", 0.82),
                    _priced_leg("KXWEATHER-26JUL03-A", "KXWEATHER-26JUL03A", "NYC temperature above 90?", 0.81),
                ]
            )
        ]
        slip = build_research_edge_slip(markets, "20260703", [], min_legs=4, max_legs=4)
        self.assertEqual(slip["action"], "BUILD_SLIP")
        self.assertEqual(slip["research_mode"], "market_only_scout")
        self.assertEqual(slip["evidence_signal_count"], 0)
        self.assertTrue(all(leg["evidence_count"] == 0 for leg in slip["legs"]))

    def test_research_edge_slip_builds_from_source_backed_signals(self):
        markets = [
            _verified_combo_market(
                [
                    _priced_leg("KXBTC-26JUL03-A", "KXBTC-26JUL03A", "Bitcoin price up in next 15 mins?", 0.72),
                    _priced_leg("KXETH-26JUL03-A", "KXETH-26JUL03A", "Ethereum price up in next 15 mins?", 0.71),
                    _priced_leg("KXMLB-26JUL03-A", "KXMLB-26JUL03A", "Atlanta score over 2.5 runs?", 0.70),
                    _priced_leg("KXWEATHER-26JUL03-A", "KXWEATHER-26JUL03A", "NYC temperature above 90?", 0.69),
                ]
            )
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
