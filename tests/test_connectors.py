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
from kalshi_research_bot.connectors.status import build_connectors_status
from kalshi_research_bot.sports_research import (
    build_sports_report,
    collect_sports_payload,
    log_sports_predictions,
    render_sports_report,
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

    def test_sports_scraper_mode_blocks_cleanly_without_public_source(self):
        blocked = collect_sports_payload(api_key="", http=_FakeHttp(error=URLError("blocked")), date="20260704")
        self.assertEqual(blocked["blocker"], "blocked_public_source_unavailable")
        with patch.dict(os.environ, {"SPORTS_SCRAPER_ENABLED": "false"}, clear=False):
            disabled = collect_sports_payload(api_key="", http=_FakeHttp(_espn_scoreboard_payload()), date="20260704")
        self.assertEqual(disabled["blocker"], "blocked_missing_sports_source")

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
        self.assertEqual(status["states"]["firecrawl"]["state"], "missing_required")
        self.assertEqual(status["states"]["google_drive"]["state"], "unconfigured_optional")
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["connectors-status"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Connector Status", buffer.getvalue())
        env_text = Path(".env.example").read_text(encoding="utf-8")
        for name in [
            "FIRECRAWL_API_KEY",
            "GOOGLE_DRIVE_ENABLED",
            "AIRTABLE_API_KEY",
            "SLACK_WEBHOOK_URL",
            "SPORTS_SOURCE_MODE",
            "SPORTS_SCRAPER_ENABLED",
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
