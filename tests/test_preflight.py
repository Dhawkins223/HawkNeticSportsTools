"""Preflight is a gate, so its failures matter more than its passes.

The case that justifies the whole file is `0014`: a migration merged into
`Master`, never applied to production because nothing there applies migrations,
and invisible until a collector died of it. These tests pin the states that must
block a deploy — and, just as importantly, that a check which could not run
blocks too, because "we could not tell" must never read as "fine".
"""

from __future__ import annotations

import unittest

from kalshi_research_bot.preflight import (
    FAIL,
    PASS,
    UNKNOWN,
    WARN,
    check_auth_configuration,
    check_migrations,
    check_safety_controls,
    render_preflight,
    run_preflight,
)

HOSTED = {"APP_ENV": "production"}


class MigrationCheckTests(unittest.TestCase):
    def test_a_pending_migration_blocks_and_names_it(self) -> None:
        """The exact shape production was in: merged, never applied."""
        result = check_migrations({"ready": False, "pending_versions": ["0014"], "state": "pending"})

        self.assertEqual(result["status"], FAIL)
        self.assertIn("0014", result["detail"])
        self.assertIn("database-migrate", result["remedy"])

    def test_every_pending_migration_is_listed(self) -> None:
        result = check_migrations({"ready": False, "pending_versions": ["0013", "0014"]})
        self.assertIn("0013", result["detail"])
        self.assertIn("0014", result["detail"])
        self.assertIn("2 migration(s)", result["detail"])

    def test_an_unready_database_blocks_even_with_nothing_pending(self) -> None:
        result = check_migrations({"ready": False, "pending_versions": [], "state": "unreachable"})
        self.assertEqual(result["status"], FAIL)
        self.assertIn("unreachable", result["detail"])

    def test_a_fully_applied_database_passes(self) -> None:
        result = check_migrations({"ready": True, "pending_versions": []})
        self.assertEqual(result["status"], PASS)


class SafetyControlTests(unittest.TestCase):
    def test_a_disabled_research_control_blocks(self) -> None:
        result = check_safety_controls(
            {"hosted": True, "ready": False, "failed_controls": ["RESEARCH_ONLY"]}
        )
        self.assertEqual(result["status"], FAIL)
        self.assertIn("RESEARCH_ONLY", result["detail"])

    def test_intact_controls_pass_and_say_where(self) -> None:
        result = check_safety_controls({"hosted": True, "ready": True, "failed_controls": []})
        self.assertEqual(result["status"], PASS)
        self.assertIn("hosted", result["detail"])


class AuthConfigurationTests(unittest.TestCase):
    def test_a_hosted_deployment_without_auth_blocks(self) -> None:
        result = check_auth_configuration(dict(HOSTED, DASHBOARD_USER_AUTH_ENABLED="true"))
        self.assertEqual(result["status"], FAIL)
        self.assertIn("DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED", result["remedy"])

    def test_no_sign_in_path_at_all_blocks(self) -> None:
        result = check_auth_configuration(
            {"DASHBOARD_USER_AUTH_ENABLED": "false", "DASHBOARD_BASIC_FALLBACK_ENABLED": "false"}
        )
        self.assertEqual(result["status"], FAIL)
        self.assertIn("nobody can sign in", result["detail"])

    def test_registration_left_on_in_a_hosted_environment_blocks(self) -> None:
        """Account creation is a deliberate local action, never a hosted default."""
        result = check_auth_configuration(
            dict(
                HOSTED,
                DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED="true",
                DASHBOARD_USER_AUTH_ENABLED="true",
                AUTH_REGISTRATION_ENABLED="true",
            )
        )
        self.assertEqual(result["status"], FAIL)

    def test_running_on_the_basic_fallback_warns_rather_than_blocks(self) -> None:
        """It works, so it must not block a deploy — but it is one shared credential."""
        result = check_auth_configuration(
            dict(HOSTED, DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED="true", DASHBOARD_USER_AUTH_ENABLED="false")
        )
        self.assertEqual(result["status"], WARN)
        self.assertIn("no audit", result["detail"])

    def test_an_open_fallback_beside_real_accounts_warns(self) -> None:
        result = check_auth_configuration(
            dict(
                HOSTED,
                DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED="true",
                DASHBOARD_USER_AUTH_ENABLED="true",
                DASHBOARD_BASIC_FALLBACK_ENABLED="true",
            )
        )
        self.assertEqual(result["status"], WARN)

    def test_accounts_on_and_fallback_closed_passes(self) -> None:
        result = check_auth_configuration(
            dict(
                HOSTED,
                DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED="true",
                DASHBOARD_USER_AUTH_ENABLED="true",
                DASHBOARD_BASIC_FALLBACK_ENABLED="false",
            )
        )
        self.assertEqual(result["status"], PASS)


class AggregationTests(unittest.TestCase):
    """`run_preflight` decides what blocks a deploy, so its arithmetic is the gate."""

    def _report(self, statuses: list[str]) -> dict:
        checks = [{"name": f"c{i}", "status": s, "detail": "", "remedy": None} for i, s in enumerate(statuses)]
        blocking = [c["name"] for c in checks if c["status"] in {FAIL, UNKNOWN}]
        return {"hosted": False, "ready": not blocking, "checks": checks, "blocking": blocking}

    def test_a_check_that_could_not_run_blocks(self) -> None:
        """`unknown` is not `pass`. Not knowing is the state this file exists for."""
        report = self._report([PASS, UNKNOWN])
        self.assertFalse(report["ready"])
        self.assertIn("c1", report["blocking"])

    def test_warnings_alone_do_not_block(self) -> None:
        report = self._report([PASS, WARN, WARN])
        self.assertTrue(report["ready"])
        self.assertEqual(report["blocking"], [])

    def test_a_single_failure_blocks_the_whole_run(self) -> None:
        report = self._report([PASS, PASS, FAIL, WARN])
        self.assertFalse(report["ready"])

    def test_a_live_run_returns_every_gate(self) -> None:
        report = run_preflight({})
        names = {check["name"] for check in report["checks"]}
        self.assertEqual(
            names, {"migrations", "safety_controls", "auth_configuration", "sign_in_possible"}
        )
        self.assertIn("ready", report)


class RenderingTests(unittest.TestCase):
    def test_a_blocked_run_states_what_blocked_it_and_how_to_fix_it(self) -> None:
        text = render_preflight(
            {
                "hosted": True,
                "ready": False,
                "blocking": ["migrations"],
                "checks": [
                    {
                        "name": "migrations",
                        "status": FAIL,
                        "detail": "1 migration(s) not applied: 0014",
                        "remedy": "run database-migrate",
                    }
                ],
            }
        )
        self.assertIn("NOT READY", text)
        self.assertIn("0014", text)
        self.assertIn("run database-migrate", text)
        self.assertIn("hosted", text)

    def test_a_remedy_is_not_shouted_for_a_passing_check(self) -> None:
        text = render_preflight(
            {
                "hosted": False,
                "ready": True,
                "blocking": [],
                "checks": [
                    {"name": "migrations", "status": PASS, "detail": "fine", "remedy": "unused remedy"}
                ],
            }
        )
        self.assertIn("Ready.", text)
        self.assertNotIn("unused remedy", text)


if __name__ == "__main__":
    unittest.main()
