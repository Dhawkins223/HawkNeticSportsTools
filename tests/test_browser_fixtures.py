import unittest

from kalshi_research_bot.browser_fixtures import (
    browser_fixture_refresh_status,
    build_browser_fixture_payload,
)


class BrowserFixtureTests(unittest.TestCase):
    def setUp(self):
        self.payload = {
            "generated_at": "2026-07-12T12:00:00+00:00",
            "games": [{"id": "game"}],
            "markets": [{"id": "market"}],
            "custom_slip": {"action": "BET_CANDIDATE", "legs": [{"id": 1}], "leg_count": 1},
            "leverage_slip": {"action": "BET_CANDIDATE", "legs": [{"id": 2}], "leg_count": 1},
            "all_day_slip": {"action": "BET_CANDIDATE", "legs": [{"id": 3}], "leg_count": 1},
            "research_edge_slip": {"action": "BET_CANDIDATE", "legs": [{"id": 4}], "leg_count": 1},
        }

    def test_empty_fixture_has_no_slip_rows(self):
        fixture = build_browser_fixture_payload(self.payload, "empty")
        self.assertEqual(fixture["games"], [])
        for key in ("custom_slip", "leverage_slip", "all_day_slip", "research_edge_slip"):
            self.assertEqual(fixture[key]["legs"], [])
            self.assertFalse(fixture[key]["manual_entry_ready"])

    def test_stale_and_error_fixtures_are_explicit(self):
        stale = build_browser_fixture_payload(self.payload, "stale")
        error = build_browser_fixture_payload(self.payload, "error")
        self.assertEqual(stale["generated_at"], "2000-01-01T00:00:00+00:00")
        self.assertEqual(error["refresh_error"], "browser_fixture_source_failed")

    def test_loading_status_is_not_reported_as_success(self):
        status = browser_fixture_refresh_status("loading")
        self.assertEqual(status["state"], "running")
        self.assertTrue(status["accepted"])


class ValidationServerRunsFromACleanCheckoutTests(unittest.TestCase):
    """The preview server has to show the dashboard working, or it teaches nothing.

    It used to fail three ways that all looked like defects in the dashboard
    rather than in the harness: it read a gitignored path that a clean checkout
    does not have, it left `DASHBOARD_PAYLOAD_SOURCE` at its `postgres` default
    so the fixture on disk was never opened, and its four-minute-old stamp aged
    past the 1800s freshness window 26 minutes in, so a server left running
    started serving the blocked page.

    Only the first was loud. These cover the two silent ones.
    """

    def script(self):
        import importlib.util
        import pathlib

        path = pathlib.Path(__file__).resolve().parent.parent / "scripts" / "browser_validation_server.py"
        spec = importlib.util.spec_from_file_location("browser_validation_server", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def gate(self, payload):
        from kalshi_research_bot.paper_server import safe_dashboard_payload

        return safe_dashboard_payload(payload).get("public_data_gate") or {}

    def test_a_fixture_built_with_no_source_clears_the_freshness_gate(self):
        # No arguments, no `data/` directory, no database: still a live page.
        payload = self.script().build_fixture(None, "live")
        self.assertEqual(self.gate(payload).get("status"), "ready")

    def test_each_build_is_stamped_fresh_rather_than_reused(self):
        """What keeps a long-running server off the blocked page.

        The fixture is built four minutes old and the dashboard blocks at
        1800s, so a payload written once at startup goes stale 26 minutes in.
        Rebuilding per request is the fix, and this is what proves the rebuild
        actually restamps instead of returning the same object.
        """
        build = self.script().build_fixture
        first = build(None, "live")["generated_at"]
        second = build(None, "live")["generated_at"]
        self.assertNotEqual(first, second, "the fixture is not restamped, so it will age out")

    def test_an_aged_fixture_really_would_block(self):
        # The guard above only matters if staleness blocks; assert that rather
        # than trusting it, so this pair cannot both quietly stop meaning
        # anything if the window changes.
        from datetime import datetime, timedelta, timezone

        from kalshi_research_bot.browser_fixtures import make_verified_fixture_payload

        aged = make_verified_fixture_payload(now=datetime.now(timezone.utc) - timedelta(hours=2))
        self.assertEqual(self.gate(aged).get("status"), "blocked")

    def test_publishing_is_atomic_under_concurrent_readers(self):
        """The server is threaded and one page load is many requests.

        Rewriting the fixture in place truncates it while another thread is
        reading, and a half-written payload does not parse -- which the
        dashboard renders as the blocked page. Measured at 26 of 60 concurrent
        loads before this was a rename.

        The mechanism is what gets asserted, not a race. Racing for it is not
        reliable here: building the payload dominates each publish, so readers
        rarely land inside the write window, and a version of this test that
        hammered it passed happily against the in-place write it exists to
        reject.
        """
        import json
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch

        module = self.script()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.json"

            real_replace = os.replace
            published = []

            def record(src, dst):
                # The target must never be open for writing at this point: the
                # bytes are already on disk under another name.
                published.append((Path(src).parent, Path(dst)))
                return real_replace(src, dst)

            with patch.object(os, "replace", record):
                module.publish_fixture(path, None, "live")

            self.assertEqual(
                [dst for _, dst in published],
                [path],
                "the fixture is not published by rename, so a reader can see it half-written",
            )
            # Renaming across filesystems is not atomic; the scratch file has to
            # be a sibling of the target.
            self.assertEqual(published[0][0], path.parent)
            self.assertTrue(json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual(
                sorted(p.name for p in path.parent.iterdir()),
                ["payload.json"],
                "a scratch file was left beside the fixture",
            )

    def test_the_preview_viewer_is_not_claimed_to_hold_a_session(self):
        """Claiming a session it does not have breaks every POST.

        `valid_session_csrf` waves through any principal whose auth_method is
        not `session`, and checks a real token for one that is. The preview
        principal is synthetic and has no session to check against, so calling
        it `session` made the admin refresh control fail with "Session CSRF
        validation failed" rather than doing anything.
        """
        principal = self.script().preview_principal("admin")
        self.assertEqual(principal.role, "admin")
        self.assertNotEqual(
            principal.auth_method,
            "session",
            "a synthetic principal has no session, so session CSRF validation can only reject it",
        )

    def test_the_payload_source_is_pinned_to_the_file_the_script_writes(self):
        # Left at its `postgres` default, `load_current_payload` never opens the
        # fixture and every page renders blocked with no error anywhere.
        import os
        import sys
        from unittest.mock import patch

        module = self.script()
        with patch.dict(os.environ, {"DASHBOARD_PAYLOAD_SOURCE": "postgres"}, clear=False):
            with patch.object(sys, "argv", ["browser_validation_server.py", "--port", "0"]):
                with patch("http.server.ThreadingHTTPServer.serve_forever", side_effect=KeyboardInterrupt):
                    module.main()
            self.assertEqual(os.environ["DASHBOARD_PAYLOAD_SOURCE"], "file")


if __name__ == "__main__":
    unittest.main()
