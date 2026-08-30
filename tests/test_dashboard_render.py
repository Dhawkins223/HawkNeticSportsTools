"""Golden render tests for the server-rendered dashboard.

These exercise `render_dashboard` end to end with a payload that passes the
freshness and exact-combo gates, so a change that silently stops showing
verified rows -- or that starts showing withheld ones -- fails here instead of
in a browser.
"""

from __future__ import annotations

import html
import json
import re
import unittest
from datetime import datetime, timedelta, timezone

from kalshi_research_bot.browser_fixtures import (
    build_browser_fixture_payload,
    make_verified_fixture_payload,
)
from kalshi_research_bot.auth import AuthPrincipal
from kalshi_research_bot.dashboard_assets import SCRIPT, stylesheet_css
from kalshi_research_bot.paper_server import (
    render_dashboard,
    render_login_page,
    render_operator_page,
)

# The stylesheet and script are served as files now; read what ships.
CSS = stylesheet_css()
JS = SCRIPT.body.decode("utf-8")


def principal(role: str) -> AuthPrincipal:
    return AuthPrincipal(username="tester", role=role, auth_method="session")


def bootstrap(rendered: str) -> dict:
    """The values the page hands its script, read back out of the markup."""
    match = re.search(r'data-paper="([^"]*)"', rendered)
    assert match, "page carries no bootstrap payload"
    return json.loads(html.unescape(match.group(1)))


class FixtureExercisesSlipArithmeticTests(unittest.TestCase):
    """The fixture has to reach the analysis engine, not just the render.

    The engine drops any leg without a fresh quote timestamp. The fixture
    omitted one, so every leg was skipped and the slip-arithmetic block showed
    "no analysis available" in every test, screenshot, and local preview -- the
    most involved part of the product was never once exercised outside
    production.
    """

    def setUp(self) -> None:
        self.payload = make_verified_fixture_payload()

    def test_priced_slips_produce_a_usable_analysis(self) -> None:
        from kalshi_research_bot.slip_report import build_slip_analysis

        for slip_key in ("primary", "leverage"):
            with self.subTest(slip=slip_key):
                report = build_slip_analysis(self.payload, slip_key, stake=5.0)
                self.assertTrue(
                    report["analysis_available"],
                    f"{slip_key} analysis unavailable: {report.get('detail')}",
                )
                self.assertEqual(report.get("skipped_legs") or [], [])
                analysis = report["analysis"]
                for field in ("hit_probability", "break_even_probability", "edge_over_break_even"):
                    self.assertIsInstance(analysis[field], float)

    def test_unrelated_games_do_not_share_an_event_id(self) -> None:
        # The correlation model keys off event_ticker, so deriving it from the
        # market ticker collided two separate games onto one event and scored
        # them as same-event correlated.
        for slip_key in ("custom_slip", "leverage_slip"):
            with self.subTest(slip=slip_key):
                legs = self.payload[slip_key]["legs"]
                tickers = [leg["event_ticker"] for leg in legs]
                self.assertEqual(len(tickers), len(set(tickers)))

    def test_the_rendered_card_shows_the_arithmetic(self) -> None:
        rendered = render_dashboard(self.payload, principal=principal("admin"))
        self.assertIn("Slip Arithmetic", rendered)
        self.assertIn("Needs to hit", rendered)
        self.assertIn("Estimated to hit", rendered)
        self.assertNotIn("No analysis available for this slip.", rendered)


