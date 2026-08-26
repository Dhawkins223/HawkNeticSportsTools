from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from kalshi_research_bot.connectors.polymarket import (
    cross_venue_gaps,
    normalize_polymarket_markets,
    probe_polymarket,
    render_polymarket_probe,
)


FETCHED_AT = "2026-08-20T18:00:00+00:00"


def _market(
    market_id: str = "512001",
    *,
    outcomes: str = '["Chiefs", "Bills"]',
    prices: str = '["0.62", "0.38"]',
    closed: bool = False,
    active: bool = True,
    **overrides: object,
) -> dict:
    row = {
        "id": market_id,
        "slug": "chiefs-vs-bills-2026-01-18",
        "question": "Will the Chiefs beat the Bills?",
        "conditionId": "0xabc123",
        "outcomes": outcomes,
        "outcomePrices": prices,
        "clobTokenIds": '["111", "222"]',
        "bestBid": "0.61",
        "bestAsk": "0.63",
        "spread": "0.02",
        "lastTradePrice": "0.62",
        "volumeNum": "184000.5",
        "liquidityNum": "22000",
        "gameStartTime": "2026-01-18T23:30:00Z",
        "startDate": "2026-01-11T00:00:00Z",
        "endDate": "2026-01-19T05:00:00Z",
        "closed": closed,
        "active": active,
    }
    row.update(overrides)
    return row


class PolymarketNormalizationTests(unittest.TestCase):
    def test_a_two_sided_market_normalizes_to_probabilities(self) -> None:
        result = normalize_polymarket_markets([_market()], api_fetched_at=FETCHED_AT)

        self.assertEqual(len(result.markets), 1)
        market = result.markets[0]
        self.assertEqual(market["venue"], "polymarket")
        self.assertEqual(market["market_id"], "512001")
        self.assertEqual(market["price_sum"], "1.00")
        self.assertEqual([entry["outcome"] for entry in market["outcomes"]], ["Chiefs", "Bills"])
        self.assertEqual(market["outcomes"][0]["normalized_probability"], "0.620000")
        self.assertEqual(market["outcomes"][0]["clob_token_id"], "111")
        self.assertEqual(market["game_start_time"], "2026-01-18T23:30:00+00:00")
        self.assertEqual(result.rejections, [])

    def test_prices_arrive_as_json_strings_and_are_decoded(self) -> None:
        """Gamma sends `outcomes` and `outcomePrices` as strings, not arrays."""
        as_strings = normalize_polymarket_markets([_market()], api_fetched_at=FETCHED_AT)
        as_arrays = normalize_polymarket_markets(
            [_market(outcomes=["Chiefs", "Bills"], prices=["0.62", "0.38"])],  # type: ignore[arg-type]
            api_fetched_at=FETCHED_AT,
        )
        self.assertEqual(
            [entry["normalized_probability"] for entry in as_strings.markets[0]["outcomes"]],
            [entry["normalized_probability"] for entry in as_arrays.markets[0]["outcomes"]],
        )

    def test_an_exchange_spread_is_normalized_without_a_devig_model(self) -> None:
        """The miss from one is the book's spread, not a bookmaker's margin."""
        result = normalize_polymarket_markets(
            [_market(prices='["0.63", "0.39"]')], api_fetched_at=FETCHED_AT
        )
        market = result.markets[0]
        self.assertEqual(market["normalization"], "multiplicative")
        self.assertEqual(market["price_sum"], "1.02")
        probabilities = [Decimal(entry["normalized_probability"]) for entry in market["outcomes"]]
        self.assertAlmostEqual(float(sum(probabilities)), 1.0, places=5)
        self.assertIn("not bookmaker margin", market["normalization_note"])

    def test_a_market_whose_prices_do_not_form_a_book_is_refused(self) -> None:
        result = normalize_polymarket_markets(
            [_market(prices='["0.20", "0.10"]')], api_fetched_at=FETCHED_AT
        )
        self.assertEqual(result.markets, [])
        self.assertEqual(result.rejection_counts(), {"price_sum_outside_two_sided_band": 1})

    def test_mismatched_outcomes_and_prices_are_refused_not_zipped(self) -> None:
        result = normalize_polymarket_markets(
            [_market(prices='["0.62"]')], api_fetched_at=FETCHED_AT
        )
        self.assertEqual(result.markets, [])
        self.assertEqual(result.rejection_counts(), {"outcome_price_length_mismatch": 1})

    def test_unparsable_and_missing_prices_are_named_separately(self) -> None:
        result = normalize_polymarket_markets(
            [
                _market("a", prices='["abc", "0.38"]'),
                _market("b", prices=None),  # type: ignore[arg-type]
            ],
            api_fetched_at=FETCHED_AT,
        )
        self.assertEqual(
            result.rejection_counts(),
            {"unparsable_price": 1, "missing_outcomes_or_prices": 1},
        )

    def test_closed_and_inactive_markets_are_excluded_by_default(self) -> None:
        rows = [_market("a", closed=True), _market("b", active=False), _market("c")]
        default = normalize_polymarket_markets(rows, api_fetched_at=FETCHED_AT)
        self.assertEqual([market["market_id"] for market in default.markets], ["c"])
        self.assertEqual(
            default.rejection_counts(), {"closed_market": 1, "inactive_market": 1}
        )

        including = normalize_polymarket_markets(rows, api_fetched_at=FETCHED_AT, include_closed=True)
        self.assertEqual(len(including.markets), 3)

    def test_a_payload_with_no_markets_says_so_rather_than_returning_empty(self) -> None:
        result = normalize_polymarket_markets({}, api_fetched_at=FETCHED_AT)
        self.assertEqual(result.markets, [])
        self.assertEqual(result.rejection_counts(), {"no_markets_in_payload": 1})

    def test_a_wrapped_payload_is_unwrapped(self) -> None:
        result = normalize_polymarket_markets({"data": [_market()]}, api_fetched_at=FETCHED_AT)
        self.assertEqual(len(result.markets), 1)

    def test_evidence_reports_what_was_normalized_and_what_was_refused(self) -> None:
        result = normalize_polymarket_markets(
            [_market("a"), _market("b", closed=True)], api_fetched_at=FETCHED_AT
        )
        evidence = result.evidence()
        self.assertEqual(evidence["normalized_market_count"], 1)
        self.assertEqual(evidence["rejection_count"], 1)
        self.assertEqual(evidence["rejection_reasons"], {"closed_market": 1})
        self.assertEqual(evidence["api_fetched_at"], FETCHED_AT)


