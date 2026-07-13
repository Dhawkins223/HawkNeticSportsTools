import csv
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import URLError

import kalshi_research_bot.sports_research as sports_module
from kalshi_research_bot.sports_research import (
    append_sports_validation_ledger,
    build_sports_report,
    build_sports_prediction_candidates,
    build_sports_validation_ledger_entry,
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
    validate_sports_prediction,
)


class _FakeResponse:
    def __init__(self, payload, fetched_at="2026-07-04T19:01:00Z"):
        self._payload = payload
        self.fetched_at = fetched_at

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeHttp:
    def __init__(self, payload=None, error=None):
        self.payload = payload
        self.error = error

    def get_text(self, url, timeout=20):
        if self.error:
            raise self.error
        return _FakeResponse(self.payload)


class _FallbackHttp:
    def __init__(self, scoreboard_payload, summary_payload):
        self.scoreboard_payload = scoreboard_payload
        self.summary_payload = summary_payload

    def get_text(self, url, timeout=20):
        if "summary?event=" in url:
            return _FakeResponse(self.summary_payload, fetched_at="2026-07-04T19:02:00Z")
        return _FakeResponse(self.scoreboard_payload)


def _odds_payload(point_shift: float = 0.0, odds_shift: float = 0.0):
    raw = [
        {
            "id": "game-1",
            "commence_time": "2026-07-04T20:00:00Z",
            "home_team": "Home",
            "away_team": "Away",
            "bookmakers": [
                {
                    "key": "book",
                    "last_update": "2026-07-04T19:00:00Z",
                    "markets": [
                        {
                            "key": "h2h",
                            "last_update": "2026-07-04T19:00:00Z",
                            "outcomes": [
                                {"name": "Home", "price": -120 + odds_shift},
                                {"name": "Away", "price": 110 + odds_shift},
                            ],
                        },
                        {
                            "key": "spreads",
                            "last_update": "2026-07-04T19:00:00Z",
                            "outcomes": [
                                {"name": "Home", "price": -110 + odds_shift, "point": -2.5 + point_shift},
                                {"name": "Away", "price": -110 + odds_shift, "point": 2.5 - point_shift},
                            ],
                        },
                        {
                            "key": "totals",
                            "last_update": "2026-07-04T19:00:00Z",
                            "outcomes": [
                                {"name": "Over", "price": -110 + odds_shift, "point": 199.5 + point_shift},
                                {"name": "Under", "price": -110 + odds_shift, "point": 199.5 + point_shift},
                            ],
                        },
                    ],
                }
            ],
        }
    ]
    records = normalize_the_odds_api_payload(raw, sport="basketball_nba", league="nba", api_fetched_at="2026-07-04T19:01:00Z")
    return {
        "asset_class": "sports",
        "model_version": "sports_odds_research_v1",
        "strategy": "pregame_odds_snapshot_v1",
        "generated_at": "2026-07-04T19:01:00Z",
        "records": records,
    }


def _espn_scoreboard_payload(completed: bool = False):
    return {
        "events": [
            {
                "id": "mlb-1",
                "date": "2026-07-04T20:00:00Z",
                "competitions": [
                    {
                        "id": "mlb-1",
                        "date": "2026-07-04T20:00:00Z",
                        "status": {"type": {"name": "STATUS_FINAL" if completed else "STATUS_SCHEDULED", "description": "Final" if completed else "Scheduled", "completed": completed}},
                        "competitors": [
                            {"homeAway": "home", "score": "5" if completed else None, "team": {"displayName": "Home"}},
                            {"homeAway": "away", "score": "3" if completed else None, "team": {"displayName": "Away"}},
                        ],
                        "odds": [
                            {
                                "provider": {"name": "ESPN BET"},
                                "lastUpdated": "2026-07-04T19:00:00Z",
                                "homeTeamOdds": {"moneyLine": -125, "spread": -1.5, "spreadOdds": -110},
                                "awayTeamOdds": {"moneyLine": 105, "spread": 1.5, "spreadOdds": -110},
                                "overUnder": 8.5,
                                "overOdds": -105,
                                "underOdds": -115,
                            }
                        ],
                    }
                ],
            }
        ]
    }


