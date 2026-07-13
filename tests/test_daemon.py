import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from kalshi_research_bot.bot_company import bot_company_summary, render_bot_company
from kalshi_research_bot.cli import main
from kalshi_research_bot.daemon import build_daemon_status, default_always_on_tasks, render_daemon_status


class DaemonTests(unittest.TestCase):
    def test_always_on_tasks_are_research_only(self):
        tasks = default_always_on_tasks()
        names = {task["name"] for task in tasks}
        self.assertIn("platform_foreman", names)
        self.assertIn("crypto_market_scout", names)
        self.assertIn("sports_public_source_scout", names)
        self.assertIn("kalshi_settlement_clerk", names)
        self.assertIn("quality_auditor", names)
        self.assertIn("daily_briefing_chief", names)
        combined = " ".join(task["command"].lower() for task in tasks)
        self.assertNotIn("order", combined)
        self.assertNotIn("trade", combined)
        self.assertNotIn("bet", combined)

    def test_bot_company_roster_and_cli_are_guarded(self):
        summary = bot_company_summary()
        self.assertGreaterEqual(summary["bot_count"], 10)
        self.assertFalse(summary["guardrails"]["auto_trade_enabled"])
        self.assertFalse(summary["guardrails"]["auto_bet_enabled"])
        self.assertFalse(summary["guardrails"]["kalshi_order_upload_enabled"])
        rendered = render_bot_company(summary)
        self.assertIn("Private Research Bot Company", rendered)
        self.assertIn("Quality Auditor", rendered)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["company-status"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Private Research Bot Company", buffer.getvalue())

    def test_daemon_status_handles_dashboard_unavailable(self):
        status = build_daemon_status(opener=lambda url: (_ for _ in ()).throw(TimeoutError("offline")))
        self.assertEqual(status["dashboard"]["status"], "unavailable")
        self.assertFalse(status["guardrails"]["auto_trade_enabled"])
        self.assertFalse(status["guardrails"]["auto_bet_enabled"])
        self.assertFalse(status["guardrails"]["kalshi_order_upload_enabled"])
        self.assertEqual(status["guardrails"]["account_handoff_policy"], "manual_review_only")

    def test_daemon_status_render_and_cli(self):
        status = build_daemon_status(
            opener=lambda url: {
                "status": "OK",
                "generated_at": "2026-07-06T13:00:00-04:00",
                "data_age_seconds": 60,
                "slip_counts": {"primary": 20},
                "warnings": [],
            }
        )
        rendered = render_daemon_status(status)
        self.assertIn("Private Research Daemon Status", rendered)
        self.assertIn("kalshi_order_upload_enabled: False", rendered)

        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["daemon-status", "--dashboard-url", "http://127.0.0.1:1"])
        self.assertEqual(exit_code, 0)
        self.assertIn("Private Research Daemon Status", buffer.getvalue())

    def test_daemon_scripts_and_env_documentation_exist(self):
        for path in [
            "scripts/install_tasks.ps1",
            "scripts/uninstall_tasks.ps1",
            "scripts/dashboard_watchdog.ps1",
            "scripts/crypto_cycle.cmd",
            "scripts/crypto_diagnostics.cmd",
            "scripts/sports_cycle.cmd",
            "scripts/kalshi_passive_check.cmd",
            "scripts/source_health.cmd",
            "scripts/data_quality.cmd",
            "scripts/feature_exports.cmd",
            "scripts/qa_daily.cmd",
            "scripts/archive_reports.cmd",
            "scripts/status_sync.cmd",
            "scripts/company_brief.cmd",
            "scripts/company_status.cmd",
            "scripts/daemon_status.cmd",
            "data/always_on_handoff.md",
        ]:
            self.assertTrue(Path(path).exists(), path)

        install_text = Path("scripts/install_tasks.ps1").read_text(encoding="utf-8")
        self.assertIn("DashboardWatchdog", install_text)
        self.assertIn("CryptoStage3A", install_text)
        self.assertIn("SportsScraperStage3A", install_text)
        self.assertIn("KalshiPassiveCheck", install_text)
        self.assertIn("QualityAuditDaily", install_text)
        self.assertIn("CompanyBriefDaily", install_text)
        self.assertIn("No auto-trading", install_text)

        live_text = Path("scripts/live.cmd").read_text(encoding="utf-8")
        watchdog_text = Path("scripts/dashboard_watchdog.ps1").read_text(encoding="utf-8")
        test_cmd_text = Path("scripts/test.cmd").read_text(encoding="utf-8")
        test_ps1_text = Path("scripts/test.ps1").read_text(encoding="utf-8")
        self.assertIn("--refresh-seconds 300", live_text)
        self.assertIn("--refresh-seconds 300", watchdog_text)
        self.assertIn('pushd "%repo%"', test_cmd_text.lower())
        self.assertIn("Push-Location $repo", test_ps1_text)

        env_text = Path(".env.example").read_text(encoding="utf-8")
        for name in [
            "RESEARCH_DAEMON_ENABLED",
            "RESEARCH_DASHBOARD_PORT",
            "CRYPTO_RUN_ID",
            "SPORTS_RUN_ID",
            "KALSHI_RUN_ID",
            "KALSHI_ORDER_UPLOAD_ENABLED=false",
        ]:
            self.assertIn(name, env_text)

        handoff = Path("data/always_on_handoff.md").read_text(encoding="utf-8")
        self.assertIn("No Kalshi account order upload", handoff)
        self.assertIn("manual", handoff.lower())


if __name__ == "__main__":
    unittest.main()
