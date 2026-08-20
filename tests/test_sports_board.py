from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kalshi_research_bot.database import connection_pool
from kalshi_research_bot.sports_board import (
    american_implied_probability,
    load_sports_board,
    summarize_sports_board,
)
from kalshi_research_bot.sports_research import log_sports_predictions, normalize_the_odds_api_payload

from tests.postgres_support import PostgresTestCase


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _odds_payload(
    *,
    start_offset_hours: float = 3,
    fetched_offset_minutes: float = 5,
    bookmakers: list[dict] | None = None,
    event_id: str = "g1",
) -> dict:
    now = _now()
    start = (now + timedelta(hours=start_offset_hours)).isoformat()
    fetched = (now - timedelta(minutes=fetched_offset_minutes)).isoformat()
    books = bookmakers if bookmakers is not None else [
        {
            "key": "book_a",
            "last_update": fetched,
            "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": -120}, {"name": "Away", "price": 100}]}],
        },
        {
            "key": "book_b",
            "last_update": fetched,
            "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": -130}, {"name": "Away", "price": 110}]}],
        },
    ]
    for book in books:
        book.setdefault("last_update", fetched)
    source = [
        {
            "id": event_id,
            "commence_time": start,
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": books,
        }
    ]
    records = normalize_the_odds_api_payload(source, sport="basketball_nba", league="nba", api_fetched_at=fetched)
    return {
        "asset_class": "sports",
        "model_version": "sports_odds_research_v1",
        "strategy": "pregame_odds_snapshot_v1",
        "generated_at": fetched,
        "records": records,
    }


