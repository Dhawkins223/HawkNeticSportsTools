from __future__ import annotations

import csv
import json
import tempfile
from pathlib import Path
from urllib.error import URLError

import kalshi_research_bot.sports_research as sports_module
from kalshi_research_bot.sports_research import (
    append_sports_validation_ledger,
    build_sports_prediction_candidates,
    build_sports_report,
    collect_sports_payload,
    export_sports_features,
    log_sports_predictions,
    match_odds_to_schedule,
    normalize_espn_scoreboard_payload,
    normalize_espn_summary_odds,
    normalize_team_name,
    normalize_the_odds_api_payload,
    parse_public_odds_fixture_html,
    read_sports_validation_ledger,
    settle_sports_predictions,
    sports_cycle,
    sports_win_rate_status,
    validate_sports_prediction,
)

from tests.postgres_support import PostgresTestCase


class _FixtureResponse:
    fetched_at = "2026-07-04T19:01:00+00:00"

    def __init__(self, payload: dict | Exception) -> None:
        self.payload = payload

    def json(self) -> dict:
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class _FixtureHttp:
    def get_text(self, url: str, timeout: int = 20) -> _FixtureResponse:
        return _FixtureResponse({"events": []})


class _PayloadHttp:
    def __init__(self, payload=None, error: Exception | None = None) -> None:
        self.payload = payload
        self.error = error

    def get_text(self, url: str, timeout: int = 20) -> _FixtureResponse:
        if self.error:
            raise self.error
        return _FixtureResponse(self.payload)


class _FallbackHttp:
    def __init__(self, scoreboard: dict, summary: dict) -> None:
        self.scoreboard = scoreboard
        self.summary = summary

    def get_text(self, url: str, timeout: int = 20) -> _FixtureResponse:
        return _FixtureResponse(self.summary if "summary?event=" in url else self.scoreboard)


def _sports_payload() -> dict:
    source = [
        {
            "id": "game-1",
            "commence_time": "2026-07-04T20:00:00+00:00",
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [
                {
                    "key": "book",
                    "last_update": "2026-07-04T19:00:00+00:00",
                    "markets": [
                        {"key": "h2h", "outcomes": [{"name": "Home", "price": -120}, {"name": "Away", "price": 110}]},
                        {"key": "spreads", "outcomes": [{"name": "Home", "price": -110, "point": -2.5}, {"name": "Away", "price": -110, "point": 2.5}]},
                    ],
                }
            ],
        }
    ]
    return {
        "asset_class": "sports",
        "model_version": "sports_odds_research_v1",
        "strategy": "pregame_odds_snapshot_v1",
        "generated_at": "2026-07-04T19:01:00+00:00",
        "records": normalize_the_odds_api_payload(source, sport="basketball_nba", league="nba", api_fetched_at="2026-07-04T19:01:00+00:00"),
    }


def _scoreboard_payload(*, completed: bool = False, with_odds: bool = True) -> dict:
    odds = [
        {
            "provider": {"name": "ESPN BET"},
            "lastUpdated": "2026-07-04T19:00:00+00:00",
            "homeTeamOdds": {"moneyLine": -125, "spread": -1.5, "spreadOdds": -110},
            "awayTeamOdds": {"moneyLine": 105, "spread": 1.5, "spreadOdds": -110},
            "overUnder": 8.5,
            "overOdds": -105,
            "underOdds": -115,
        }
    ] if with_odds else []
    return {
        "events": [
            {
                "id": "mlb-1",
                "date": "2026-07-04T20:00:00+00:00",
                "competitions": [
                    {
                        "id": "mlb-1",
                        "date": "2026-07-04T20:00:00+00:00",
                        "status": {"type": {"name": "STATUS_FINAL" if completed else "STATUS_SCHEDULED", "description": "Final" if completed else "Scheduled", "completed": completed}},
                        "competitors": [
                            {"homeAway": "home", "score": "5" if completed else None, "team": {"displayName": "Home"}},
                            {"homeAway": "away", "score": "3" if completed else None, "team": {"displayName": "Away"}},
                        ],
                        "odds": odds,
                    }
                ],
            }
        ]
    }


