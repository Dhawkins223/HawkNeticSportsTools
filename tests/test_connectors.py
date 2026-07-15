import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

from kalshi_research_bot.cli import main
from kalshi_research_bot.connectors.airtable_status import (
    bot_run_payload,
    open_issue_payload,
    stage_gate_payload,
    sync_status,
)
from kalshi_research_bot.connectors.firecrawl import build_firecrawl_snapshot, fetch_public_page
from kalshi_research_bot.connectors.google_drive_archive import archive_files, drive_folder_for_path
from kalshi_research_bot.connectors.slack_alerts import build_alert_payload, send_alert
from kalshi_research_bot.connectors.source_adapters import (
    HttpJsonSourceAdapter,
    SourceCollectionResult,
    SourceRequest,
    collect_from_plan,
    configured_retrieval_plan,
)
from kalshi_research_bot.connectors.status import build_connectors_status
from kalshi_research_bot.sports_research import (
    build_sports_report,
    collect_sports_payload,
    log_sports_predictions,
    render_sports_report,
)


class _FakeResponse:
    def __init__(self, payload, fetched_at="2026-07-04T19:01:00Z", *, stale=False):
        self._payload = payload
        self.fetched_at = fetched_at
        self.status = 200
        self.stale = stale

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeHttp:
    def __init__(self, payload=None, error=None, *, stale=False):
        self.payload = payload
        self.error = error
        self.stale = stale

    def get_text(self, url, timeout=20):
        if self.error:
            raise self.error
        return _FakeResponse(self.payload, stale=self.stale)


def _espn_scoreboard_payload():
    return {
        "events": [
            {
                "id": "mlb-1",
                "date": "2026-07-04T20:00:00Z",
                "competitions": [
                    {
                        "date": "2026-07-04T20:00:00Z",
                        "status": {"type": {"name": "STATUS_SCHEDULED", "description": "Scheduled", "completed": False}},
                        "competitors": [
                            {"homeAway": "home", "team": {"displayName": "Home"}},
                            {"homeAway": "away", "team": {"displayName": "Away"}},
                        ],
                        "odds": [
                            {
                                "provider": {"name": "ESPN BET"},
                                "lastUpdated": "2026-07-04T19:00:00Z",
                                "homeTeamOdds": {"moneyLine": -125},
                                "awayTeamOdds": {"moneyLine": 105},
                            }
                        ],
                    }
                ],
            }
        ]
    }


