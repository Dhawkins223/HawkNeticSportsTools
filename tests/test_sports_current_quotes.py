"""The current-quote projection must never disagree with the log it summarizes.

`app.sports_current_quotes` exists so the board reads the slate instead of the
whole collection history. That is only safe while the projection says exactly
what the `DISTINCT ON` query it replaced would have said, so these tests exercise
the trigger against every transition that can change the answer, and check the
result against the original query rather than against a hand-written expectation.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kalshi_research_bot.sports_board import load_sports_board, verify_current_quotes
from kalshi_research_bot.sports_clv import capture_sports_closing_lines
from kalshi_research_bot.sports_research import (
    log_sports_predictions,
    normalize_the_odds_api_payload,
    settle_sports_predictions,
)

from tests.postgres_support import PostgresTestCase


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SportsCurrentQuotesTests(PostgresTestCase):
    def _log(
        self,
        *,
        home_price: int,
        away_price: int,
        event_id: str = "g1",
        bookmaker: str = "book_a",
        start_offset_hours: float = 3,
        collected_minutes_ago: float = 5,
        run_id: str = "quotes",
    ) -> dict:
        now = _now()
        starts_at = now + timedelta(hours=start_offset_hours)
        # A quote posted after kickoff is not a pre-game price and the collector
        # rejects it, so a game already under way is quoted just before it began.
        collected_at = min(now - timedelta(minutes=collected_minutes_ago), starts_at - timedelta(minutes=1))
        start = starts_at.isoformat()
        fetched = collected_at.isoformat()
        records = normalize_the_odds_api_payload(
            [
                {
                    "id": event_id,
                    "commence_time": start,
                    "home_team": "Home",
                    "away_team": "Away",
                    "bookmakers": [
                        {
                            "key": bookmaker,
                            "last_update": fetched,
                            "markets": [
                                {
                                    "key": "h2h",
                                    "outcomes": [
                                        {"name": "Home", "price": home_price},
                                        {"name": "Away", "price": away_price},
                                    ],
                                }
                            ],
                        }
                    ],
                }
            ],
            sport="basketball_nba",
            league="nba",
            api_fetched_at=fetched,
        )
        return log_sports_predictions(
            run_id=run_id,
            payload={
                "asset_class": "sports",
                "model_version": "sports_odds_research_v1",
                "strategy": "pregame_odds_snapshot_v1",
                "generated_at": fetched,
                "records": records,
            },
        )

    def _projection(self) -> dict[tuple[str, str], Decimal]:
        rows = self.query_all(
            """
            SELECT bookmaker, selection, odds
            FROM app.sports_current_quotes
            ORDER BY bookmaker, selection
            """
        )
        return {(str(row["bookmaker"]), str(row["selection"])): Decimal(str(row["odds"])) for row in rows}

    def test_a_new_quote_replaces_the_one_it_supersedes(self) -> None:
        self._log(home_price=-110, away_price=-110, collected_minutes_ago=30)
        self._log(home_price=-130, away_price=110, collected_minutes_ago=5)

        # Two collection cycles, four log rows, but only two current quotes.
        self.assertEqual(
            self.query_one("SELECT COUNT(*) AS total FROM app.sports_prediction_logs")["total"], 4
        )
        self.assertEqual(
            self._projection(),
            {("book_a", "Home"): Decimal("-130"), ("book_a", "Away"): Decimal("110")},
        )
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_a_late_arriving_older_quote_does_not_overwrite_a_newer_one(self) -> None:
        """Collection is not guaranteed to arrive in order; the projection is."""
        self._log(home_price=-130, away_price=110, collected_minutes_ago=5)
        self._log(home_price=-110, away_price=-110, collected_minutes_ago=45, run_id="late")

        self.assertEqual(
            self._projection(),
            {("book_a", "Home"): Decimal("-130"), ("book_a", "Away"): Decimal("110")},
        )
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_each_book_keeps_its_own_current_quote(self) -> None:
        self._log(home_price=-110, away_price=-110, bookmaker="book_a")
        self._log(home_price=-125, away_price=105, bookmaker="book_b")

        self.assertEqual(
            self._projection(),
            {
                ("book_a", "Home"): Decimal("-110"),
                ("book_a", "Away"): Decimal("-110"),
                ("book_b", "Home"): Decimal("-125"),
                ("book_b", "Away"): Decimal("105"),
            },
        )
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_settlement_removes_the_event_from_the_projection(self) -> None:
        self._log(home_price=-110, away_price=-110, start_offset_hours=-2)
        self.assertEqual(len(self._projection()), 2)

        settle_sports_predictions(
            run_id="quotes",
            finals_payload={
                "events": [
                    {
                        "event_id": "g1",
                        "home_team": "Home",
                        "away_team": "Away",
                        "home_score": 110,
                        "away_score": 100,
                        "status": "final",
                    }
                ]
            },
        )

        self.assertEqual(self._projection(), {})
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_a_rejected_row_never_becomes_a_current_quote(self) -> None:
        """Only a valid, unresolved row is a current quote."""
        self._log(home_price=-110, away_price=-110)
        before = self._projection()

        self.query_one(
            """
            UPDATE app.sports_prediction_logs
            SET validation_status = 'invalid', rejection_reason = 'test'
            WHERE selection = 'Home'
            RETURNING id
            """
        )

        after = self._projection()
        self.assertEqual(len(before), 2)
        self.assertEqual(list(after), [("book_a", "Away")])
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_invalidating_the_newest_snapshot_restores_the_one_it_superseded(self) -> None:
        """A quote does not disappear because its latest observation was rejected.

        Removing the newest snapshot leaves the previous one as the current
        quote, which is what the `DISTINCT ON` query returns. Dropping the
        projection row instead would hide a market the board should still show.
        """
        self._log(home_price=-110, away_price=-110, collected_minutes_ago=30)
        self._log(home_price=-130, away_price=110, collected_minutes_ago=5)
        self.assertEqual(
            self._projection(),
            {("book_a", "Home"): Decimal("-130"), ("book_a", "Away"): Decimal("110")},
        )

        self.query_one(
            """
            UPDATE app.sports_prediction_logs
            SET validation_status = 'invalid', rejection_reason = 'test'
            WHERE odds = -130
            RETURNING id
            """
        )

        self.assertEqual(
            self._projection(),
            {("book_a", "Home"): Decimal("-110"), ("book_a", "Away"): Decimal("110")},
        )
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_deleting_the_newest_snapshot_restores_the_one_it_superseded(self) -> None:
        self._log(home_price=-110, away_price=-110, collected_minutes_ago=30)
        self._log(home_price=-130, away_price=110, collected_minutes_ago=5)

        self.query_one("DELETE FROM app.sports_prediction_logs WHERE odds = 110 RETURNING id")

        self.assertEqual(
            self._projection(),
            {("book_a", "Home"): Decimal("-130"), ("book_a", "Away"): Decimal("-110")},
        )
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_settling_an_event_leaves_no_predecessor_behind(self) -> None:
        """Settlement takes every snapshot, so promotion must find nothing to promote."""
        self._log(home_price=-110, away_price=-110, start_offset_hours=-2, collected_minutes_ago=180)
        self._log(home_price=-130, away_price=110, start_offset_hours=-2, collected_minutes_ago=150)
        self.assertEqual(len(self._projection()), 2)

        settle_sports_predictions(
            run_id="quotes",
            finals_payload={
                "events": [
                    {
                        "event_id": "g1",
                        "home_team": "Home",
                        "away_team": "Away",
                        "home_score": 110,
                        "away_score": 100,
                        "status": "final",
                    }
                ]
            },
        )

        self.assertEqual(self._projection(), {})
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_deleting_a_superseded_snapshot_leaves_the_current_quote_alone(self) -> None:
        """Retention prunes old rows; that must not disturb the projection."""
        self._log(home_price=-110, away_price=-110, collected_minutes_ago=30)
        self._log(home_price=-130, away_price=110, collected_minutes_ago=5)
        before = self.query_all(
            "SELECT prediction_log_id, updated_at FROM app.sports_current_quotes ORDER BY prediction_log_id"
        )

        self.query_one("DELETE FROM app.sports_prediction_logs WHERE odds = -110 RETURNING id")

        after = self.query_all(
            "SELECT prediction_log_id, updated_at FROM app.sports_current_quotes ORDER BY prediction_log_id"
        )
        self.assertEqual(
            [(row["prediction_log_id"], row["updated_at"]) for row in before],
            [(row["prediction_log_id"], row["updated_at"]) for row in after],
        )
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_deleting_a_log_row_removes_its_quote(self) -> None:
        self._log(home_price=-110, away_price=-110)
        self.assertEqual(len(self._projection()), 2)

        self.query_one(
            "DELETE FROM app.sports_prediction_logs WHERE selection = 'Home' RETURNING id"
        )

        self.assertEqual(list(self._projection()), [("book_a", "Away")])
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_recording_closing_lines_leaves_the_projection_alone(self) -> None:
        """CLV writes columns the projection does not carry; it must not churn."""
        self._log(home_price=-110, away_price=-110, start_offset_hours=-1, collected_minutes_ago=90)
        before = self.query_all(
            "SELECT prediction_log_id, updated_at FROM app.sports_current_quotes ORDER BY prediction_log_id"
        )
        self.assertEqual(len(before), 2, "fixture must produce quotes for the comparison to mean anything")

        captured = capture_sports_closing_lines(run_id="quotes")
        self.assertGreater(captured["rows_updated"], 0, "closing lines must actually have been written")

        after = self.query_all(
            "SELECT prediction_log_id, updated_at FROM app.sports_current_quotes ORDER BY prediction_log_id"
        )
        self.assertEqual(
            [(row["prediction_log_id"], row["updated_at"]) for row in before],
            [(row["prediction_log_id"], row["updated_at"]) for row in after],
        )
        self.assertTrue(verify_current_quotes()["consistent"])

    def test_the_board_reads_the_same_rows_the_original_query_would_have(self) -> None:
        """The projection replaced a `DISTINCT ON`; it must not change the answer."""
        for minutes, home, away in ((60, -110, -110), (40, -115, -105), (10, -130, 110)):
            self._log(home_price=home, away_price=away, collected_minutes_ago=minutes)
        self._log(home_price=-120, away_price=100, bookmaker="book_b")
        self._log(home_price=-105, away_price=-115, event_id="g2", start_offset_hours=5)

        expected = self.query_all(
            """
            SELECT DISTINCT ON (event_id, market_type, selection, line, bookmaker)
                   event_id, bookmaker, selection, odds
            FROM app.sports_prediction_logs
            WHERE validation_status = 'valid'
              AND settlement_state = 'unresolved'
            ORDER BY event_id, market_type, selection, line, bookmaker,
                     prediction_timestamp DESC, id DESC
            """
        )
        projected = self.query_all(
            """
            SELECT event_id, bookmaker, selection, odds
            FROM app.sports_current_quotes
            ORDER BY event_id, bookmaker, selection
            """
        )
        as_tuples = lambda rows: sorted(  # noqa: E731 - local shorthand
            (str(r["event_id"]), str(r["bookmaker"]), str(r["selection"]), Decimal(str(r["odds"])))
            for r in rows
        )
        self.assertEqual(as_tuples(expected), as_tuples(projected))

        board = load_sports_board()
        self.assertEqual(board["board_state"], "fresh")
        self.assertEqual(board["event_count"], 2)
        self.assertEqual(board["quote_count"], len(projected))

    def test_verification_reports_a_projection_that_has_drifted(self) -> None:
        """The check has to be able to fail, or it is not a check."""
        self._log(home_price=-110, away_price=-110)
        self.assertTrue(verify_current_quotes()["consistent"])

        # Reach around the trigger the way a bad migration or manual fix would.
        self.query_one(
            "DELETE FROM app.sports_current_quotes WHERE selection = 'Home' RETURNING id"
        )
        drifted = verify_current_quotes()
        self.assertFalse(drifted["consistent"])
        self.assertEqual(drifted["missing_from_projection"], 1)
        self.assertEqual(drifted["disagreements"], 1)

        self.query_one(
            """
            UPDATE app.sports_current_quotes
            SET prediction_log_id = (SELECT MIN(id) FROM app.sports_prediction_logs)
            WHERE selection = 'Away'
            RETURNING id
            """
        )
        repointed = verify_current_quotes()
        self.assertEqual(repointed["pointing_at_another_row"], 1)
        self.assertFalse(repointed["consistent"])

    def test_an_empty_log_leaves_an_empty_and_consistent_projection(self) -> None:
        report = verify_current_quotes()
        self.assertEqual(report["expected_quotes"], 0)
        self.assertEqual(report["projected_quotes"], 0)
        self.assertTrue(report["consistent"])
