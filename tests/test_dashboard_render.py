"""Golden render tests for the server-rendered dashboard.

These exercise `render_dashboard` end to end with a payload that passes the
freshness and exact-combo gates, so a change that silently stops showing
verified rows -- or that starts showing withheld ones -- fails here instead of
in a browser.
"""

from __future__ import annotations

import re
import unittest
from datetime import datetime, timedelta, timezone

from kalshi_research_bot.browser_fixtures import (
    build_browser_fixture_payload,
    make_verified_fixture_payload,
)
from kalshi_research_bot.paper_server import (
    CSS,
    JS,
    render_dashboard,
    render_login_page,
    render_operator_page,
)


class DashboardRenderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = make_verified_fixture_payload()
        self.fresh = render_dashboard(self.payload)

    def test_fresh_payload_shows_verified_slip_rows(self) -> None:
        self.assertIn("Fresh data", self.fresh)
        self.assertIn("NYY @ BOS", self.fresh)
        self.assertIn("LAD @ SD", self.fresh)
        self.assertIn("PHI @ ATL", self.fresh)

    def test_fresh_payload_reports_ready_tier_counts(self) -> None:
        # Two of the four tiers build in the fixture; the summary must agree
        # with the panels rather than being computed from a stale field.
        self.assertIn("2/4", self.fresh)

    def test_stale_payload_withholds_every_slip_row(self) -> None:
        stale = dict(self.payload)
        stale["generated_at"] = (datetime.now(timezone.utc) - timedelta(hours=3)).isoformat()
        rendered = render_dashboard(stale)
        self.assertIn("Review blocked", rendered)
        self.assertNotIn("NYY @ BOS", rendered)
        self.assertNotIn("PHI @ ATL", rendered)
        self.assertIn("0/4", rendered)

    def test_refresh_failure_withholds_every_slip_row(self) -> None:
        failed = dict(self.payload)
        failed["refresh_error"] = "live_refresh_failed"
        rendered = render_dashboard(failed)
        self.assertIn("Review blocked", rendered)
        self.assertNotIn("NYY @ BOS", rendered)

    def test_empty_fixture_state_renders_without_slip_rows(self) -> None:
        empty = build_browser_fixture_payload(self.payload, "empty")
        rendered = render_dashboard(empty)
        self.assertNotIn("NYY @ BOS", rendered)
        self.assertIn("No Slip", rendered)

    def test_hostile_payload_text_is_escaped(self) -> None:
        hostile = dict(self.payload)
        hostile["combo_source_summary"] = {
            "active_kxmve_market_count": 1,
            "verified_current_day_contract_count": 1,
            "tiers": {},
        }
        hostile["dashboard_snapshot"] = {"source": "<script>alert(1)</script>"}
        rendered = render_dashboard(hostile)
        self.assertNotIn("<script>alert(1)</script>", rendered)

    def test_bootstrap_json_cannot_close_the_script_element(self) -> None:
        payload = dict(self.payload)
        payload["generated_at_note"] = "</script><script>alert(1)</script>"
        rendered = render_dashboard(payload)
        script_open = rendered.count("<script>")
        # Two intentional inline scripts: the bootstrap payload and the app JS.
        self.assertEqual(script_open, 2)


class DashboardAssetTests(unittest.TestCase):
    """Guard against shipping CSS and JS that address markup nothing renders."""

    def setUp(self) -> None:
        self.rendered_pages = [
            render_dashboard(make_verified_fixture_payload()),
            render_login_page(),
            render_operator_page(),
        ]

    def _element_ids(self) -> set[str]:
        ids: set[str] = set()
        for page in self.rendered_pages:
            ids.update(re.findall(r'id="([A-Za-z][\w-]*)"', page))
        return ids

    def test_javascript_only_targets_ids_that_exist(self) -> None:
        referenced = set(re.findall(r'querySelector\(["\']#([A-Za-z][\w-]*)', JS))
        missing = sorted(referenced - self._element_ids())
        self.assertEqual(missing, [], f"JS targets ids no page renders: {missing}")

    def test_stylesheet_has_no_leftover_layout_classes(self) -> None:
        # Classes from retired layouts keep accumulating override rules; this
        # names the ones already removed so they cannot quietly return.
        retired = {"hero", "hero-meta", "refresh-box", "cards", "ghost"}
        present = {name for name in retired if re.search(rf"\.{name}(?![\w-])", CSS)}
        self.assertEqual(present, set(), f"retired classes still styled: {sorted(present)}")


if __name__ == "__main__":
    unittest.main()
