import json
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
from kalshi_research_bot.paper_server import append_jsonl, build_quality_status, render_dashboard
from kalshi_research_bot.source_quality import (
    active_refresh_errors,
    build_data_quality_report,
    build_zero_heartbeat_diagnosis,
    evaluate_source_records,
    render_data_quality_report,
)


class QualityTests(unittest.TestCase):
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