class LegBreakdownTests(unittest.TestCase):
    """Per-leg price-versus-probability, surfaced from the analysis payload."""

    def setUp(self) -> None:
        self.payload = make_verified_fixture_payload()
        self.rendered = render_dashboard(self.payload, principal=principal("admin"))

    def test_identical_differences_get_identical_labels(self) -> None:
        # 0.86-0.84 and 0.84-0.82 are both two points, and in binary floating
        # point they land either side of the 0.02 threshold. Labelling them
        # differently would be the classifier reporting float noise.
        from kalshi_research_bot.paper_server import leg_edge_flag

        self.assertEqual(leg_edge_flag(0.86 - 0.84), leg_edge_flag(0.84 - 0.82))

    def test_flags_cover_every_sign(self) -> None:
        from kalshi_research_bot.paper_server import leg_edge_flag

        self.assertEqual(leg_edge_flag(-0.02)[0], "Priced over")
        self.assertEqual(leg_edge_flag(0.0)[0], "No edge")
        self.assertEqual(leg_edge_flag(0.005)[0], "Thin edge")
        self.assertEqual(leg_edge_flag(0.05)[0], "Good cushion")

    def test_breakdown_renders_a_row_for_every_analysed_leg(self) -> None:
        from kalshi_research_bot.slip_report import build_slip_analysis

        analysis = build_slip_analysis(self.payload, "primary", stake=5.0)["analysis"]
        self.assertIn(f"Leg breakdown ({len(analysis['legs'])})", self.rendered)
        for leg in analysis["legs"]:
            self.assertIn(html.escape(str(leg["selection"])), self.rendered)

    def test_breakdown_is_a_table_with_scoped_headers(self) -> None:
        # Numeric columns only stay comparable as a real table.
        self.assertIn('<th scope="col">Ask / break-even</th>', self.rendered)
        self.assertIn('<th scope="row">', self.rendered)
        self.assertIn("<caption>", self.rendered)

    def test_price_and_break_even_are_the_same_number(self) -> None:
        """The invariant that lets one column carry both.

        `slip_report` builds each leg with `decimal_odds = 100 / ask_cents`, and
        `SlipLeg.break_even` is `1 / decimal_odds`, so the ask in cents and the
        break-even in percent are the same figure. The table prints it once and
        says so. If that derivation ever changes, they stop being one number and
        the merged column starts lying -- so this fails here rather than in
        front of a reader.
        """
        from kalshi_research_bot.slip_report import build_slip_analysis

        analysis = build_slip_analysis(self.payload, "primary", stake=5.0)["analysis"]
        asks = {
            leg["market_ticker"]: float(leg["ask_cents"])
            for leg in self.payload["custom_slip"]["legs"]
        }
        self.assertTrue(analysis["legs"], "fixture produced no analysed legs")
        for leg in analysis["legs"]:
            self.assertAlmostEqual(
                float(leg["break_even"]) * 100.0,
                asks[leg["leg_id"]],
                places=9,
                msg=f"{leg['leg_id']}: break-even and ask have diverged",
            )

    def test_every_cell_carries_a_label_for_the_stacked_layout(self) -> None:
        # Below 560px the table reflows to one stacked block per leg and each
        # cell draws its own heading from `data-label`, because the column
        # headers are no longer above it. A cell without one renders as a bare
        # number with nothing to say what it measures.
        breakdown = re.search(
            r'<details class="leg-breakdown">.*?</details>', self.rendered, re.S
        )
        self.assertIsNotNone(breakdown, "no leg breakdown in the rendered page")
        cells = re.findall(r"<td\b[^>]*>", breakdown.group(0))
        self.assertTrue(cells)
        unlabelled = [cell for cell in cells if "data-label=" not in cell]
        self.assertEqual(unlabelled, [], "leg cells without a stacked-layout label")

    def test_scroll_container_ancestors_can_be_narrower_than_the_table(self) -> None:
        """Guards the fix for a page that scrolled sideways on a phone.

        A grid item defaults to `min-width: auto` and so refuses to lay out
        narrower than its content. With any step of the chain left at that
        default, the table's `overflow-x: auto` cannot clip: the ancestors widen
        instead, and the whole page scrolls sideways. Static assertion because a
        browser is the only other way to catch it.
        """
        for selector in (".panel", ".slip-card", ".slip-analysis", ".leg-breakdown"):
            with self.subTest(selector=selector):
                self.assertRegex(
                    CSS,
                    rf"(^|[,{{\s]){re.escape(selector)}\s*(,[^{{]*)?\{{[^}}]*min-width:\s*0",
                    f"{selector} must opt out of min-width:auto",
                )

    def test_empty_analysis_renders_nothing_rather_than_an_empty_table(self) -> None:
        from kalshi_research_bot.paper_server import render_leg_breakdown

        self.assertEqual(render_leg_breakdown({}), "")
        self.assertEqual(render_leg_breakdown({"legs": []}), "")


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

    def test_page_carries_no_inline_script(self) -> None:
        # The bootstrap payload rides on a data attribute so the CSP can refuse
        # inline script outright.
        self.assertNotIn("<script>", self.fresh)
        self.assertNotIn("<style>", self.fresh)

    def test_bootstrap_payload_cannot_break_out_of_its_attribute(self) -> None:
        payload = dict(self.payload)
        payload["generated_at"] = '2026-01-01T00:00:00+00:00" onload="alert(1)'
        rendered = render_dashboard(payload)
        self.assertNotIn('onload="alert(1)"', rendered)


