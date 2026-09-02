"""The composed-dashboard fixtures must carry what the real producers return.

`ComposedDashboardPanelTests` patches `safe_sports_board`,
`safe_sports_clv_report` and `build_research_record` with fixtures so the golden
render can draw panels that otherwise need a database. That is only worth
anything while the fixtures agree with the producers they stand in for.

The first draft of those fixtures did not. It emitted `best_price` where the
board emits `best_odds`, so every posted price on the rendered board came out as
"n/a" -- and the render test passed, because it only asked whether the markup
appeared. A fixture that quietly disagrees with its producer renders a different
page than production and calls it coverage.

So these tests run the real producers against a real database and assert the
fixtures carry every key that comes back. Keys are compared, not values: the
fixture is allowed to choose its own numbers, and required to keep the shape.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from kalshi_research_bot import browser_fixtures as fixtures
from kalshi_research_bot import research_record
from kalshi_research_bot.evaluation.model_validation import wilson_interval
from kalshi_research_bot.research_record import build_research_record, hit_rate_status
from kalshi_research_bot.sports_board import load_sports_board
from kalshi_research_bot.sports_clv import build_sports_clv_report
from kalshi_research_bot.sports_research import (
    log_sports_predictions,
    normalize_the_odds_api_payload,
)

from tests.postgres_support import PostgresTestCase


class FixtureContractTests(PostgresTestCase):
    def assert_carries(self, produced: Mapping[str, Any], fixture: Mapping[str, Any], where: str) -> None:
        """Every key the producer returns is present in the fixture."""

        missing = sorted(set(produced) - set(fixture))
        self.assertEqual(
            missing,
            [],
            f"{where}: fixture is missing keys the producer returns: {missing}",
        )

    def assert_invents_nothing(self, produced: Mapping[str, Any], fixture: Mapping[str, Any], where: str) -> None:
        """And invents none the producer does not.

        An invented key is how `best_price` survived: it looked deliberate, the
        renderer ignored it, and nothing pointed at the real name.
        """

        extra = sorted(set(fixture) - set(produced))
        self.assertEqual(
            extra,
            [],
            f"{where}: fixture carries keys the producer never returns: {extra}",
        )

    def seed_one_event(self) -> None:
        now = datetime.now(timezone.utc)
        fetched = now.isoformat()
        source = [
            {
                "id": "contract-1",
                "commence_time": (now + timedelta(hours=6)).isoformat(),
                "home_team": "Home Team",
                "away_team": "Away Team",
                "bookmakers": [
                    {
                        "key": "book_a",
                        "last_update": fetched,
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Home Team", "price": -135},
                                    {"name": "Away Team", "price": 115},
                                ],
                            },
                            {
                                "key": "totals",
                                "outcomes": [
                                    {"name": "Over", "price": -105, "point": 218.5},
                                    {"name": "Under", "price": -115, "point": 218.5},
                                ],
                            },
                        ],
                    },
                    {
                        "key": "book_b",
                        "last_update": fetched,
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Home Team", "price": -130},
                                    {"name": "Away Team", "price": 118},
                                ],
                            }
                        ],
                    },
                ],
            }
        ]
        log_sports_predictions(
            run_id="contract",
            payload={
                "asset_class": "sports",
                "model_version": "sports_odds_research_v1",
                "strategy": "pregame_odds_snapshot_v1",
                "generated_at": fetched,
                "records": normalize_the_odds_api_payload(
                    source, sport="americanfootball_nfl", league="nfl", api_fetched_at=fetched
                ),
            },
        )

    def test_the_sports_board_fixture_matches_the_board(self) -> None:
        self.seed_one_event()
        produced = load_sports_board()
        self.assertTrue(produced.get("is_current"), "seeded board is not current; contract not comparable")
        fixture = fixtures.make_fixture_sports_board()

        self.assert_carries(produced, fixture, "sports board")
        self.assert_invents_nothing(produced, fixture, "sports board")

        event, fixture_event = produced["events"][0], fixture["events"][0]
        self.assert_carries(event, fixture_event, "sports event")
        self.assert_invents_nothing(event, fixture_event, "sports event")

        market, fixture_market = event["markets"][0], fixture_event["markets"][0]
        self.assert_carries(market, fixture_market, "sports market")
        self.assert_invents_nothing(market, fixture_market, "sports market")

        selection = market["selections"][0]
        fixture_selection = fixture_market["selections"][0]
        self.assert_carries(selection, fixture_selection, "sports selection")
        self.assert_invents_nothing(selection, fixture_selection, "sports selection")

    def test_the_fixture_uses_the_normalised_market_type(self) -> None:
        """The board emits "moneyline"; "h2h" is the upstream API's word for it.

        A fixture carrying the raw key renders a market heading no board ever
        shows, which is the same class of drift as a wrong field name.
        """

        self.seed_one_event()
        produced = {
            market["market_type"]
            for event in load_sports_board()["events"]
            for market in event["markets"]
        }
        fixture = {
            market["market_type"]
            for event in fixtures.make_fixture_sports_board()["events"]
            for market in event["markets"]
        }
        self.assertTrue(
            fixture <= produced,
            f"fixture market types {sorted(fixture - produced)} are not names the board emits {sorted(produced)}",
        )

    def test_the_clv_fixture_matches_the_report(self) -> None:
        produced = build_sports_clv_report()
        fixture = fixtures.make_fixture_sports_clv_report()
        self.assert_carries(produced, fixture, "closing-line report")
        self.assert_invents_nothing(produced, fixture, "closing-line report")

    def test_the_research_record_fixture_matches_the_record(self) -> None:
        produced = build_research_record(payload={})
        fixture = fixtures.make_fixture_research_record()
        self.assert_carries(produced, fixture, "research record")
        self.assert_invents_nothing(produced, fixture, "research record")

        # Every track, not just the first. `render_research_record_panel`
        # iterates the whole list, so a fixture short of a track renders a panel
        # missing a card the product always shows -- which is exactly what
        # happened: the producer returns kalshi, crypto and sports, and this
        # fixture had two of the three while comparing only `tracks[0]`.
        produced_classes = [track["asset_class"] for track in produced["tracks"]]
        fixture_classes = [track["asset_class"] for track in fixture["tracks"]]
        self.assertEqual(
            sorted(fixture_classes),
            sorted(produced_classes),
            "fixture tracks do not cover the asset classes the producer returns",
        )

        by_class = {track["asset_class"]: track for track in fixture["tracks"]}
        for track in produced["tracks"]:
            where = f"research record track ({track['asset_class']})"
            self.assert_carries(track, by_class[track["asset_class"]], where)
            self.assert_invents_nothing(track, by_class[track["asset_class"]], where)

    def test_categorical_values_match_the_producer_not_just_the_keys(self) -> None:
        """Keys alone let a value drift to something the product never emits.

        `measure` carried "closing_line_value" while the report returns
        "probability_points_versus_closing_line" -- a key-only check passed it,
        and the fixture described a measure that does not exist. These fields
        name a thing rather than count one, so the fixture has to use the
        producer's word for it.
        """

        self.seed_one_event()
        board = load_sports_board()
        fixture_board = fixtures.make_fixture_sports_board()
        for field in ("board_state", "probability_source", "state_reason"):
            with self.subTest(field=field):
                self.assertEqual(fixture_board[field], board[field])

        market = board["events"][0]["markets"][0]
        fixture_market = fixture_board["events"][0]["markets"][0]
        for field in ("market_type", "no_vig_method", "consensus_method"):
            with self.subTest(field=field):
                self.assertEqual(fixture_market[field], market[field])

        self.assertEqual(
            fixtures.make_fixture_sports_clv_report()["measure"],
            build_sports_clv_report()["measure"],
        )

        # `hit_rate_status` names a thing the same way `measure` does, and it
        # drifted the same way: the fixture said "measured", a word the record
        # never returns for any row count. It is a pure function of the settled
        # win/loss count, so the fixture is checked against the producer's own
        # rule rather than against a string copied out of it.
        for track in fixtures.make_fixture_research_record()["tracks"]:
            with self.subTest(track=track["asset_class"]):
                self.assertEqual(
                    track["hit_rate_status"],
                    hit_rate_status(track["win_loss_count"]),
                )

    def test_the_record_fixture_repeats_no_prose_of_its_own(self) -> None:
        """The record's fixed strings are the producer's, not a paraphrase.

        Each of these was written out by hand once and said something slightly
        different: a `next_action` the record never returns, a `metric_guardrail`
        rewritten in the fixture's own words, and a `sample_gate_required` of 30
        against a gate of 100. None changes a key, so the shape tests passed and
        the golden page showed a policy the product does not state.
        """

        record = fixtures.make_fixture_research_record()
        self.assertEqual(record["metric_policy"], research_record.METRIC_POLICY)
        self.assertEqual(record["next_action"], research_record.NEXT_ACTION)

        specs = {str(spec["asset_class"]): spec for spec in research_record.TRACK_SPECS}
        self.assertEqual(
            sorted(track["asset_class"] for track in record["tracks"]),
            sorted(specs),
            "fixture tracks do not cover the producer's own spec list",
        )
        for track in record["tracks"]:
            spec = specs[track["asset_class"]]
            with self.subTest(track=track["asset_class"]):
                self.assertEqual(track["bot_name"], spec["bot_name"])
                self.assertEqual(track["dedupe_policy"], " + ".join(spec["dedupe_fields"]))
                self.assertEqual(
                    track["metric_guardrail"], research_record.TRACK_METRIC_GUARDRAIL
                )
                self.assertEqual(
                    track["sample_gate_required"],
                    research_record.MIN_SETTLED_WIN_LOSS_FOR_HIT_RATE,
                )

    def test_the_record_fixture_gates_its_hit_rate_the_way_the_record_does(self) -> None:
        """The numbers the record derives, derived the same way.

        A fixture free to pick its own hit rate can show one below the gate, or
        an interval that does not belong to its counts -- and the golden page
        would then demonstrate the platform breaking the rule it advertises.
        """

        gate = research_record.MIN_SETTLED_WIN_LOSS_FOR_HIT_RATE
        for track in fixtures.make_fixture_research_record()["tracks"]:
            settled, wins = track["win_loss_count"], track["wins"]
            with self.subTest(track=track["asset_class"]):
                self.assertEqual(settled, track["wins"] + track["losses"])
                expected_raw = round(wins / settled, 6) if settled else None
                self.assertEqual(track["observed_hit_rate_raw"], expected_raw)
                self.assertEqual(
                    track["observed_hit_rate"],
                    expected_raw if settled >= gate else None,
                    "a hit rate is shown for a sample the gate would withhold",
                )
                if settled:
                    low, high = wilson_interval(wins, settled)
                    self.assertEqual(
                        track["observed_hit_rate_interval"], [float(low), float(high)]
                    )
                else:
                    self.assertIsNone(track["observed_hit_rate_interval"])

    def test_the_board_fixture_does_not_contradict_itself(self) -> None:
        """Internal consistency the producer maintains and a hand-written
        fixture will not unless someone checks: a selection cannot name a book
        its market does not list, and the source age is the gap between the two
        timestamps beside it."""

        board = fixtures.make_fixture_sports_board()
        generated = datetime.fromisoformat(board["generated_at"])
        fetched = datetime.fromisoformat(board["latest_source_fetched_at"])
        self.assertEqual(
            board["source_age_seconds"],
            int((generated - fetched).total_seconds()),
            "source_age_seconds disagrees with the timestamps beside it",
        )

        for event in board["events"]:
            for market in event["markets"]:
                books = set(market["bookmakers"])
                for entry in market["selections"]:
                    with self.subTest(market=market["market_type"], selection=entry["selection"]):
                        self.assertIn(entry["best_bookmaker"], books)
                        self.assertIn(entry["worst_bookmaker"], books)
                        self.assertLessEqual(entry["quote_count"], len(books))

    def test_the_record_fixture_claims_the_status_the_producer_would(self) -> None:
        """Keys alone would let `status` drift to a value the panel colours
        differently, so this pins the value to the producer's own rule:

            status = "OK" if any(track["valid_rows"] for track in tracks) else "WATCH"

        The fixture's first track has valid rows, so the producer would say `OK`
        and the panel renders `good` rather than its `WATCH` warning. Applied to
        the fixture rather than to a database, because an empty database yields
        `WATCH` and would prove nothing about a fixture that carries rows.
        """

        record = fixtures.make_fixture_research_record()
        expected = "OK" if any(track["valid_rows"] for track in record["tracks"]) else "WATCH"
        self.assertEqual(record["status"], expected)
        self.assertEqual(record["status"], "OK")

    def test_an_empty_database_is_watch_which_is_why_the_rule_is_applied(self) -> None:
        """The rule above, confirmed against the producer at its other extreme."""

        self.assertEqual(build_research_record(payload={})["status"], "WATCH")


if __name__ == "__main__":
    import unittest

    unittest.main()
