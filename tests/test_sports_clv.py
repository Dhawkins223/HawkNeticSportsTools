from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from kalshi_research_bot.sports_board import american_implied_probability
from kalshi_research_bot.sports_clv import (
    build_sports_clv_report,
    capture_sports_closing_lines,
    closing_line_value,
    render_sports_clv_report,
)
from kalshi_research_bot.sports_research import log_sports_predictions, normalize_the_odds_api_payload

from tests.postgres_support import PostgresTestCase


def _now() -> datetime:
    return datetime.now(timezone.utc)


class SportsClvTests(PostgresTestCase):
    def _log_quote(
        self,
        *,
        run_id: str = "clv",
        home_price: int,
        away_price: int,
        minutes_before_start: float,
        start_offset_hours: float = -1,
        bookmaker: str = "book_a",
        event_id: str = "g1",
    ) -> dict:
        """Record one collection cycle for a game that starts `start_offset_hours` from now."""
        now = _now()
        start = now + timedelta(hours=start_offset_hours)
        fetched = (start - timedelta(minutes=minutes_before_start)).isoformat()
        source = [
            {
                "id": event_id,
                "commence_time": start.isoformat(),
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
        ]
        records = normalize_the_odds_api_payload(
            source, sport="baseball_mlb", league="mlb", api_fetched_at=fetched
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

    def test_closing_line_value_is_probability_points_against_the_close(self) -> None:
        # Took -110, market closed -130: the market moved toward this side.
        gained = closing_line_value(Decimal("-110"), Decimal("-130"))
        self.assertGreater(gained, 0)
        expected = american_implied_probability(Decimal("-130")) - american_implied_probability(Decimal("-110"))
        self.assertEqual(gained, expected.quantize(Decimal("0.000000000001")))

        # Took -130, market closed -110: the market moved away.
        self.assertLess(closing_line_value(Decimal("-130"), Decimal("-110")), 0)
        # Closed where it was taken.
        self.assertEqual(closing_line_value(Decimal("-110"), Decimal("-110")), Decimal("0").quantize(Decimal("0.000000000001")))

    def test_started_games_get_a_closing_line_and_clv(self) -> None:
        self._log_quote(home_price=-110, away_price=-110, minutes_before_start=120)
        self._log_quote(home_price=-130, away_price=110, minutes_before_start=10)

        capture = capture_sports_closing_lines(run_id="clv")
        self.assertEqual(capture["markets_closed"], 2)
        self.assertEqual(capture["rows_updated"], 4)

        rows = self.query_all(
            "SELECT selection, odds, closing_line, clv FROM app.sports_prediction_logs ORDER BY selection, odds"
        )
        self.assertTrue(all(row["closing_line"] is not None and row["clv"] is not None for row in rows))
        by_key = {(str(row["selection"]), Decimal(str(row["odds"]))): row for row in rows}

        # The Home side opened -110 and closed -130, so the earlier price beat the close.
        opened_home = by_key[("Home", Decimal("-110"))]
        self.assertEqual(Decimal(str(opened_home["closing_line"])), Decimal("-130"))
        self.assertGreater(Decimal(str(opened_home["clv"])), 0)

        # The Away side opened -110 and closed +110, so the earlier price lost to the close.
        opened_away = by_key[("Away", Decimal("-110"))]
        self.assertLess(Decimal(str(opened_away["clv"])), 0)

        # A closing quote is its own close and grades at exactly zero.
        closing_home = by_key[("Home", Decimal("-130"))]
        self.assertEqual(Decimal(str(closing_home["clv"])), 0)

    def test_capture_is_idempotent(self) -> None:
        self._log_quote(home_price=-110, away_price=-110, minutes_before_start=120)
        self._log_quote(home_price=-130, away_price=110, minutes_before_start=10)

        first = capture_sports_closing_lines(run_id="clv")
        second = capture_sports_closing_lines(run_id="clv")

        self.assertGreater(first["rows_updated"], 0)
        self.assertEqual(second["rows_updated"], 0)
        self.assertEqual(second["rows_unchanged"], first["rows_updated"])

    def test_upcoming_games_are_not_graded(self) -> None:
        self._log_quote(home_price=-110, away_price=-110, minutes_before_start=30, start_offset_hours=4)

        capture = capture_sports_closing_lines(run_id="clv")
        self.assertEqual(capture["markets_closed"], 0)
        self.assertEqual(capture["rows_updated"], 0)

        report = build_sports_clv_report(run_id="clv")
        self.assertEqual(report["graded_rows"], 0)
        self.assertEqual(report["pending_rows"], 2)
        self.assertIsNone(report["beat_rate"])

    def test_a_later_close_supersedes_an_earlier_one(self) -> None:
        self._log_quote(home_price=-110, away_price=-110, minutes_before_start=120)
        capture_sports_closing_lines(run_id="clv")

        # A quote collected closer to kickoff becomes the new close.
        self._log_quote(home_price=-150, away_price=130, minutes_before_start=5)
        recapture = capture_sports_closing_lines(run_id="clv")
        self.assertGreater(recapture["rows_updated"], 0)

        opened = self.query_one(
            "SELECT closing_line, clv FROM app.sports_prediction_logs WHERE selection = 'Home' AND odds = %s",
            (Decimal("-110"),),
        )
        self.assertEqual(Decimal(str(opened["closing_line"])), Decimal("-150"))

    def test_report_separates_beat_lost_and_matched(self) -> None:
        self._log_quote(home_price=-110, away_price=-110, minutes_before_start=120)
        self._log_quote(home_price=-130, away_price=110, minutes_before_start=10)
        capture_sports_closing_lines(run_id="clv")

        report = build_sports_clv_report(run_id="clv")
        self.assertEqual(report["graded_rows"], 4)
        self.assertEqual(report["beat_close"], 1)
        self.assertEqual(report["lost_to_close"], 1)
        self.assertEqual(report["matched_close"], 2)
        self.assertEqual(report["beat_rate_denominator"], 2)
        self.assertEqual(Decimal(report["beat_rate"]), Decimal("0.5"))
        self.assertEqual(report["model_state"], "baseline_only")
        self.assertEqual(report["decision_status"], "track_only")

        self.assertEqual([entry["market_type"] for entry in report["by_market"]], ["moneyline"])
        self.assertEqual([entry["bookmaker"] for entry in report["by_bookmaker"]], ["book_a"])

    def test_report_scopes_to_a_run_when_asked(self) -> None:
        self._log_quote(run_id="run_a", home_price=-110, away_price=-110, minutes_before_start=120)
        self._log_quote(run_id="run_a", home_price=-130, away_price=110, minutes_before_start=10)
        self._log_quote(run_id="run_b", home_price=-105, away_price=-115, minutes_before_start=90, event_id="g2")
        self._log_quote(run_id="run_b", home_price=-140, away_price=120, minutes_before_start=8, event_id="g2")
        capture_sports_closing_lines()

        self.assertEqual(build_sports_clv_report(run_id="run_a")["graded_rows"], 4)
        self.assertEqual(build_sports_clv_report(run_id="run_b")["graded_rows"], 4)
        self.assertEqual(build_sports_clv_report()["graded_rows"], 8)

    def test_exact_values_are_serialized_as_fixed_point_strings(self) -> None:
        self._log_quote(home_price=-110, away_price=-110, minutes_before_start=120)
        self._log_quote(home_price=-130, away_price=110, minutes_before_start=10)
        capture_sports_closing_lines(run_id="clv")

        report = build_sports_clv_report(run_id="clv")
        self.assertIsInstance(report["average_clv"], str)
        self.assertNotIn("e", report["average_clv"].lower())
        Decimal(report["average_clv"])
        Decimal(report["total_clv"])

    def test_rendered_report_states_it_is_not_profit(self) -> None:
        self._log_quote(home_price=-110, away_price=-110, minutes_before_start=120)
        self._log_quote(home_price=-130, away_price=110, minutes_before_start=10)
        capture_sports_closing_lines(run_id="clv")

        rendered = render_sports_clv_report(build_sports_clv_report(run_id="clv"))
        self.assertIn("Sports Closing Line Value", rendered)
        self.assertIn("not profit", rendered)

    def test_dashboard_panel_reports_both_states(self) -> None:
        from kalshi_research_bot.paper_server import render_sports_clv_panel

        empty = render_sports_clv_panel(build_sports_clv_report(run_id="clv"))
        self.assertIn("No closing lines recorded", empty)

        self._log_quote(home_price=-110, away_price=-110, minutes_before_start=120)
        self._log_quote(home_price=-130, away_price=110, minutes_before_start=10)
        capture_sports_closing_lines(run_id="clv")

        graded = render_sports_clv_panel(build_sports_clv_report(run_id="clv"))
        self.assertIn("Closing line value", graded)
        self.assertIn("Beat close", graded)
        self.assertIn("Not profit", graded)