class ViewerRoleTests(unittest.TestCase):
    """A reader who cannot refresh must not be shown controls that 403."""

    def setUp(self) -> None:
        self.payload = make_verified_fixture_payload()

    def test_admin_gets_the_refresh_control(self) -> None:
        rendered = render_dashboard(self.payload, principal=principal("admin"))
        self.assertIn('id="refresh-slip"', rendered)
        self.assertTrue(bootstrap(rendered)["can_refresh"])

    def test_reader_roles_get_no_refresh_control(self) -> None:
        for role in ("read_only", "researcher"):
            with self.subTest(role=role):
                rendered = render_dashboard(self.payload, principal=principal(role))
                self.assertNotIn('id="refresh-slip"', rendered)
                self.assertFalse(bootstrap(rendered)["can_refresh"])

    def test_missing_principal_is_treated_as_a_reader(self) -> None:
        rendered = render_dashboard(self.payload)
        self.assertFalse(bootstrap(rendered)["can_refresh"])

    def test_polling_uses_an_endpoint_every_role_may_read(self) -> None:
        # /quality.json is admin-only; polling it left other roles silently
        # stale, so the freshness poll must not go back to it.
        self.assertIn("/freshness.json", JS)
        self.assertNotIn("/quality.json", JS)


class CsrfTokenTests(unittest.TestCase):
    """The token has to survive a new tab, which per-tab storage does not."""

    def test_client_reads_the_csrf_cookie(self) -> None:
        self.assertIn("hawknetic_research_csrf=", JS)

    def test_csrf_cookie_is_readable_but_session_cookie_is_not(self) -> None:
        from kalshi_research_bot.paper_server import build_csrf_cookie, build_session_cookie

        session_cookie = build_session_cookie("session-value", secure=True)
        csrf_cookie = build_csrf_cookie("csrf-value", secure=True)
        self.assertIn("HttpOnly", session_cookie)
        self.assertNotIn("HttpOnly", csrf_cookie)
        for cookie in (session_cookie, csrf_cookie):
            self.assertIn("SameSite=Strict", cookie)
            self.assertIn("Secure", cookie)

    def test_cookies_drop_secure_off_a_hosted_runtime(self) -> None:
        from kalshi_research_bot.paper_server import build_csrf_cookie

        self.assertNotIn("Secure", build_csrf_cookie("csrf-value", secure=False))

    def test_logout_clears_both_cookies(self) -> None:
        from kalshi_research_bot.paper_server import clear_csrf_cookie, clear_session_cookie

        self.assertIn("Max-Age=0", clear_session_cookie(secure=False))
        self.assertIn("Max-Age=0", clear_csrf_cookie(secure=False))


def _srgb_channel(value: int) -> float:
    v = value / 255
    return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4


