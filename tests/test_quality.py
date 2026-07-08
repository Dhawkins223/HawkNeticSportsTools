import json
import os
import sqlite3
import tempfile
import time
import unittest
import io
import urllib.error
from contextlib import redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from kalshi_research_bot.cli import main
from kalshi_research_bot.connectors.http import HttpClient
from kalshi_research_bot.paper_server import append_jsonl, build_quality_status, refresh_payload, render_dashboard
from kalshi_research_bot.source_quality import (
    active_refresh_errors,
    build_data_quality_report,
    build_zero_heartbeat_diagnosis,
    evaluate_source_records,
    render_data_quality_report,
)


class QualityTests(unittest.TestCase):
    def _refresh_fixture_payload(self) -> dict:
        return {
            "generated_at": "2099-07-03T16:00:00+00:00",
            "date": "2099-07-03",
            "games": [{"id": "game-1"}],
            "markets": [{"ticker": "MKT-1"}],
            "all_day_market_count": 0,
            "custom_slip": {
                "action": "BUILD_SLIP",
                "leg_count": 1,
                "legs": [
                    {
                        "display_event": "Team A vs Team B",
                        "event_ticker": "EVT-1",
                        "market_ticker": "MKT-1",
                        "side": "yes",
                        "status": "open",
                        "probability": 0.82,
                        "required_probability": 0.8,
                        "ask_cents": 82,
                        "bid_cents": 81,
                        "midpoint_cents": 81.5,
                        "event_start_time": "2099-07-03T20:00:00+00:00",
                        "market_close_time": "2099-07-03T20:30:00+00:00",
                        "api_fetched_at": "2099-07-03T15:59:00+00:00",
                        "source_updated_at": "2099-07-03T15:58:00+00:00",
                        "evidence_count": 4,
                        "research_mode": "source_backed",
                    }
                ],
            },
            "leverage_slip": {"action": "NO_SLIP", "leg_count": 0, "legs": []},
            "all_day_slip": {"action": "NO_SLIP", "leg_count": 0, "legs": []},
            "research_edge_slip": {"action": "NO_SLIP", "leg_count": 0, "legs": []},
        }

    def test_build_quality_status_reports_ok_with_fresh_slip(self):
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "custom_slip": {"leg_count": 2},
        }
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            error_path = Path(tmp) / "errors.jsonl"
            append_jsonl(audit_path, {"event": "refresh", "ok": True})
            status = build_quality_status(payload, audit_path, error_path)
        self.assertEqual(status["status"], "OK")
        self.assertEqual(status["slip_counts"]["primary"], 2)
        self.assertIn("cache", status["controls"])
        self.assertEqual(status["source_quality_gate"]["status"], "OK")
        self.assertFalse(status["metric_contamination_checks"]["auto_bet_enabled"])

    def test_build_quality_status_warns_on_refresh_error(self):
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "refresh_error": "boom",
        }
        with tempfile.TemporaryDirectory() as tmp:
            status = build_quality_status(payload, Path(tmp) / "audit.jsonl", Path(tmp) / "errors.jsonl")
        self.assertEqual(status["status"], "WATCH")
        self.assertIn("latest refresh has an error", status["warnings"])
        self.assertIn("latest_refresh_error", status["source_quality_gate"]["reasons"])

    def test_old_refresh_errors_do_not_keep_quality_in_watch_after_success(self):
        audit_rows = [
            {
                "ok": False,
                "started_at": "2026-07-05T12:00:00Z",
                "finished_at": "2026-07-05T12:00:10Z",
            },
            {
                "ok": True,
                "started_at": "2026-07-07T12:00:00Z",
                "finished_at": "2026-07-07T12:00:10Z",
            },
        ]
        errors = [
            {
                "error": "old sandbox networking error",
                "started_at": "2026-07-05T12:00:00Z",
                "finished_at": "2026-07-05T12:00:10Z",
            }
        ]
        active = active_refresh_errors(
            audit_rows=audit_rows,
            latest_errors=errors,
            now=datetime(2026, 7, 7, 12, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(active, [])

    def test_dashboard_renders_data_quality_panel(self):
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "custom_slip": {"action": "BUILD_SLIP", "leg_count": 1, "legs": [], "sports": []},
        }
        rendered = render_dashboard(payload)
        self.assertIn("Data Quality Gate", rendered)
        self.assertIn("Research Record", rendered)
        self.assertIn("Metric Guardrails", rendered)
        self.assertIn("LIVE_DATA_POLL_SECONDS", rendered)
        self.assertIn("/quality.json", rendered)
        with tempfile.TemporaryDirectory() as tmp:
            controls = build_quality_status(payload, Path(tmp) / "audit.jsonl", Path(tmp) / "errors.jsonl")["controls"]
        self.assertIn("/research-record.json", controls["api"])
        self.assertIn("manual", rendered.lower())

    def test_refresh_payload_logs_hosted_predictions_to_research_ledger(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data_path = root / "today.json"
            with patch.dict(os.environ, {"RESEARCH_DATA_DIR": str(root), "KALSHI_RUN_ID": "hosted_test"}, clear=False):
                with patch("kalshi_research_bot.today.write_today_payload", return_value=self._refresh_fixture_payload()):
                    status = refresh_payload(
                        data_path=data_path,
                        yyyymmdd="20260703",
                        target_probability=0.8,
                        min_leg_probability=None,
                        max_leg_probability=0.985,
                        min_legs=1,
                        max_legs=20,
                        stake_dollars=5,
                        leverage_min_leg_probability=0.75,
                        public_intel_path=None,
                    )

            self.assertTrue(status["ok"])
            self.assertTrue(status["ledger_ok"])
            self.assertEqual(status["ledger_run_id"], "hosted_test")
            self.assertEqual(status["ledger_attempted_predictions"], 1)
            self.assertEqual(status["ledger_logged_predictions"], 1)
            self.assertEqual(status["ledger_rejected_predictions"], 0)
            connection = sqlite3.connect(root / "evaluation.sqlite")
            try:
                count = connection.execute("SELECT COUNT(*) FROM prediction_logs").fetchone()[0]
                run_count = connection.execute("SELECT COUNT(*) FROM paper_test_runs WHERE run_id = 'hosted_test'").fetchone()[0]
            finally:
                connection.close()
            self.assertEqual(count, 1)
            self.assertEqual(run_count, 1)

    def test_refresh_payload_keeps_slip_live_when_ledger_logging_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("kalshi_research_bot.today.write_today_payload", return_value=self._refresh_fixture_payload()):
                with patch("kalshi_research_bot.paper_server.log_refresh_predictions", side_effect=RuntimeError("db locked")):
                    status = refresh_payload(
                        data_path=Path(tmp) / "today.json",
                        yyyymmdd="20260703",
                        target_probability=0.8,
                        min_leg_probability=None,
                        max_leg_probability=0.985,
                        min_legs=1,
                        max_legs=20,
                        stake_dollars=5,
                        leverage_min_leg_probability=0.75,
                        public_intel_path=None,
                    )

        self.assertTrue(status["ok"])
        self.assertFalse(status["ledger_ok"])
        self.assertIn("RuntimeError: db locked", status["ledger_error"])
        self.assertEqual(status["primary_leg_count"], 1)

    def test_evaluate_source_records_requires_hash_and_timestamps(self):
        gate = evaluate_source_records(
            [{"api_fetched_at": "2026-07-06T12:00:00Z"}],
            required_fields=("api_fetched_at", "source_snapshot_hash"),
            max_age_seconds=60,
            now=datetime(2026, 7, 6, 12, 0, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(gate["status"], "WATCH")
        self.assertEqual(gate["issue_counts"]["missing_source_snapshot_hash"], 1)

    def test_zero_heartbeat_diagnosis_treats_fresh_unchanged_as_no_material_change(self):
        payload = {
            "records": [
                {
                    "asset_class": "crypto",
                    "exchange": "coinbase",
                    "symbol": "BTC-USD",
                    "timeframe": "1m",
                    "candle_open_time": "2026-07-06T11:59:00Z",
                    "candle_close_time": "2026-07-06T12:00:00Z",
                    "open": 1,
                    "high": 1,
                    "low": 1,
                    "close": 1,
                    "volume": 1,
                    "api_fetched_at": "2026-07-06T12:00:00Z",
                    "source_snapshot_hash": "abc",
                }
            ],
            "errors": [],
        }
        report_text = "Heartbeat status: no_material_change\nLogged predictions: 0\nRejected predictions: 0\nSettled rows: 0"
        diagnosis = build_zero_heartbeat_diagnosis(
            crypto_payload=payload,
            crypto_report_text=report_text,
            now=datetime(2026, 7, 6, 12, 1, tzinfo=timezone.utc),
        )
        self.assertEqual(diagnosis["status"], "OK")
        self.assertEqual(diagnosis["diagnosis"], "unchanged_repeat_guard_or_no_eligible_settlement")

    def test_data_quality_report_and_cli_do_not_require_live_network(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            dashboard = root / "today.json"
            dashboard.write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-06T12:00:00Z",
                        "custom_slip": {"leg_count": 2},
                    }
                ),
                encoding="utf-8",
            )
            output = root / "quality.txt"
            json_output = root / "quality.json"
            report = build_data_quality_report(
                db_path=root / "missing.sqlite",
                dashboard_payload_path=dashboard,
                audit_path=root / "audit.jsonl",
                error_path=root / "errors.jsonl",
                now=datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc),
            )
            rendered = render_data_quality_report(report)
            self.assertIn("Private Research Data Quality Report", rendered)
            self.assertIn("Metric contamination checks", rendered)
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "data-quality",
                        "--db",
                        str(root / "missing.sqlite"),
                        "--dashboard-payload",
                        str(dashboard),
                        "--audit-path",
                        str(root / "audit.jsonl"),
                        "--error-path",
                        str(root / "errors.jsonl"),
                        "--output",
                        str(output),
                        "--json-output",
                        str(json_output),
                    ]
                )
            self.assertEqual(exit_code, 0)
            self.assertTrue(output.exists())
            self.assertTrue(json_output.exists())
            self.assertIn("no auto-betting", buffer.getvalue())

    def test_http_client_uses_cache(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok": true}'

        with tempfile.TemporaryDirectory() as tmp:
            client = HttpClient(cache_dir=tmp, cache_ttl_seconds=60)
            with patch("urllib.request.urlopen", return_value=FakeResponse()) as opener:
                first = client.get_text("https://example.com/data")
                second = client.get_text("https://example.com/data")
        self.assertEqual(json.loads(first.text), {"ok": True})
        self.assertEqual(second.text, first.text)
        self.assertEqual(opener.call_count, 1)

    def test_http_client_retries_rate_limit_once(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok": true}'

        error = urllib.error.HTTPError("https://example.com/data", 429, "Too Many Requests", {}, None)
        with tempfile.TemporaryDirectory() as tmp:
            client = HttpClient(
                cache_dir=tmp,
                cache_ttl_seconds=60,
                max_retries=1,
                retry_backoff_seconds=0,
            )
            with patch("urllib.request.urlopen", side_effect=[error, FakeResponse()]) as opener:
                response = client.get_text("https://example.com/data")
        self.assertEqual(json.loads(response.text), {"ok": True})
        self.assertFalse(response.from_cache)
        self.assertEqual(opener.call_count, 2)

    def test_http_client_stale_fallback_is_marked(self):
        class FakeResponse:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, traceback):
                return False

            def read(self):
                return b'{"ok": true}'

        url = "https://example.com/data"
        with tempfile.TemporaryDirectory() as tmp:
            client = HttpClient(cache_dir=tmp, cache_ttl_seconds=60)
            with patch("urllib.request.urlopen", return_value=FakeResponse()):
                client.get_text(url)
            cache_path = client._cache_path(url)
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            cached["saved_at"] = time.time() - 120
            cached["fetched_at"] = "2026-07-01T00:00:00Z"
            cache_path.write_text(json.dumps(cached), encoding="utf-8")
            fallback_client = HttpClient(
                cache_dir=tmp,
                cache_ttl_seconds=1,
                max_retries=0,
                allow_stale_on_error=True,
                max_stale_seconds=3600,
            )
            error = urllib.error.HTTPError(url, 429, "Too Many Requests", {}, None)
            with patch("urllib.request.urlopen", side_effect=error):
                response = fallback_client.get_text(url)
        self.assertTrue(response.from_cache)
        self.assertTrue(response.stale)
        self.assertEqual(response.stale_reason, "http_429")
        self.assertEqual(response.fetched_at, "2026-07-01T00:00:00Z")
        self.assertEqual(fallback_client.cache_status()["stale_fallback_count"], 1)

    def test_quality_gate_flags_stale_cache_fallback(self):
        payload = {
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "custom_slip": {"leg_count": 2},
            "source_cache_status": {"stale_fallback_count": 1},
        }
        with tempfile.TemporaryDirectory() as tmp:
            audit_path = Path(tmp) / "audit.jsonl"
            error_path = Path(tmp) / "errors.jsonl"
            append_jsonl(audit_path, {"event": "refresh", "ok": True})
            status = build_quality_status(payload, audit_path, error_path)
        self.assertEqual(status["status"], "WATCH")
        self.assertIn("stale_cache_fallback_used", status["source_quality_gate"]["reasons"])


if __name__ == "__main__":
    unittest.main()
