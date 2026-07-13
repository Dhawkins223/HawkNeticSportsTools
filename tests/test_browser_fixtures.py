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


if __name__ == "__main__":
    unittest.main()