def _espn_scoreboard_without_odds():
    payload = _espn_scoreboard_payload()
    payload["events"][0]["competitions"][0]["odds"] = []
    return payload


def _espn_summary_payload():
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


class SportsResearchTests(unittest.TestCase):
    def test_no_key_uses_scraper_first_espn_payload_without_fake_rows(self):
        payload = collect_sports_payload(api_key="", http=_FakeHttp(_espn_scoreboard_payload()), date="20260704")
        self.assertEqual(payload["source_mode"], "scraper")
        self.assertEqual(payload["source"], "espn_scoreboard")
        self.assertIsNone(payload["blocker"])
        self.assertEqual(len(payload["records"]), 6)

    def test_espn_schedule_and_final_score_parsing(self):
        scheduled = normalize_espn_scoreboard_payload(_espn_scoreboard_payload(), sport="baseball", league="mlb", api_fetched_at="2026-07-04T19:01:00Z")
        self.assertEqual(scheduled["schedule"][0]["event_id"], "mlb-1")
        self.assertEqual(scheduled["schedule"][0]["game_start_time"], "2026-07-04T20:00:00Z")
        self.assertEqual(len(scheduled["odds"]), 6)
        final = normalize_espn_scoreboard_payload(_espn_scoreboard_payload(completed=True), sport="baseball", league="mlb", api_fetched_at="2026-07-04T23:01:00Z")
        self.assertEqual(final["finals"][0]["home_score"], "5")
        self.assertEqual(final["finals"][0]["status"], "final")

    def test_espn_summary_odds_fallback_parsing(self):
        schedule = normalize_espn_scoreboard_payload(
            _espn_scoreboard_without_odds(),
            sport="baseball",
            league="mlb",
            api_fetched_at="2026-07-04T19:01:00Z",
        )["schedule"]
        rows = normalize_espn_summary_odds(_espn_summary_payload(), schedule_row=schedule[0], api_fetched_at="2026-07-04T19:02:00Z")
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["source"], "espn_summary_odds")
        self.assertEqual(rows[0]["bookmaker"], "DraftKings")
        payload = collect_sports_payload(
            api_key="",
            http=_FallbackHttp(_espn_scoreboard_without_odds(), _espn_summary_payload()),
            date="20260704",
        )
        self.assertEqual(payload["source"], "espn_summary")
        self.assertIsNone(payload["blocker"])
        self.assertEqual(len(payload["records"]), 6)
        self.assertGreaterEqual(payload["generated_at"], max(row["api_fetched_at"] for row in payload["records"]))

    def test_public_odds_fixture_html_parsing_and_team_normalization(self):
        fixture = [
            {
                "home_team": "LA Dodgers",
                "away_team": "Boston Red Sox",
                "game_start_time": "2026-07-04T20:00:00Z",
                "bookmaker": "public-book",
                "market_type": "moneyline",
                "selection": "LA Dodgers",
                "odds": -130,
                "odds_timestamp": "2026-07-04T19:00:00Z",
            }
        ]
        html = f'<html><script id="sports-odds-data" type="application/json">{json.dumps(fixture)}</script></html>'
        rows = parse_public_odds_fixture_html(html, sport="baseball", league="mlb", api_fetched_at="2026-07-04T19:01:00Z")
        self.assertEqual(rows[0]["bookmaker"], "public-book")
        self.assertEqual(normalize_team_name("LA Dodgers"), "losangelesdodgers")
        self.assertEqual(normalize_team_name("Red Sox"), "bostonredsox")

    def test_low_confidence_event_match_rejection(self):
        schedule = normalize_espn_scoreboard_payload(_espn_scoreboard_payload(), sport="baseball", league="mlb", api_fetched_at="2026-07-04T19:01:00Z")["schedule"]
        odds = [
            {
                "sport": "baseball",
                "league": "mlb",
                "home_team": "Wrong",
                "away_team": "Other",
                "game_start_time": "2026-07-04T20:00:00Z",
                "bookmaker": "public",
                "market_type": "moneyline",
                "selection": "Wrong",
                "odds": -110,
                "odds_format": "american",
                "odds_timestamp": "2026-07-04T19:00:00Z",
                "api_fetched_at": "2026-07-04T19:01:00Z",
                "source_snapshot_hash": "hash",
            }
        ]
        matched, rejected = match_odds_to_schedule(odds, schedule)
        self.assertEqual(matched, [])
        self.assertEqual(rejected[0]["rejection_reason"], "low_confidence_event_match")

    def test_odds_payload_normalization_and_deterministic_hash(self):
        first = _odds_payload()["records"]
        second = normalize_the_odds_api_payload(
            [
                {
                    "id": "game-1",
                    "commence_time": "2026-07-04T20:00:00Z",
                    "home_team": "Home",
                    "away_team": "Away",
                    "bookmakers": [{"key": "book", "last_update": "2026-07-04T19:00:00Z", "markets": [{"key": "h2h", "last_update": "2026-07-04T19:00:00Z", "outcomes": [{"name": "Home", "price": -120}]}]}],
                }
            ],
            sport="basketball_nba",
            league="nba",
            api_fetched_at="2026-07-04T19:02:00Z",
        )
        self.assertEqual(first[0]["market_type"], "moneyline")
        self.assertEqual(first[0]["source_snapshot_hash"], second[0]["source_snapshot_hash"])

    def test_timestamp_odds_and_stale_validation(self):
        candidate = build_sports_prediction_candidates(_odds_payload(), run_id="sports")[0]
        missing = dict(candidate)
        missing["odds_timestamp"] = None
        self.assertIn("missing_odds_timestamp", validate_sports_prediction(missing))
        missing_start = dict(candidate)
        missing_start["game_start_time"] = None
        self.assertIn("missing_game_start_time", validate_sports_prediction(missing_start))
        missing_market = dict(candidate)
        missing_market["market_type"] = None
        self.assertIn("missing_market_type", validate_sports_prediction(missing_market))
        after_start = dict(candidate)
        after_start["prediction_timestamp"] = "2026-07-04T20:01:00Z"
        self.assertIn("prediction_after_game_start", validate_sports_prediction(after_start))
        odds_after = dict(candidate)
        odds_after["odds_timestamp"] = "2026-07-04T20:01:00Z"
        self.assertIn("odds_after_game_start", validate_sports_prediction(odds_after))
        stale = dict(candidate)
        stale["prediction_timestamp"] = "2026-07-04T19:01:00Z"
        stale["odds_timestamp"] = "2026-07-04T17:00:00Z"
        self.assertIn("stale_odds", validate_sports_prediction(stale))
        future_odds = dict(candidate)
        future_odds["odds_timestamp"] = "2026-07-04T19:01:01Z"
        self.assertIn("odds_timestamp_after_prediction", validate_sports_prediction(future_odds))
        future_fetch = dict(candidate)
        future_fetch["api_fetched_at"] = "2026-07-04T19:01:01Z"
        self.assertIn("api_fetched_after_prediction", validate_sports_prediction(future_fetch))
        naive = dict(candidate)
        naive["prediction_timestamp"] = "2026-07-04T19:01:00"
        self.assertIn("invalid_timezone", validate_sports_prediction(naive))

    def test_source_blocked_and_parse_failed_handling(self):
        blocked = collect_sports_payload(api_key="", http=_FakeHttp(error=URLError("blocked")), date="20260704")
        self.assertEqual(blocked["blocker"], "blocked_public_source_unavailable")
        self.assertEqual(blocked["errors"][0]["reason"], "source_blocked")
        parsed = collect_sports_payload(api_key="", http=_FakeHttp(ValueError("bad-json")), date="20260704")
        self.assertEqual(parsed["blocker"], "blocked_public_source_unavailable")
        self.assertEqual(parsed["errors"][0]["reason"], "parse_failed")

    def test_low_confidence_rejected_rows_excluded_from_metrics(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "sports.sqlite"
            payload = _odds_payload()
            rejected = dict(payload["records"][0])
            rejected["rejection_reason"] = "low_confidence_event_match"
            payload["records"] = []
            payload["rejected_records"] = [rejected]
            result = log_sports_predictions(db, run_id="low-match", payload=payload)
            self.assertEqual(result["rejection_reasons"].get("low_confidence_event_match"), 1)
            report = build_sports_report(db, run_id="low-match")
            self.assertEqual(report["total_raw_predictions"], 0)
            self.assertEqual(report["low_confidence_event_match_count"], 1)

    def test_moneyline_spread_total_push_and_void_settlement(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "sports.sqlite"
            log_sports_predictions(db, run_id="settle", payload=_odds_payload())
            final = {"events": [{"event_id": "game-1", "home_score": 101, "away_score": 96, "status": "final"}]}
            settle_sports_predictions(db, run_id="settle", finals_payload=final)
            report = build_sports_report(db, run_id="settle")
            self.assertGreater(report["settled_raw_rows"], 0)
            self.assertGreater(report["accuracy"] or 0, 0)

            log_sports_predictions(db, run_id="push", payload=_odds_payload(point_shift=0.0))
            push_final = {"events": [{"event_id": "game-1", "home_score": 101, "away_score": 98.5, "status": "final"}]}
            settle_sports_predictions(db, run_id="push", finals_payload=push_final)
            self.assertGreater(build_sports_report(db, run_id="push")["push_count"], 0)

            log_sports_predictions(db, run_id="void", payload=_odds_payload())
            settle_sports_predictions(db, run_id="void", finals_payload={"events": [{"event_id": "game-1", "status": "canceled"}]})
            self.assertGreater(build_sports_report(db, run_id="void")["void_count"], 0)

    def test_missing_final_score_stays_unresolved_and_excluded(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "sports.sqlite"
            log_sports_predictions(db, run_id="unresolved", payload=_odds_payload())
            settle_sports_predictions(db, run_id="unresolved", finals_payload={"events": []})
            report = build_sports_report(db, run_id="unresolved")
            self.assertEqual(report["settled_raw_rows"], 0)
            self.assertEqual(report["accuracy"], None)
            self.assertEqual(report["win_rate"], None)
            self.assertEqual(report["win_rate_status"], "unavailable / no settled rows")

            ledger_entry = build_sports_validation_ledger_entry(report)
            self.assertIsNone(ledger_entry["win_rate"])
            self.assertEqual(ledger_entry["win_rate_status"], "unavailable / no settled rows")
            self.assertIn("unresolved", ledger_entry["metric_denominator_policy"])
            self.assertIn("rejected", ledger_entry["metric_denominator_policy"])

    def test_sports_validation_ledger_records_cycle_counts_without_counting_unresolved_losses(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "sports.sqlite"
            ledger = Path(directory) / "sports_validation_ledger.jsonl"
            log_result = log_sports_predictions(db, run_id="ledger", payload=_odds_payload())
            report = build_sports_report(db, run_id="ledger")

            entry = append_sports_validation_ledger(report, log_result=log_result, path=ledger)
            rows = read_sports_validation_ledger(ledger)

            self.assertEqual(len(rows), 1)
            self.assertEqual(entry["valid_sports_predictions_total"], 6)
            self.assertEqual(entry["valid_sports_predictions_logged_this_cycle"], 6)
            self.assertEqual(entry["deduped_settled_exposures"], 0)
            self.assertEqual(entry["loss_count"], 0)
            self.assertIsNone(entry["win_rate"])
            self.assertEqual(rows[0]["win_rate_status"], "unavailable / no settled rows")

    def test_sports_cycle_settles_from_public_finals_payload_and_records_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "sports.sqlite"
            output = Path(directory) / "odds.json"
            log_sports_predictions(db, run_id="cycle-finals", payload=_odds_payload())
            original_collect = sports_module.collect_sports_payload
            original_daily = sports_module.default_sports_daily_report_path
            original_all = sports_module.default_sports_all_report_path
            original_ledger = sports_module.default_sports_validation_ledger_path
            try:
                sports_module.collect_sports_payload = lambda: {
                    "asset_class": "sports",
                    "source_mode": "scraper",
                    "source": "espn_scoreboard",
                    "source_urls": ["https://example.test/scoreboard"],
                    "model_version": "sports_odds_research_v1",
                    "strategy": "pregame_odds_snapshot_v1",
                    "generated_at": "2026-07-04T23:01:00Z",
                    "records": [],
                    "schedule": [],
                    "finals": [{"event_id": "game-1", "home_score": 101, "away_score": 96, "status": "final"}],
                    "rejected_records": [],
                    "errors": [],
                    "blocker": None,
                }
                sports_module.default_sports_daily_report_path = lambda run_id: Path(directory) / f"{run_id}_daily_report.txt"
                sports_module.default_sports_all_report_path = lambda run_id: Path(directory) / f"{run_id}_all_report.txt"
                sports_module.default_sports_validation_ledger_path = lambda run_id: Path(directory) / f"{run_id}_validation_ledger.jsonl"
                result = sports_cycle(db, run_id="cycle-finals", output=output)
            finally:
                sports_module.collect_sports_payload = original_collect
                sports_module.default_sports_daily_report_path = original_daily
                sports_module.default_sports_all_report_path = original_all
                sports_module.default_sports_validation_ledger_path = original_ledger

            self.assertGreater(result["settle_result"]["rows_updated"], 0)
            self.assertGreater(result["report"]["settled_deduped_exposures"], 0)
            self.assertEqual(result["report"]["validation_ledger_status"], "recorded")
            self.assertNotEqual(result["report"]["win_rate_status"], "unavailable / no settled rows")

    def test_snapshot_duplicate_metric_filters_and_clv_field_is_evaluation_only(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "sports.sqlite"
            payload = _odds_payload()
            first = log_sports_predictions(db, run_id="snap", payload=payload)
            duplicate = log_sports_predictions(db, run_id="snap", payload=payload)
            repeat = log_sports_predictions(db, run_id="snap", payload=payload, prediction_timestamp="2026-07-04T19:02:00Z")
            changed = log_sports_predictions(db, run_id="snap", payload=_odds_payload(odds_shift=5.0), prediction_timestamp="2026-07-04T19:03:00Z")
            self.assertEqual(first["logged_predictions"], 6)
            self.assertEqual(duplicate["rejection_reasons"].get("exact_duplicate"), 6)
            self.assertEqual(repeat["rejection_reasons"].get("unchanged_repeat_snapshot"), 6)
            self.assertGreater(changed["logged_predictions"], 0)
            settle_sports_predictions(db, run_id="snap", finals_payload={"events": [{"event_id": "game-1", "home_score": 101, "away_score": 96, "status": "final"}]})
            report = build_sports_report(db, run_id="snap")
            self.assertIn("insufficient_sample", report["sample_size_status"])
            self.assertGreater(report["duplicate_exposure_warnings"], 0)

    def test_feature_export_excludes_final_score_outcome_and_profit_leakage(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "sports.sqlite"
            log_sports_predictions(db, run_id="export", payload=_odds_payload())
            settle_sports_predictions(db, run_id="export", finals_payload={"events": [{"event_id": "game-1", "home_score": 101, "away_score": 96, "status": "final"}]})
            features = Path(directory) / "features.csv"
            labels = Path(directory) / "labels.csv"
            result = export_sports_features(db, run_id="export", output=features, labels_output=labels)
            self.assertGreater(result["feature_rows"], 0)
            with features.open(newline="", encoding="utf-8") as handle:
                header = next(csv.reader(handle))
            self.assertNotIn("final_score_json", header)
            self.assertNotIn("actual_outcome", header)
            self.assertNotIn("profit_loss", header)
            with labels.open(newline="", encoding="utf-8") as handle:
                label_header = next(csv.reader(handle))
            self.assertIn("actual_outcome", label_header)
            self.assertIn("final_score_json", label_header)


if __name__ == "__main__":
    unittest.main()