class ConnectorTests(unittest.TestCase):
    def test_firecrawl_success_fixture_and_deterministic_hash(self):
        first = fetch_public_page(
            "https://example.test/odds",
            fetcher=lambda url, timeout: {
                "raw_text": "Home -125 Away +105",
                "raw_html": "<html>odds</html>",
                "status_code": 200,
                "api_fetched_at": "2026-07-04T19:01:00Z",
            },
            cache_snapshot=False,
        )
        second = build_firecrawl_snapshot(
            source_url="https://example.test/odds",
            api_fetched_at="2026-07-04T19:02:00Z",
            raw_text="Home -125 Away +105",
            raw_html="<html>odds</html>",
            status_code=200,
        )
        self.assertFalse(first["blocked"])
        self.assertEqual(first["connector_name"], "firecrawl")
        self.assertEqual(first["source_snapshot_hash"], second["source_snapshot_hash"])

    def test_firecrawl_blocked_captcha_login_paywall_fixture(self):
        blocked = fetch_public_page(
            "https://example.test/login",
            fetcher=lambda url, timeout: {
                "raw_text": "Please log in to continue. CAPTCHA required.",
                "raw_html": "<html>captcha</html>",
                "status_code": 403,
                "api_fetched_at": "2026-07-04T19:01:00Z",
            },
            cache_snapshot=False,
        )
        paywall = fetch_public_page(
            "https://example.test/paywall",
            fetcher=lambda url, timeout: {
                "raw_text": "Subscribe to continue",
                "status_code": 200,
                "api_fetched_at": "2026-07-04T19:01:00Z",
            },
            cache_snapshot=False,
        )
        self.assertTrue(blocked["blocked"])
        self.assertEqual(blocked["block_reason"], "source_blocked")
        self.assertEqual(paywall["block_reason"], "paywall_detected")

    def test_firecrawl_unavailable_and_timeout_do_not_fake_data(self):
        unavailable = fetch_public_page("https://example.test", env={}, cache_snapshot=False)
        timeout = fetch_public_page(
            "https://example.test/slow",
            fetcher=lambda url, timeout: (_ for _ in ()).throw(TimeoutError("slow")),
            cache_snapshot=False,
        )
        self.assertTrue(unavailable["blocked"])
        self.assertEqual(unavailable["error_reason"], "firecrawl_unconfigured")
        self.assertEqual(unavailable["raw_text"], "")
        self.assertEqual(timeout["block_reason"], "timeout")

    def test_sports_scraper_mode_runs_without_api_key_if_public_source_available(self):
        with patch.dict(os.environ, {"SPORTS_SCRAPER_ENABLED": "true"}, clear=False):
            payload = collect_sports_payload(api_key="", http=_FakeHttp(_espn_scoreboard_payload()), date="20260704")
        self.assertEqual(payload["source_mode"], "scraper")
        self.assertIsNone(payload["blocker"])
        self.assertGreater(len(payload["records"]), 0)
        self.assertEqual(payload["source_urls"][0].count("espn.com"), 1)
        self.assertEqual(payload["retrieval_method"], "http_json")
        self.assertEqual(payload["freshness_state"], "fresh")
        self.assertTrue(payload["raw_evidence"])
        self.assertEqual(payload["raw_evidence"][0]["retrieval_method"], "http_json")

    def test_sports_scraper_mode_blocks_cleanly_without_public_source(self):
        blocked = collect_sports_payload(api_key="", http=_FakeHttp(error=URLError("blocked")), date="20260704")
        self.assertEqual(blocked["blocker"], "blocked_public_source_unavailable")
        with patch.dict(os.environ, {"SPORTS_SCRAPER_ENABLED": "false"}, clear=False):
            disabled = collect_sports_payload(api_key="", http=_FakeHttp(_espn_scoreboard_payload()), date="20260704")
        self.assertEqual(disabled["blocker"], "blocked_missing_sports_source")

    def test_sports_stale_public_result_remains_blocked(self):
        blocked = collect_sports_payload(api_key="", http=_FakeHttp(_espn_scoreboard_payload(), stale=True), date="20260704")
        self.assertEqual(blocked["blocker"], "blocked_public_source_unavailable")
        self.assertEqual(blocked["freshness_state"], "blocked")
        self.assertEqual(blocked["raw_evidence"][0]["freshness_state"], "stale")
        self.assertEqual(blocked["errors"][0]["reason"], "stale_source_response")

    def test_sports_official_api_is_preferred_without_exposing_key(self):
        official_payload = [
            {
                "id": "mlb-1",
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
                                "outcomes": [
                                    {"name": "Home", "price": -125},
                                    {"name": "Away", "price": 105},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        payload = collect_sports_payload(
            api_key="private-test-key",
            http=_FakeHttp(official_payload),
            date="20260704",
            env={"SPORTS_RETRIEVAL_PLAN": "official_api,http_json,firecrawl"},
        )
        self.assertEqual(payload["source_mode"], "api")
        self.assertEqual(payload["retrieval_method"], "official_api")
        self.assertGreater(len(payload["records"]), 0)
        self.assertNotIn("private-test-key", "".join(payload["source_urls"]))

    def test_firecrawl_fallback_records_method_and_preserves_fetch_time(self):
        fallback = SourceCollectionResult(
            source_name="firecrawl",
            requested_resource="https://example.test/scoreboard",
            retrieval_method="firecrawl",
            source_observation_time="2026-07-04T19:01:00Z",
            received_time="2026-07-04T19:01:00Z",
            http_status=200,
            content_type="application/json",
            content_hash="fallback-hash",
            parser_version="sports_source_v2",
            freshness_deadline="2026-07-04T20:01:00Z",
            freshness_state="fresh",
            raw_evidence_reference="fallback-hash",
            validation_state="valid",
            raw_result=_espn_scoreboard_payload(),
        )
        with patch("kalshi_research_bot.sports_research.FirecrawlJsonSourceAdapter.collect", return_value=fallback):
            payload = collect_sports_payload(
                api_key="",
                http=_FakeHttp(error=URLError("blocked")),
                date="20260704",
                env={
                    "FIRECRAWL_API_KEY": "configured-test-value",
                    "FIRECRAWL_MODE": "optional",
                    "SPORTS_RETRIEVAL_PLAN": "http_json,firecrawl",
                },
            )
        self.assertEqual(payload["retrieval_method"], "firecrawl")
        self.assertEqual(payload["records"][0]["api_fetched_at"], "2026-07-04T19:01:00Z")
        self.assertEqual(payload["retrieval_attempts"][0]["status"], "rejected")
        self.assertEqual(payload["retrieval_attempts"][1]["status"], "accepted")

    def test_retrieval_plan_prefers_direct_http_over_browser(self):
        plan = configured_retrieval_plan("browser_dom,http_json")
        result, attempts, evidence = collect_from_plan(
            SourceRequest(
                resource="https://example.test/scoreboard",
                parser_version="test-v1",
                freshness_seconds=60,
            ),
            plan=plan,
            adapters={"http_json": HttpJsonSourceAdapter(source_name="public_json", http=_FakeHttp({"events": []}))},
        )
        self.assertEqual(plan, ["http_json", "browser_dom"])
        self.assertIsNotNone(result)
        self.assertEqual(attempts[0]["retrieval_method"], "http_json")
        self.assertEqual(len(evidence), 1)

    def test_browser_failure_never_becomes_false_success(self):
        class FailedBrowserAdapter:
            source_name = "browser"
            retrieval_method = "browser_dom"

            def collect(self, request):
                return SourceCollectionResult(
                    source_name=self.source_name,
                    requested_resource=request.resource,
                    retrieval_method=self.retrieval_method,
                    source_observation_time=None,
                    received_time="2026-07-04T19:01:00Z",
                    http_status=None,
                    content_type="text/html",
                    content_hash=None,
                    parser_version=request.parser_version,
                    freshness_deadline=None,
                    freshness_state="failed",
                    raw_evidence_reference=None,
                    validation_state="rejected",
                    rejection_count=1,
                    failure_reason="browser_failed",
                )

        result, attempts, _ = collect_from_plan(
            SourceRequest(
                resource="https://example.test/rendered",
                parser_version="test-v1",
                freshness_seconds=60,
            ),
            plan=["browser_dom"],
            adapters={"browser_dom": FailedBrowserAdapter()},
        )
        self.assertIsNone(result)
        self.assertEqual(attempts[0]["status"], "rejected")
        self.assertEqual(attempts[0]["reason"], "browser_failed")

    def test_google_drive_unavailable_and_folder_selection(self):
        result = archive_files([Path("missing.txt")], env={})
        self.assertEqual(result["status"], "archive_skipped_google_drive_unavailable")
        self.assertEqual(drive_folder_for_path("data/crypto_runs/run_stage3b_audit.txt"), "Research Bots/Audits")
        self.assertEqual(drive_folder_for_path("data/sports_runs/run_report.txt"), "Research Bots/Sports")

    def test_airtable_payloads_and_unavailable_sync(self):
        report = {
            "run_id": "r1",
            "total_raw_predictions": 4,
            "settled_deduped_exposures": 2,
            "unresolved_predictions": 1,
            "rejected_predictions": 1,
            "rejection_reasons": {"source_blocked": 1},
            "duplicate_exposure_warnings": 0,
            "gate_result": "blocked_sample_size",
        }
        payload = bot_run_payload(report, bot_name="crypto", asset_class="crypto", stage="Stage 3A", mode="private_research")
        gate = stage_gate_payload(bot_name="crypto", run_id="r1", current_stage="Stage 3A", current_count=2, required_count=100, gate_status="blocked_sample_size", next_action="collect")
        issue = open_issue_payload(severity="high", bot_name="sports", issue_type="source_blocked", description="public source blocked")
        result = sync_status({"bot_runs": [payload], "stage_gates": [gate], "open_issues": [issue]}, env={})
        self.assertFalse(payload["claims_allowed"])
        self.assertFalse(payload["ml_allowed"])
        self.assertEqual(result["status"], "airtable_sync_skipped_unavailable")
        self.assertEqual(issue["severity"], "high")

    def test_airtable_payload_accepts_list_shaped_rejection_reasons(self):
        report = {
            "run_id": "kalshi-run",
            "rejection_reasons": ["unchanged_repeat_snapshot", "prediction_after_event_start"],
            "duplicate_exposure_warnings": [],
        }
        payload = bot_run_payload(
            report,
            bot_name="kalshi",
            asset_class="kalshi",
            stage="Stage 3B Passive",
            mode="private_research",
        )
        self.assertEqual(payload["top_rejection_reason"], "unchanged_repeat_snapshot")

    def test_slack_unavailable_and_dedupe(self):
        alert = build_alert_payload(
            bot_name="crypto",
            asset_class="crypto",
            run_id="r1",
            severity="warn",
            event_type="tests_failed",
            message="tests failed",
        )
        self.assertEqual(alert["severity"], "warning")
        unavailable = send_alert(alert, env={})
        self.assertEqual(unavailable["status"], "slack_alert_skipped_unavailable")
        with tempfile.TemporaryDirectory() as directory:
            sent = []
            path = Path(directory) / "alerts.json"
            first = send_alert(alert, sender=lambda payload: sent.append(payload), state_path=path)
            second = send_alert(alert, sender=lambda payload: sent.append(payload), state_path=path)
        self.assertEqual(first["status"], "slack_alert_sent")
        self.assertEqual(second["status"], "slack_alert_deduped")
        self.assertEqual(len(sent), 1)

    def test_connector_status_command_and_env_example(self):
        status = build_connectors_status(env={"SPORTS_SOURCE_MODE": "scraper", "SPORTS_SCRAPER_ENABLED": "true"})
        self.assertEqual(status["firecrawl"], "unconfigured")
        self.assertEqual(status["states"]["firecrawl"]["state"], "unconfigured_optional")
        self.assertEqual(status["firecrawl_mode"], "optional")
        self.assertNotIn("FIRECRAWL_API_KEY", status["missing_env_vars"])
        required = build_connectors_status(env={"FIRECRAWL_MODE": "required"})
        self.assertEqual(required["states"]["firecrawl"]["state"], "missing_required")
        self.assertIn("FIRECRAWL_API_KEY", required["missing_env_vars"])
        disabled = build_connectors_status(env={"FIRECRAWL_MODE": "disabled", "FIRECRAWL_API_KEY": "configured"})
        self.assertEqual(disabled["states"]["firecrawl"]["state"], "disabled")
        self.assertEqual(status["states"]["google_drive"]["state"], "unconfigured_optional")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["connectors-status"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Connector Status", buffer.getvalue())
        env_text = Path(".env.example").read_text(encoding="utf-8")
        for name in [
            "FIRECRAWL_API_KEY",
            "FIRECRAWL_MODE",
            "GOOGLE_DRIVE_ENABLED",
            "AIRTABLE_API_KEY",
            "SLACK_WEBHOOK_URL",
            "SPORTS_SOURCE_MODE",
            "SPORTS_SCRAPER_ENABLED",
            "SPORTS_RETRIEVAL_PLAN",
        ]:
            self.assertIn(name, env_text)

    def test_reports_include_connector_status_without_metric_mutation(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Path(directory) / "sports.sqlite"
            payload = collect_sports_payload(api_key="", http=_FakeHttp(_espn_scoreboard_payload()), date="20260704")
            log_sports_predictions(db, run_id="connectors", payload=payload)
            report = build_sports_report(db, run_id="connectors")
            metric_snapshot = {
                "total_raw_predictions": report["total_raw_predictions"],
                "settled_deduped_exposures": report["settled_deduped_exposures"],
                "unresolved_predictions": report["unresolved_predictions"],
                "rejected_predictions": report["rejected_predictions"],
            }
            rendered = render_sports_report(report)
            self.assertIn("Connector status:", rendered)
            self.assertEqual(
                metric_snapshot,
                {
                    "total_raw_predictions": report["total_raw_predictions"],
                    "settled_deduped_exposures": report["settled_deduped_exposures"],
                    "unresolved_predictions": report["unresolved_predictions"],
                    "rejected_predictions": report["rejected_predictions"],
                },
            )


if __name__ == "__main__":
    unittest.main()