class SportsBoardTests(PostgresTestCase):
    def test_empty_database_reports_unavailable_without_inventing_rows(self) -> None:
        board = load_sports_board()
        self.assertEqual(board["board_state"], "unavailable")
        self.assertEqual(board["state_reason"], "no_sports_rows_uploaded")
        self.assertFalse(board["is_current"])
        self.assertEqual(board["events"], [])
        self.assertEqual(board["event_count"], 0)

    def test_uploaded_rows_become_a_current_board(self) -> None:
        logged = log_sports_predictions(run_id="board", payload=_odds_payload())
        self.assertGreater(logged["logged_predictions"], 0)

        board = load_sports_board()
        self.assertEqual(board["board_state"], "fresh")
        self.assertTrue(board["is_current"])
        self.assertEqual(board["event_count"], 1)
        self.assertEqual(board["model_state"], "baseline_only")
        self.assertEqual(board["decision_status"], "track_only")

        event = board["events"][0]
        self.assertEqual(event["home_team"], "Home")
        self.assertEqual(event["league"], "nba")
        self.assertGreater(event["seconds_to_start"], 0)
        self.assertEqual(event["market_count"], 1)

    def test_best_price_per_selection_is_taken_across_bookmakers(self) -> None:
        log_sports_predictions(run_id="shop", payload=_odds_payload())
        market = load_sports_board()["events"][0]["markets"][0]
        selections = {entry["selection"]: entry for entry in market["selections"]}

        # book_a posts the better Home price (-120 beats -130); book_b the better Away price.
        self.assertEqual(selections["Home"]["best_bookmaker"], "book_a")
        self.assertEqual(Decimal(selections["Home"]["best_odds"]), Decimal("-120"))
        self.assertEqual(selections["Away"]["best_bookmaker"], "book_b")
        self.assertEqual(Decimal(selections["Away"]["best_odds"]), Decimal("110"))

        self.assertEqual(selections["Home"]["worst_bookmaker"], "book_b")
        self.assertEqual(selections["Away"]["worst_bookmaker"], "book_a")
        self.assertEqual(market["bookmaker_count"], 2)

    def test_line_shopping_gain_is_the_implied_probability_avoided(self) -> None:
        log_sports_predictions(run_id="gain", payload=_odds_payload())
        market = load_sports_board()["events"][0]["markets"][0]
        away = next(entry for entry in market["selections"] if entry["selection"] == "Away")

        expected = american_implied_probability(Decimal("100")) - american_implied_probability(Decimal("110"))
        self.assertEqual(Decimal(away["line_shopping_gain_probability"]), expected.quantize(Decimal("0.000001")))
        self.assertGreater(Decimal(away["line_shopping_gain_probability"]), 0)

    def test_no_vig_probabilities_sum_to_one_and_report_the_overround(self) -> None:
        log_sports_predictions(run_id="novig", payload=_odds_payload())
        market = load_sports_board()["events"][0]["markets"][0]
        self.assertTrue(market["no_vig_available"])

        fair = [Decimal(entry["no_vig_probability"]) for entry in market["selections"]]
        self.assertEqual(len(fair), 2)
        self.assertAlmostEqual(float(sum(fair)), 1.0, places=5)

        raw = [Decimal(entry["implied_probability"]) for entry in market["selections"]]
        self.assertEqual(Decimal(market["overround"]), (sum(raw) - Decimal(1)).quantize(Decimal("0.000001")))

    def test_consensus_devigs_each_book_before_taking_the_median(self) -> None:
        """The consensus is the market's estimate, not the shopper's.

        Best prices across books carry less margin than any single book posts,
        so de-vigging them reads as a fairer market than the books actually
        offer. The consensus de-vigs each book on its own first.
        """

        log_sports_predictions(run_id="consensus", payload=_odds_payload())
        market = load_sports_board()["events"][0]["markets"][0]

        self.assertTrue(market["consensus_available"])
        self.assertEqual(market["consensus_bookmakers"], ["book_a", "book_b"])
        self.assertEqual(market["consensus_method"], "per_book_shin_median")

        selections = {entry["selection"]: entry for entry in market["selections"]}
        consensus = [Decimal(entry["consensus_probability"]) for entry in selections.values()]
        self.assertAlmostEqual(float(sum(consensus)), 1.0, places=5)

        # The two readings are genuinely different numbers, not the same one
        # published twice: the shopper's de-vig starts from prices no single book
        # offers together.
        self.assertNotEqual(
            Decimal(selections["Home"]["no_vig_probability"]),
            Decimal(selections["Home"]["consensus_probability"]),
        )

        best_price_home = Decimal(selections["Home"]["implied_probability"])
        gap = Decimal(selections["Home"]["best_price_vs_consensus_probability"])
        self.assertAlmostEqual(
            float(gap),
            float(Decimal(selections["Home"]["consensus_probability"]) - best_price_home),
            places=5,
        )

        # Consensus probabilities sum to one and best prices sum to one plus the
        # shopper's overround, so the gaps must sum to exactly minus that
        # overround. Here every book still charges margin after shopping, so no
        # side comes out cheap and both gaps are negative.
        gaps = [Decimal(entry["best_price_vs_consensus_probability"]) for entry in selections.values()]
        self.assertAlmostEqual(float(sum(gaps)), -float(Decimal(market["overround"])), places=5)
        self.assertTrue(all(value < 0 for value in gaps))

    def test_a_book_off_the_market_shows_up_as_a_positive_gap(self) -> None:
        """The case the comparison exists for: one book has not moved.

        Two books price the home side near -180 while a third still shows -120.
        The best price then implies materially less probability than the books'
        own consensus, and the gap says so with a sign and a size.
        """

        payload = _odds_payload(
            bookmakers=[
                {
                    "key": book,
                    "markets": [
                        {
                            "key": "h2h",
                            "outcomes": [{"name": "Home", "price": home}, {"name": "Away", "price": away}],
                        }
                    ],
                }
                for book, home, away in (
                    ("book_a", -120, 100),
                    ("book_b", -180, 160),
                    ("book_c", -175, 155),
                )
            ]
        )
        log_sports_predictions(run_id="stale_book", payload=payload)

        market = load_sports_board()["events"][0]["markets"][0]
        selections = {entry["selection"]: entry for entry in market["selections"]}
        home = selections["Home"]

        self.assertEqual(market["consensus_bookmaker_count"], 3)
        self.assertEqual(home["best_bookmaker"], "book_a")
        gap = Decimal(home["best_price_vs_consensus_probability"])
        self.assertGreater(gap, Decimal("0.05"))
        self.assertLess(Decimal(home["implied_probability"]), Decimal(home["consensus_probability"]))

    def test_a_book_quoting_one_side_is_left_out_of_the_consensus(self) -> None:
        """A partial quote has no margin to remove, so it cannot be de-vigged."""

        payload = _odds_payload(
            bookmakers=[
                {
                    "key": "book_a",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": -120}, {"name": "Away", "price": 100}]}],
                },
                {
                    "key": "book_b",
                    "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": -130}, {"name": "Away", "price": 110}]}],
                },
            ]
        )
        payload["records"] = [
            record
            for record in payload["records"]
            if not (record["bookmaker"] == "book_b" and record["selection"] == "Away")
        ]
        log_sports_predictions(run_id="partial", payload=payload)

        market = load_sports_board()["events"][0]["markets"][0]
        self.assertEqual(market["consensus_bookmakers"], ["book_a"])
        self.assertEqual(market["consensus_bookmaker_count"], 1)
        self.assertIn("book_b", market["bookmakers"])

    def test_a_single_sided_market_has_no_consensus_at_all(self) -> None:
        payload = _odds_payload(
            bookmakers=[
                {"key": "book_a", "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": -120}, {"name": "Away", "price": 100}]}]}
            ]
        )
        payload["records"] = [record for record in payload["records"] if record["selection"] == "Home"]
        log_sports_predictions(run_id="oneside_consensus", payload=payload)

        market = load_sports_board()["events"][0]["markets"][0]
        self.assertFalse(market["consensus_available"])
        self.assertIsNone(market["selections"][0]["consensus_probability"])
        self.assertIsNone(market["selections"][0]["best_price_vs_consensus_probability"])

    def test_single_sided_market_reports_no_no_vig_probability(self) -> None:
        payload = _odds_payload(
            bookmakers=[
                {"key": "book_a", "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": -120}, {"name": "Away", "price": 100}]}]}
            ]
        )
        # Drop one side so the market can no longer be de-vigged.
        payload["records"] = [record for record in payload["records"] if record["selection"] == "Home"]
        log_sports_predictions(run_id="oneside", payload=payload)

        market = load_sports_board()["events"][0]["markets"][0]
        self.assertFalse(market["no_vig_available"])
        self.assertIsNone(market["overround"])
        self.assertIsNone(market["selections"][0]["no_vig_probability"])
        self.assertIsNotNone(market["selections"][0]["implied_probability"])

    def test_started_games_are_excluded_from_the_upcoming_board(self) -> None:
        log_sports_predictions(run_id="started", payload=_odds_payload(start_offset_hours=0.25, fetched_offset_minutes=1))
        # Twenty minutes on: the game has tipped off but the collector is still fresh.
        board = load_sports_board(now=_now() + timedelta(minutes=20))
        self.assertEqual(board["event_count"], 0)
        self.assertEqual(board["board_state"], "empty")
        self.assertFalse(board["is_current"])

    def test_stale_rows_are_withheld_rather_than_shown_as_current(self) -> None:
        log_sports_predictions(run_id="stale", payload=_odds_payload(start_offset_hours=48, fetched_offset_minutes=5))
        board = load_sports_board(now=_now() + timedelta(hours=6))

        self.assertEqual(board["board_state"], "stale")
        self.assertFalse(board["is_current"])
        self.assertEqual(board["events"], [])
        self.assertEqual(board["withheld_event_count"], 1)
        self.assertGreater(board["source_age_seconds"], board["stale_after_seconds"])

    def test_blocked_source_health_blocks_the_board(self) -> None:
        log_sports_predictions(run_id="blocked", payload=_odds_payload())
        with connection_pool(self.settings).connection() as connection:
            connection.execute(
                """
                INSERT INTO ops.source_health (
                    source, last_attempted_at, freshness_state, consecutive_failures, last_error, updated_at
                ) VALUES (%s, NOW(), 'blocked', 3, 'robots_disallowed', NOW())
                """,
                ("espn_scoreboard",),
            )

        board = load_sports_board()
        self.assertEqual(board["board_state"], "blocked")
        self.assertIn("robots_disallowed", board["state_reason"])
        self.assertEqual(board["events"], [])
        self.assertEqual(board["withheld_event_count"], 1)

    def test_exact_prices_are_serialized_as_fixed_point_strings(self) -> None:
        log_sports_predictions(run_id="exact", payload=_odds_payload())
        market = load_sports_board()["events"][0]["markets"][0]
        for entry in market["selections"]:
            self.assertIsInstance(entry["best_odds"], str)
            self.assertNotIn("e", entry["best_odds"].lower())
            self.assertIsInstance(entry["implied_probability"], str)
            Decimal(entry["best_odds"])
            Decimal(entry["implied_probability"])

    def test_repeated_collection_cycles_keep_one_current_quote_per_price(self) -> None:
        log_sports_predictions(run_id="cycle1", payload=_odds_payload())
        log_sports_predictions(run_id="cycle2", payload=_odds_payload(fetched_offset_minutes=1))

        board = load_sports_board()
        self.assertEqual(board["event_count"], 1)
        market = board["events"][0]["markets"][0]
        self.assertEqual(len(market["selections"]), 2)
        for entry in market["selections"]:
            self.assertEqual(entry["quote_count"], 2)

    def test_summary_counts_match_the_board(self) -> None:
        log_sports_predictions(run_id="summary", payload=_odds_payload())
        board = load_sports_board()
        summary = summarize_sports_board(board)

        self.assertTrue(summary["is_current"])
        self.assertEqual(summary["event_count"], 1)
        self.assertEqual(summary["market_count"], 1)
        self.assertEqual(summary["no_vig_market_count"], 1)
        self.assertEqual(summary["line_shopping_market_count"], 1)
        self.assertEqual(summary["next_event"]["home_team"], "Home")

    def test_spread_sides_are_paired_by_line_magnitude(self) -> None:
        payload = _odds_payload(
            bookmakers=[
                {
                    "key": "book_a",
                    "markets": [
                        {
                            "key": "spreads",
                            "outcomes": [
                                {"name": "Home", "price": -110, "point": -1.5},
                                {"name": "Away", "price": -110, "point": 1.5},
                            ],
                        }
                    ],
                }
            ]
        )
        log_sports_predictions(run_id="spread", payload=payload)

        markets = load_sports_board()["events"][0]["markets"]
        self.assertEqual(len(markets), 1, "mirrored spread sides must form one de-viggable market")
        market = markets[0]
        self.assertTrue(market["no_vig_available"])
        self.assertEqual(len(market["selections"]), 2)
        lines = {entry["selection"]: Decimal(entry["line"]) for entry in market["selections"]}
        self.assertEqual(lines["Home"], Decimal("-1.5"))
        self.assertEqual(lines["Away"], Decimal("1.5"))

    def test_dashboard_section_renders_withheld_states_without_leaking_rows(self) -> None:
        from kalshi_research_bot.paper_server import render_sports_section

        log_sports_predictions(run_id="hidden", payload=_odds_payload(start_offset_hours=48))
        stale_board = load_sports_board(now=_now() + timedelta(hours=6))
        rendered = render_sports_section(stale_board)

        self.assertIn("Sports odds are stale", rendered)
        self.assertNotIn("Home", rendered)
        self.assertIn("held back", rendered)

    def test_dashboard_section_renders_a_current_board(self) -> None:
        from kalshi_research_bot.paper_server import render_sports_section

        log_sports_predictions(run_id="render", payload=_odds_payload())
        rendered = render_sports_section(load_sports_board())

        self.assertIn("sports-board-list", rendered)
        self.assertIn("Away @ Home", rendered)
        self.assertIn("No-vig", rendered)
        self.assertIn("+110", rendered)

    def test_american_implied_probability_is_exact(self) -> None:
        self.assertEqual(american_implied_probability(Decimal("100")), Decimal("0.5"))
        self.assertEqual(american_implied_probability(Decimal("-100")), Decimal("0.5"))
        self.assertEqual(
            american_implied_probability(Decimal("-110")).quantize(Decimal("0.000001")),
            Decimal("0.523810"),
        )
        self.assertIsNone(american_implied_probability(Decimal("0")))