class PolymarketProbeTests(unittest.TestCase):
    def test_the_probe_names_fields_the_live_response_never_carried(self) -> None:
        """Written against docs, not a response: the probe is how that gets checked."""
        # Marked as a sports market so the sports-only fields are judged at all;
        # Gamma sets `gameStartTime` on these and nothing else.
        stripped = _market(sportsMarketType="moneyline")
        del stripped["gameStartTime"]
        del stripped["bestBid"]
        with patch(
            "kalshi_research_bot.connectors.polymarket.fetch_polymarket_markets",
            return_value=([stripped], FETCHED_AT, 200, None),
        ):
            report = probe_polymarket()

        self.assertTrue(report["reachable"])
        self.assertEqual(report["markets_in_response"], 1)
        self.assertEqual(report["normalized_market_count"], 1)
        self.assertIn("gameStartTime", report["missing_everywhere"])
        self.assertIn("bestBid", report["missing_everywhere"])
        self.assertNotIn("outcomePrices", report["missing_everywhere"])
        self.assertIn("fields absent from every market", render_polymarket_probe(report))

    def test_sports_only_fields_are_not_judged_against_non_sports_markets(self) -> None:
        """A politics question has no kickoff, and that is not a mapping break.

        Gamma sets `gameStartTime` only on sports markets. Judging it against a
        sample of politics and crypto questions reported that the mapping needed
        updating when it did not, and a readiness check that cries wolf gets
        ignored on the day it is right.
        """
        politics = _market(question="Xi Jinping out before 2027?")
        del politics["gameStartTime"]
        with patch(
            "kalshi_research_bot.connectors.polymarket.fetch_polymarket_markets",
            return_value=([politics], FETCHED_AT, 200, None),
        ):
            report = probe_polymarket()

        self.assertEqual(report["sports_markets_in_response"], 0)
        self.assertTrue(report["sports_fields_unjudged"])
        self.assertNotIn("gameStartTime", report["missing_everywhere"])
        self.assertIn("sports-only fields were not judged", render_polymarket_probe(report))

    def test_a_sports_market_still_has_its_start_time_checked(self) -> None:
        with patch(
            "kalshi_research_bot.connectors.polymarket.fetch_polymarket_markets",
            return_value=([_market(sportsMarketType="moneyline")], FETCHED_AT, 200, None),
        ):
            report = probe_polymarket()

        self.assertEqual(report["sports_markets_in_response"], 1)
        self.assertFalse(report["sports_fields_unjudged"])
        self.assertEqual(report["missing_everywhere"], [])
        self.assertIn("every expected field appeared", render_polymarket_probe(report))

    def test_a_cached_body_is_not_accepted_as_a_live_probe(self) -> None:
        """A probe promises the source answered now, not that it once did.

        `HttpClient` caches responses and can be configured to serve a stale body
        when a request fails, so a probe that ignores those flags reports success
        without a request leaving the machine.
        """

        for flags, expected in (
            ({"from_cache": True}, "served_from_cache"),
            ({"stale": True, "stale_reason": "upstream_error"}, "stale_response:upstream_error"),
        ):
            with self.subTest(flags=flags):
                class _Response:
                    status = 200
                    fetched_at = FETCHED_AT
                    from_cache = flags.get("from_cache", False)
                    stale = flags.get("stale", False)
                    stale_reason = flags.get("stale_reason", "")

                    def json(self):
                        return [_market()]

                class _Client:
                    def get_text(self, url: str, timeout: int = 20):
                        return _Response()

                report = probe_polymarket(client=_Client())
                self.assertFalse(report["reachable"])
                self.assertEqual(report["error"], "response_not_live")
                self.assertEqual(report["error_detail"], expected)
                self.assertIn("unreachable", render_polymarket_probe(report))

    def test_a_live_response_still_passes(self) -> None:
        class _Response:
            status = 200
            fetched_at = FETCHED_AT
            from_cache = False
            stale = False
            stale_reason = ""

            def json(self):
                return [_market()]

        class _Client:
            def get_text(self, url: str, timeout: int = 20):
                return _Response()

        report = probe_polymarket(client=_Client())
        self.assertTrue(report["reachable"])
        self.assertEqual(report["normalized_market_count"], 1)

    def test_an_unreachable_host_is_reported_not_raised(self) -> None:
        with patch(
            "kalshi_research_bot.connectors.polymarket.fetch_polymarket_markets",
            side_effect=OSError("connection refused"),
        ):
            report = probe_polymarket()
        self.assertFalse(report["reachable"])
        self.assertEqual(report["error"], "OSError")
        self.assertIn("unreachable", render_polymarket_probe(report))


class CrossVenueTests(unittest.TestCase):
    def test_gaps_are_only_reported_where_the_caller_supplied_a_match(self) -> None:
        """Entity resolution across venues is E-49; this never guesses it."""
        result = normalize_polymarket_markets([_market()], api_fetched_at=FETCHED_AT)
        gaps = cross_venue_gaps(
            result.markets,
            {"polymarket:512001": Decimal("0.580000")},
            outcome_name="Chiefs",
        )
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["gap_probability"], "0.040000")

        self.assertEqual(cross_venue_gaps(result.markets, {}, outcome_name="Chiefs"), [])
        self.assertEqual(
            cross_venue_gaps(
                result.markets, {"polymarket:512001": Decimal("0.58")}, outcome_name="Nobody"
            ),
            [],
        )
