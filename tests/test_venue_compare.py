import json
import unittest
from decimal import Decimal
from pathlib import Path

from kalshi_research_bot.connectors.polymarket import normalize_polymarket_markets
from kalshi_research_bot.venue_compare import (
    compare_venues,
    league_from_slug,
    market_is_two_way_moneyline,
    match_market_to_event,
    outcome_names,
    render_venue_comparison,
    slug_has_derivative_suffix,
    teams_correspond,
)

FIXTURE = Path(__file__).parent / "fixtures" / "polymarket_sports_markets.json"


def _markets():
    """Normalize the recorded live Gamma response the same way production does."""
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    return normalize_polymarket_markets(
        payload, api_fetched_at="2026-08-21T00:00:00+00:00", source_url="fixture"
    ).markets


def _market(slug: str):
    return next(market for market in _markets() if market.get("slug") == slug)


def _board(**overrides):
    event = {
        "event_id": "e1",
        "league": "mlb",
        "home_team": "Milwaukee Brewers",
        "away_team": "Atlanta Braves",
        "game_start_time": "2026-08-21T20:10:00+00:00",
        "markets": [
            {
                "market_type": "h2h",
                "no_vig_available": True,
                "overround": "0.040000",
                "no_vig_method_disagreement": "0.001000",
                "selections": [
                    {"selection": "Atlanta Braves", "no_vig_probability": "0.120000"},
                    {"selection": "Milwaukee Brewers", "no_vig_probability": "0.880000"},
                ],
            }
        ],
    }
    event.update(overrides)
    return {"board_state": "fresh", "events": [event]}


class TeamMatchingTest(unittest.TestCase):
    def test_identical_names_match(self) -> None:
        self.assertTrue(teams_correspond("Atlanta Braves", "Atlanta Braves"))

    def test_abbreviated_city_matches_on_nickname(self) -> None:
        self.assertTrue(teams_correspond("NY Yankees", "New York Yankees"))

    def test_punctuation_and_case_do_not_block_a_match(self) -> None:
        self.assertTrue(teams_correspond("st. louis cardinals", "St Louis Cardinals"))

    def test_three_letter_codes_never_match_by_containment(self) -> None:
        # The defect this rule exists for: "ATL" is a substring of every Atlanta
        # franchise, so containment matching paired an abbreviation-keyed spread
        # market with an unrelated moneyline.
        self.assertFalse(teams_correspond("ATL", "Atlanta Braves"))
        self.assertFalse(teams_correspond("CAR", "Carolina Panthers"))
        self.assertFalse(teams_correspond("NY", "New York Yankees"))

    def test_different_teams_do_not_match(self) -> None:
        self.assertFalse(teams_correspond("Atlanta Braves", "Atlanta Hawks"))
        self.assertFalse(teams_correspond("New York Yankees", "New York Mets"))

    def test_empty_names_do_not_match(self) -> None:
        self.assertFalse(teams_correspond("", "Atlanta Braves"))
        self.assertFalse(teams_correspond(None, None))


class SlugTest(unittest.TestCase):
    def test_league_comes_from_the_slug_head(self) -> None:
        self.assertEqual(league_from_slug("mlb-atl-mil-2026-08-21"), "mlb")
        self.assertEqual(league_from_slug("epl-bre-tot-2026-08-22-bre"), "epl")
        self.assertIsNone(league_from_slug(""))

    def test_a_plain_moneyline_slug_ends_at_the_date(self) -> None:
        self.assertFalse(slug_has_derivative_suffix("mlb-atl-mil-2026-08-21"))

    def test_derivative_slugs_carry_a_suffix(self) -> None:
        for slug in (
            "mlb-tor-nyy-2026-08-21-total-7pt5",
            "nfl-car-jax-2026-08-21-spread-away-1pt5",
            "epl-bre-tot-2026-08-22-bre",
        ):
            with self.subTest(slug=slug):
                self.assertTrue(slug_has_derivative_suffix(slug))

    def test_a_slug_without_a_date_is_not_called_a_derivative(self) -> None:
        self.assertFalse(slug_has_derivative_suffix("some-market-without-a-date"))


class MarketEquivalenceTest(unittest.TestCase):
    def test_a_real_moneyline_is_comparable(self) -> None:
        comparable, reason = market_is_two_way_moneyline(_market("mlb-atl-mil-2026-08-21"))
        self.assertTrue(comparable, reason)

    def test_totals_and_spreads_are_refused(self) -> None:
        for slug in ("mlb-tor-nyy-2026-08-21-total-7pt5", "nfl-car-jax-2026-08-21-spread-away-1pt5"):
            with self.subTest(slug=slug):
                comparable, reason = market_is_two_way_moneyline(_market(slug))
                self.assertFalse(comparable)
                self.assertTrue(reason.startswith("not_moneyline"), reason)

    def test_a_three_way_sport_collapsed_to_yes_no_is_refused(self) -> None:
        # "Will Brentford FC win on 2026-08-22?" - the No side carries the draw,
        # so its price is not a two-way moneyline probability.
        market = _market("epl-bre-tot-2026-08-22-bre")
        comparable, reason = market_is_two_way_moneyline(market)
        self.assertFalse(comparable)
        self.assertIn(reason, {"yes_no_market", "not_moneyline:slug_suffix"})

    def test_an_unsupported_league_is_refused_by_name(self) -> None:
        comparable, reason = market_is_two_way_moneyline(_market("atp-fritz-nakashi-2026-08-21"))
        self.assertFalse(comparable)
        self.assertEqual(reason, "unsupported_league:atp")

    def test_outcome_names_read_the_normalized_shape(self) -> None:
        names = outcome_names(_market("mlb-atl-mil-2026-08-21"))
        self.assertEqual(names, ["Atlanta Braves", "Milwaukee Brewers"])