def _luminance(rgb: tuple[int, int, int]) -> float:
    r, g, b = (_srgb_channel(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast_ratio(fg: tuple[int, int, int], bg: tuple[int, int, int]) -> float:
    """WCAG 2.x relative-contrast ratio, lighter over darker."""
    hi, lo = sorted((_luminance(fg), _luminance(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def over(top: tuple[int, int, int], alpha: float, bottom: tuple[int, int, int]) -> tuple[int, int, int]:
    """Composite a translucent overlay onto an opaque backdrop."""
    return tuple(round(alpha * t + (1 - alpha) * b) for t, b in zip(top, bottom))


def css_token(name: str) -> tuple[int, int, int]:
    match = re.search(rf"^\s*{re.escape(name)}:\s*#([0-9a-fA-F]{{6}});", CSS, re.M)
    assert match, f"token {name} not found in the stylesheet"
    value = match.group(1)
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))


class TextContrastTests(unittest.TestCase):
    """The AA floor, asserted against the tokens that actually ship.

    Contrast was measured off the composited page rather than eyeballed: text
    made transparent, the page screenshotted, and the pixels behind each run
    sampled. That found `--text-muted` at 4.44:1 on the tinted ready-summary
    surface, just under the 4.5:1 floor. Re-running a browser in CI to catch a
    regression would be heavy, so the arithmetic is asserted here instead --
    the same formula, against the same colours the stylesheet declares.
    """

    ACCENT = (0, 230, 118)

    def surfaces(self) -> dict[str, tuple[int, int, int]]:
        surface_alt = css_token("--surface-alt")
        return {
            "--bg": css_token("--bg"),
            "--surface": css_token("--surface"),
            "--surface-alt": surface_alt,
            # `.ready-summary` lays a 10%-accent gradient over --surface-alt.
            # Text sits at the strong end of it, so that is the case to hold.
            ".ready-summary": over(self.ACCENT, 0.10, surface_alt),
        }

    def test_muted_text_clears_aa_on_every_surface_it_lands_on(self) -> None:
        muted = css_token("--text-muted")
        for name, background in self.surfaces().items():
            with self.subTest(surface=name):
                self.assertGreaterEqual(
                    contrast_ratio(muted, background),
                    4.5,
                    f"--text-muted is below WCAG AA on {name}",
                )

    def test_primary_and_secondary_text_clear_aa_too(self) -> None:
        for token in ("--text-primary", "--text-secondary"):
            colour = css_token(token)
            for name, background in self.surfaces().items():
                with self.subTest(token=token, surface=name):
                    self.assertGreaterEqual(contrast_ratio(colour, background), 4.5)

    def test_the_ratio_helper_agrees_with_known_values(self) -> None:
        # Anchor the formula so a bug in it cannot quietly pass the checks above.
        self.assertAlmostEqual(contrast_ratio((255, 255, 255), (0, 0, 0)), 21.0, places=6)
        self.assertAlmostEqual(contrast_ratio((0, 0, 0), (0, 0, 0)), 1.0, places=6)


class LabelledRegionTests(unittest.TestCase):
    """`aria-label` on a bare div is prohibited, and screen readers drop it.

    Both summaries carried one, so the names reached nobody: invisible to
    sighted readers by design, and discarded by assistive technology because a
    plain div exposes no role that can take a name.
    """

    def setUp(self) -> None:
        self.rendered = render_dashboard(make_verified_fixture_payload(), principal=principal("admin"))

    def test_labelled_groups_declare_a_role_that_can_carry_a_name(self) -> None:
        for match in re.finditer(r"<div\b[^>]*aria-label(?:ledby)?=[^>]*>", self.rendered):
            with self.subTest(tag=match.group(0)[:80]):
                self.assertIn("role=", match.group(0))

    def test_every_labelledby_points_at_an_element_that_exists(self) -> None:
        referenced = re.findall(r'aria-labelledby="([^"]+)"', self.rendered)
        self.assertTrue(referenced, "no aria-labelledby in the page")
        for group in referenced:
            for token in group.split():
                with self.subTest(id=token):
                    self.assertEqual(
                        len(re.findall(rf'id="{re.escape(token)}"', self.rendered)),
                        1,
                        f"aria-labelledby={token} must resolve to exactly one element",
                    )


class OperatorFacingDetailTests(unittest.TestCase):
    def setUp(self) -> None:
        self.payload = make_verified_fixture_payload()
        self.rendered = render_dashboard(self.payload, principal=principal("admin"))

    def test_every_page_carries_an_inline_favicon(self) -> None:
        for page in (self.rendered, render_login_page(), render_operator_page()):
            self.assertIn('rel="icon"', page)
            self.assertIn('name="theme-color"', page)

    def test_build_timestamps_are_localized_by_the_client(self) -> None:
        # The server renders in its own zone; without this the header clock and
        # the event clocks disagreed on the same page.
        self.assertIn('data-format="timestamp"', self.rendered)
        self.assertIn('dataset.format === "timestamp"', JS)

    def test_build_timestamp_keeps_a_server_rendered_fallback(self) -> None:
        from kalshi_research_bot.paper_server import timestamp_element

        element = timestamp_element("2026-08-17T04:44:00+00:00")
        self.assertIn("<time", element)
        self.assertIn('datetime="2026-08-17T04:44:00+00:00"', element)
        # Text between the tags is what a reader without script still sees.
        self.assertRegex(element, r">[^<]+</time>")

    def test_missing_timestamp_does_not_emit_an_empty_time_element(self) -> None:
        from kalshi_research_bot.paper_server import timestamp_element

        self.assertNotIn("<time", timestamp_element(None))

    def test_refresh_status_label_stays_inside_the_topbar(self) -> None:
        # It was absolutely positioned with no positioned ancestor, so it
        # anchored to the sticky topbar and hung below the header border.
        self.assertNotIn("top: 49px", CSS)

    def test_stylesheet_does_not_fight_itself_with_important(self) -> None:
        # The retired sheet carried 77 !important declarations layered over a
        # design that no longer rendered.
        self.assertLessEqual(CSS.count("!important"), 4)

    def test_clipboard_failure_has_a_fallback(self) -> None:
        self.assertIn("execCommand", JS)
        self.assertIn("Copy failed", JS)

    def test_stylesheet_and_script_are_served_as_cacheable_files(self) -> None:
        self.assertRegex(self.rendered, r'<link rel="stylesheet" href="/assets/app\.[0-9a-f]+\.css">')
        self.assertRegex(self.rendered, r'<script src="/assets/app\.[0-9a-f]+\.js" defer>')

    def test_inter_is_self_hosted_rather_than_fetched_from_a_cdn(self) -> None:
        # A strict CSP blocks font CDNs, so a declared-but-unshipped Inter
        # silently fell back to system fonts.
        self.assertIn("@font-face", CSS)
        self.assertRegex(CSS, r"/assets/inter-latin\.[0-9a-f]+\.woff2")
        self.assertNotIn("fonts.googleapis.com", CSS)
        self.assertNotIn("fonts.gstatic.com", CSS)

    def test_internal_reason_codes_are_explained(self) -> None:
        from kalshi_research_bot.paper_server import explain_state_reason

        explained = explain_state_reason("sports_board_unavailable:OperationalError")
        self.assertIn("sports database", explained.lower())
        self.assertIn("OperationalError", explained)
        # An unmapped code still shows rather than silently disappearing.
        self.assertEqual(explain_state_reason("something_new:X"), "something_new:X")
        self.assertEqual(explain_state_reason(""), "")

    def test_unreadable_sports_board_explains_itself(self) -> None:
        board = {
            "board_state": "unavailable",
            "is_current": False,
            "state_reason": "sports_board_unavailable:OperationalError",
            "events": [],
        }
        from kalshi_research_bot.paper_server import render_sports_section

        rendered = render_sports_section(board)
        self.assertIn("sports database", rendered.lower())
        # The raw code stays reachable for whoever is debugging it.
        self.assertIn("sports_board_unavailable:OperationalError", rendered)

    def test_each_page_links_the_script_that_drives_it(self) -> None:
        """Guard the page/asset split from the side that runs without a database.

        The equivalent sign-in assertion lives in a Postgres-gated test, so
        moving that script out of the markup broke only in CI.
        """
        from kalshi_research_bot.dashboard_assets import LOGIN_SCRIPT, OPS_SCRIPT

        login = render_login_page()
        self.assertRegex(login, r'<script src="/assets/login\.[0-9a-f]+\.js" defer>')
        self.assertIn("research_csrf_token", LOGIN_SCRIPT.body.decode("utf-8"))

        ops = render_operator_page()
        self.assertRegex(ops, r'<script src="/assets/ops\.[0-9a-f]+\.js" defer>')
        self.assertIn("operator-messages", OPS_SCRIPT.body.decode("utf-8"))

        for page in (self.rendered, login, ops):
            self.assertNotIn("<script>", page)

    def test_operator_queue_reports_a_failed_load(self) -> None:
        from kalshi_research_bot.dashboard_assets import OPS_SCRIPT

        ops = OPS_SCRIPT.body.decode("utf-8")
        self.assertIn("could not be", ops)
        self.assertIn("catch", ops)


class DashboardAssetTests(unittest.TestCase):
    """Guard against shipping CSS and JS that address markup nothing renders."""

    def setUp(self) -> None:
        payload = make_verified_fixture_payload()
        self.rendered_pages = [
            render_dashboard(payload, principal=principal("admin")),
            render_dashboard(payload, principal=principal("read_only")),
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

    def test_every_rendered_class_is_styled_or_used_by_script(self) -> None:
        """No class survives in markup unless something acts on it.

        Retired class names are how the previous stylesheet accumulated an
        override layer nobody could safely touch.
        """
        from kalshi_research_bot.dashboard_assets import LOGIN_SCRIPT, OPS_SCRIPT

        rendered_classes: set[str] = set()
        for page in self.rendered_pages:
            for attribute in re.findall(r'class="([^"]*)"', page):
                rendered_classes.update(token for token in attribute.split() if token)

        script_text = "\n".join(
            asset.body.decode("utf-8") for asset in (SCRIPT, LOGIN_SCRIPT, OPS_SCRIPT)
        )
        script_hooks = set(re.findall(r'classList\.(?:add|toggle|remove)\(["\']([^"\']+)', script_text))
        script_hooks |= set(re.findall(r'querySelector(?:All)?\(["\'][^"\']*?\.([\w-]+)', script_text))
        styled = set(re.findall(r"\.([A-Za-z][\w-]*)", CSS))

        orphans = sorted(rendered_classes - styled - script_hooks)
        self.assertEqual(orphans, [], f"classes rendered but never used: {orphans}")

    def test_stylesheet_has_no_leftover_layout_classes(self) -> None:
        # Classes from retired layouts keep accumulating override rules; this
        # names the ones already removed so they cannot quietly return.
        retired = {"hero", "hero-meta", "refresh-box", "cards", "ghost"}
        present = {name for name in retired if re.search(rf"\.{name}(?![\w-])", CSS)}
        self.assertEqual(present, set(), f"retired classes still styled: {sorted(present)}")


if __name__ == "__main__":
    unittest.main()