def _summary_payload() -> dict:
    return {
        "pickcenter": [
            {
                "provider": {"name": "DraftKings"},
                "overUnder": 8.0,
                "overOdds": -114,
                "underOdds": -105,
                "awayTeamOdds": {"moneyLine": -181},
                "homeTeamOdds": {"moneyLine": 149},
                "pointSpread": {
                    "home": {"close": {"line": "+1.5", "odds": "-114"}},
                    "away": {"close": {"line": "-1.5", "odds": "-105"}},
                },
                "total": {
                    "over": {"close": {"line": "o8", "odds": "-114"}},
                    "under": {"close": {"line": "u8", "odds": "-105"}},
                },
            }
        ]
    }


class SportsResearchTests(PostgresTestCase):
    def test_public_source_without_valid_schedule_blocks_without_fake_rows(self) -> None:
        payload = collect_sports_payload(api_key="", http=_FixtureHttp(), date="20260704")
        self.assertEqual(payload["records"], [])
        self.assertIn(payload["blocker"], {"blocked_missing_sports_source", "blocked_no_scheduled_events", "source_blocked", "source_failed"})

    def test_predictions_settle_and_report_keeps_win_rate_unavailable_until_settled(self) -> None:
        payload = _sports_payload()
        candidates = build_sports_prediction_candidates(payload, run_id="sports")
        self.assertGreater(len(candidates), 0)
        logged = log_sports_predictions(run_id="sports", payload=payload)
        before = build_sports_report(run_id="sports")
        self.assertGreater(logged["logged_predictions"], 0)
        self.assertEqual(before["settled_deduped_exposures"], 0)
        self.assertEqual(before["win_rate_status"], "unavailable / no settled rows")

        settled = settle_sports_predictions(run_id="sports", finals_payload={"events": [{"event_id": "game-1", "home_score": 101, "away_score": 90}]})
        after = build_sports_report(run_id="sports")
        self.assertGreater(settled["rows_updated"], 0)
        self.assertGreater(after["settled_deduped_exposures"], 0)
        self.assertEqual(after["win_loss_denominator"], after["win_count"] + after["loss_count"])

    def test_repeat_is_rejected_and_status_never_calls_unsettled_rows_losses(self) -> None:
        payload = _sports_payload()
        first = log_sports_predictions(run_id="repeat", payload=payload)
        repeated = log_sports_predictions(run_id="repeat", payload=payload)
        self.assertGreater(first["logged_predictions"], 0)
        self.assertGreater(repeated["rejected_predictions"], 0)
        self.assertEqual(sports_win_rate_status(0, 0), "unavailable / no settled rows")

    def test_scraper_mode_uses_public_schedule_without_fake_rows(self) -> None:
        payload = collect_sports_payload(api_key="", http=_PayloadHttp(_scoreboard_payload()), date="20260704")
        self.assertEqual(payload["source_mode"], "scraper")
        self.assertEqual(payload["source"], "espn_scoreboard")
        self.assertIsNone(payload["blocker"])
        self.assertEqual(len(payload["records"]), 6)

    def test_schedule_and_final_scores_are_normalized(self) -> None:
        scheduled = normalize_espn_scoreboard_payload(
            _scoreboard_payload(), sport="baseball", league="mlb", api_fetched_at="2026-07-04T19:01:00+00:00"
        )
        completed = normalize_espn_scoreboard_payload(
            _scoreboard_payload(completed=True), sport="baseball", league="mlb", api_fetched_at="2026-07-04T23:01:00+00:00"
        )
        self.assertEqual(scheduled["schedule"][0]["event_id"], "mlb-1")
        self.assertEqual(scheduled["schedule"][0]["game_start_time"], "2026-07-04T20:00:00+00:00")
        self.assertEqual(len(scheduled["odds"]), 6)
        self.assertEqual(completed["finals"][0]["home_score"], "5")
        self.assertEqual(completed["finals"][0]["status"], "final")

    def test_summary_odds_fallback_remains_public_and_attributed(self) -> None:
        schedule = normalize_espn_scoreboard_payload(
            _scoreboard_payload(with_odds=False),
            sport="baseball",
            league="mlb",
            api_fetched_at="2026-07-04T19:01:00+00:00",
        )["schedule"]
        rows = normalize_espn_summary_odds(
            _summary_payload(), schedule_row=schedule[0], api_fetched_at="2026-07-04T19:02:00+00:00"
        )
        payload = collect_sports_payload(
            api_key="",
            http=_FallbackHttp(_scoreboard_payload(with_odds=False), _summary_payload()),
            date="20260704",
        )
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["source"], "espn_summary_odds")
        self.assertEqual(rows[0]["bookmaker"], "DraftKings")
        self.assertEqual(payload["source"], "espn_summary")
        self.assertIsNone(payload["blocker"])

    def test_public_fixture_html_preserves_team_normalization(self) -> None:
        fixture = [{
            "home_team": "LA Dodgers",
            "away_team": "Boston Red Sox",
            "game_start_time": "2026-07-04T20:00:00+00:00",
            "bookmaker": "public-book",
            "market_type": "moneyline",
            "selection": "LA Dodgers",
            "odds": -130,
            "odds_timestamp": "2026-07-04T19:00:00+00:00",
        }]
        html = f'<html><script id="sports-odds-data" type="application/json">{json.dumps(fixture)}</script></html>'
        rows = parse_public_odds_fixture_html(html, sport="baseball", league="mlb", api_fetched_at="2026-07-04T19:01:00+00:00")
        self.assertEqual(rows[0]["bookmaker"], "public-book")
        self.assertEqual(normalize_team_name("LA Dodgers"), "losangelesdodgers")
        self.assertEqual(normalize_team_name("Red Sox"), "bostonredsox")

    def test_low_confidence_event_match_is_rejected(self) -> None:
        schedule = normalize_espn_scoreboard_payload(
            _scoreboard_payload(), sport="baseball", league="mlb", api_fetched_at="2026-07-04T19:01:00+00:00"
        )["schedule"]
        odds = [{
            "sport": "baseball", "league": "mlb", "home_team": "Wrong", "away_team": "Other",
            "game_start_time": "2026-07-04T20:00:00+00:00", "bookmaker": "public",
            "market_type": "moneyline", "selection": "Wrong", "odds": -110,
            "odds_format": "american", "odds_timestamp": "2026-07-04T19:00:00+00:00",
            "api_fetched_at": "2026-07-04T19:01:00+00:00", "source_snapshot_hash": "hash",
        }]
        matched, rejected = match_odds_to_schedule(odds, schedule)
        self.assertEqual(matched, [])
        self.assertEqual(rejected[0]["rejection_reason"], "low_confidence_event_match")

    def test_source_hash_is_deterministic_across_fetch_time(self) -> None:
        first = _sports_payload()["records"]
        second = normalize_the_odds_api_payload(
            [{
                "id": "game-1", "commence_time": "2026-07-04T20:00:00+00:00", "home_team": "Home", "away_team": "Away",
                "bookmakers": [{"key": "book", "last_update": "2026-07-04T19:00:00+00:00", "markets": [{"key": "h2h", "outcomes": [{"name": "Home", "price": -120}]}]}],
            }],
            sport="basketball_nba", league="nba", api_fetched_at="2026-07-04T19:02:00+00:00",
        )
        self.assertEqual(first[0]["market_type"], "moneyline")
        self.assertEqual(first[0]["source_snapshot_hash"], second[0]["source_snapshot_hash"])

    def test_timestamp_and_stale_odds_validation_is_strict(self) -> None:
        candidate = build_sports_prediction_candidates(_sports_payload(), run_id="validation")[0]
        self.assertIn("missing_odds_timestamp", validate_sports_prediction({**candidate, "odds_timestamp": None}))
        self.assertIn("missing_game_start_time", validate_sports_prediction({**candidate, "game_start_time": None}))
        self.assertIn("missing_market_type", validate_sports_prediction({**candidate, "market_type": None}))
        self.assertIn("prediction_after_game_start", validate_sports_prediction({**candidate, "prediction_timestamp": "2026-07-04T20:01:00+00:00"}))
        self.assertIn("odds_after_game_start", validate_sports_prediction({**candidate, "odds_timestamp": "2026-07-04T20:01:00+00:00"}))
        self.assertIn("stale_odds", validate_sports_prediction({**candidate, "prediction_timestamp": "2026-07-04T19:01:00+00:00", "odds_timestamp": "2026-07-04T17:00:00+00:00"}))
        self.assertIn("invalid_timezone", validate_sports_prediction({**candidate, "prediction_timestamp": "2026-07-04T19:01:00"}))

    def test_source_block_and_parse_failure_remain_blocked(self) -> None:
        blocked = collect_sports_payload(api_key="", http=_PayloadHttp(error=URLError("blocked")), date="20260704")
        parsed = collect_sports_payload(api_key="", http=_PayloadHttp(ValueError("bad-json")), date="20260704")
        self.assertEqual(blocked["blocker"], "blocked_public_source_unavailable")
        self.assertEqual(blocked["errors"][0]["reason"], "source_blocked")
        self.assertEqual(parsed["blocker"], "blocked_public_source_unavailable")
        self.assertEqual(parsed["errors"][0]["reason"], "parse_failed")
        self.assertTrue(parsed["raw_evidence"])

    def test_low_confidence_rejection_is_excluded_from_metrics(self) -> None:
        payload = _sports_payload()
        rejected = {**payload["records"][0], "rejection_reason": "low_confidence_event_match"}
        payload["records"] = []
        payload["rejected_records"] = [rejected]
        result = log_sports_predictions(run_id="low-match", payload=payload)
        report = build_sports_report(run_id="low-match")
        self.assertEqual(result["rejection_reasons"].get("low_confidence_event_match"), 1)
        persisted = self.query_one(
            "SELECT rejection_reason FROM app.sports_prediction_rejections WHERE run_id = %s",
            ("low-match",),
        )
        self.assertIsNotNone(persisted)
        self.assertEqual(persisted["rejection_reason"], "low_confidence_event_match")
        self.assertEqual(report["total_raw_predictions"], 0)
        self.assertEqual(report["low_confidence_event_match_count"], 1)

    def test_push_void_and_missing_final_score_are_not_losses(self) -> None:
        log_sports_predictions(run_id="push", payload=_sports_payload())
        settle_sports_predictions(run_id="push", finals_payload={"events": [{"event_id": "game-1", "home_score": 101, "away_score": 98.5, "status": "final"}]})
        self.assertGreater(build_sports_report(run_id="push")["push_count"], 0)

        log_sports_predictions(run_id="void", payload=_sports_payload())
        settle_sports_predictions(run_id="void", finals_payload={"events": [{"event_id": "game-1", "status": "canceled"}]})
        self.assertGreater(build_sports_report(run_id="void")["void_count"], 0)

        log_sports_predictions(run_id="unresolved", payload=_sports_payload())
        settle_sports_predictions(run_id="unresolved", finals_payload={"events": []})
        report = build_sports_report(run_id="unresolved")
        self.assertEqual(report["settled_raw_rows"], 0)
        self.assertIsNone(report["accuracy"])
        self.assertEqual(report["win_rate_status"], "unavailable / no settled rows")

    def test_validation_ledger_does_not_convert_unresolved_rows_to_losses(self) -> None:
        logged = log_sports_predictions(run_id="ledger", payload=_sports_payload())
        report = build_sports_report(run_id="ledger")
        with tempfile.TemporaryDirectory() as directory:
            ledger = Path(directory) / "validation.jsonl"
            entry = append_sports_validation_ledger(report, log_result=logged, path=ledger)
            rows = read_sports_validation_ledger(ledger)
        self.assertEqual(len(rows), 1)
        self.assertEqual(entry["deduped_settled_exposures"], 0)
        self.assertEqual(entry["loss_count"], 0)
        self.assertIsNone(entry["win_rate"])

    def test_feature_export_separates_outcomes_and_final_scores(self) -> None:
        log_sports_predictions(run_id="features", payload=_sports_payload())
        settle_sports_predictions(run_id="features", finals_payload={"events": [{"event_id": "game-1", "home_score": 101, "away_score": 96, "status": "final"}]})
        with tempfile.TemporaryDirectory() as directory:
            features = Path(directory) / "features.csv"
            labels = Path(directory) / "labels.csv"
            result = export_sports_features(run_id="features", output=features, labels_output=labels)
            with features.open(newline="", encoding="utf-8") as handle:
                feature_header = next(csv.reader(handle))
            with labels.open(newline="", encoding="utf-8") as handle:
                label_header = next(csv.reader(handle))
        self.assertGreater(result["feature_rows"], 0)
        self.assertNotIn("final_score_json", feature_header)
        self.assertNotIn("actual_outcome", feature_header)
        self.assertNotIn("profit_loss", feature_header)
        self.assertIn("actual_outcome", label_header)
        self.assertIn("final_score_json", label_header)