class MatchingTest(unittest.TestCase):
    def test_a_market_matches_its_event_on_time_and_both_teams(self) -> None:
        event, basis = match_market_to_event(
            _market("mlb-atl-mil-2026-08-21"), _board()["events"]
        )
        self.assertIsNotNone(event)
        self.assertEqual(basis, "start_time_and_both_teams")

    def test_a_distant_start_time_blocks_the_match(self) -> None:
        board = _board(game_start_time="2026-08-22T20:10:00+00:00")
        event, reason = match_market_to_event(_market("mlb-atl-mil-2026-08-21"), board["events"])
        self.assertIsNone(event)
        self.assertEqual(reason, "no_event_matched")

    def test_one_matching_team_is_not_enough(self) -> None:
        board = _board(away_team="Atlanta Braves", home_team="Chicago Cubs")
        event, reason = match_market_to_event(_market("mlb-atl-mil-2026-08-21"), board["events"])
        self.assertIsNone(event)
        self.assertEqual(reason, "no_event_matched")

    def test_two_candidate_events_are_refused_rather_than_guessed(self) -> None:
        board = _board()
        duplicate = dict(board["events"][0])
        duplicate["event_id"] = "e2"
        events = board["events"] + [duplicate]
        event, reason = match_market_to_event(_market("mlb-atl-mil-2026-08-21"), events)
        self.assertIsNone(event)
        self.assertEqual(reason, "ambiguous_match")

    def test_a_market_without_a_start_time_is_refused(self) -> None:
        market = dict(_market("mlb-atl-mil-2026-08-21"))
        market["game_start_time"] = None
        event, reason = match_market_to_event(market, _board()["events"])
        self.assertIsNone(event)
        self.assertEqual(reason, "missing_game_start_time")

    def test_home_and_away_may_be_listed_in_either_order(self) -> None:
        board = _board(home_team="Atlanta Braves", away_team="Milwaukee Brewers")
        event, basis = match_market_to_event(_market("mlb-atl-mil-2026-08-21"), board["events"])
        self.assertIsNotNone(event)


class ComparisonTest(unittest.TestCase):
    def test_only_the_moneyline_is_compared_from_a_full_slate(self) -> None:
        report = compare_venues(_board(), _markets())

        self.assertEqual(report["matched_market_count"], 1)
        self.assertEqual(report["compared_selection_count"], 2)
        self.assertIn("unsupported_league:atp", report["excluded_counts"])

    def test_a_gap_above_the_threshold_is_flagged(self) -> None:
        # Board says 0.12 for Atlanta; the venue fixture says 0.085.
        report = compare_venues(_board(), _markets())
        gap = report["gaps"][0]

        self.assertEqual(report["exceeding_threshold_count"], 2)
        self.assertTrue(gap["exceeds_threshold"])
        self.assertAlmostEqual(abs(Decimal(gap["gap"])), Decimal("0.035"), places=6)

    def test_a_gap_below_execution_cost_is_not_flagged(self) -> None:
        # Move the board onto the venue's price; what remains is inside cost.
        board = _board()
        board["events"][0]["markets"][0]["selections"] = [
            {"selection": "Atlanta Braves", "no_vig_probability": "0.090000"},
            {"selection": "Milwaukee Brewers", "no_vig_probability": "0.910000"},
        ]
        report = compare_venues(board, _markets())

        self.assertEqual(report["compared_selection_count"], 2)
        self.assertEqual(report["exceeding_threshold_count"], 0)

    def test_the_threshold_includes_the_devig_disagreement(self) -> None:
        board = _board()
        board["events"][0]["markets"][0]["no_vig_method_disagreement"] = "0.500000"
        report = compare_venues(board, _markets())

        self.assertEqual(report["exceeding_threshold_count"], 0)
        self.assertGreater(Decimal(report["gaps"][0]["threshold"]), Decimal("0.5"))

    def test_an_event_without_a_devigged_moneyline_is_counted(self) -> None:
        board = _board(markets=[])
        report = compare_venues(board, _markets())

        self.assertEqual(report["compared_selection_count"], 0)
        self.assertEqual(report["excluded_counts"].get("board_has_no_devigged_moneyline"), 1)

    def test_an_empty_board_compares_nothing_and_says_so(self) -> None:
        report = compare_venues({"board_state": "empty", "events": []}, _markets())

        self.assertEqual(report["matched_market_count"], 0)
        self.assertEqual(report["compared_selection_count"], 0)
        self.assertGreater(report["polymarket_markets_considered"], 0)

    def test_the_report_never_calls_a_gap_an_edge(self) -> None:
        report = compare_venues(_board(), _markets())
        rendered = render_venue_comparison(report)

        self.assertIn("no gap here is a validated model edge", report["disclaimer"])
        self.assertIn("Cross-venue price comparison", rendered)
        self.assertIn("execution cost", rendered)


if __name__ == "__main__":
    unittest.main()
