from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import patch

from kalshi_research_bot.auth import LocalAuthStore
from kalshi_research_bot.database import production_safety_status
from kalshi_research_bot.dashboard_assets import LOGIN_SCRIPT
from kalshi_research_bot.paper_server import (
    OPERATOR_ACTION_VALUE,
    REFRESH_ACTION_VALUE,
    authenticate_dashboard_request,
    build_session_cookie,
    dashboard_auth_configured,
    render_login_page,
    dashboard_auth_enabled,
    dashboard_security_headers,
    hosted_runtime,
    user_auth_enabled,
    valid_dashboard_auth,
    valid_json_content_type,
    valid_refresh_action,
    valid_research_action,
)
from tests.postgres_support import PostgresTestCase


def basic_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


class PaperServerAuthTests(PostgresTestCase):
    def test_hosted_readiness_requires_explicit_research_safety_controls(self) -> None:
        with patch.dict(os.environ, {"APP_ENV": "staging"}, clear=True):
            status = production_safety_status()

        self.assertFalse(status["ready"])
        self.assertIn("KALSHI_ORDER_UPLOAD_ENABLED", status["failed_controls"])
        self.assertIn("DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED", status["failed_controls"])

    def test_hosted_readiness_rejects_order_upload_or_disabled_auth_requirement(self) -> None:
        environment = {
            "APP_ENV": "production",
            "RESEARCH_ONLY": "true",
            "LIVE_EXECUTION_ENABLED": "false",
            "AUTO_UPLOAD_ENABLED": "false",
            "AUTO_TRADE_ENABLED": "false",
            "KALSHI_ORDER_UPLOAD_ENABLED": "true",
            "MODEL_PROMOTION_ENABLED": "false",
            "STALE_CACHE_AS_FRESH": "false",
            "DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED": "false",
        }
        with patch.dict(os.environ, environment, clear=True):
            status = production_safety_status()

        self.assertFalse(status["ready"])
        self.assertIn("KALSHI_ORDER_UPLOAD_ENABLED", status["failed_controls"])
        self.assertIn("DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED", status["failed_controls"])

    def test_hosted_readiness_accepts_explicit_safe_controls(self) -> None:
        environment = {
            "RAILWAY_PROJECT_ID": "staging-project",
            "RESEARCH_ONLY": "true",
            "LIVE_EXECUTION_ENABLED": "false",
            "AUTO_UPLOAD_ENABLED": "false",
            "AUTO_TRADE_ENABLED": "false",
            "KALSHI_ORDER_UPLOAD_ENABLED": "false",
            "MODEL_PROMOTION_ENABLED": "false",
            "STALE_CACHE_AS_FRESH": "false",
            "DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED": "true",
        }
        with patch.dict(os.environ, environment, clear=True):
            status = production_safety_status()

        self.assertTrue(status["ready"])
        self.assertEqual(status["failed_controls"], [])

    def test_dashboard_auth_disabled_without_password(self) -> None:
        env = {}

        self.assertFalse(dashboard_auth_enabled(env))
        self.assertTrue(valid_dashboard_auth(None, env))

    def test_dashboard_auth_enabled_by_password(self) -> None:
        env = {"DASHBOARD_AUTH_PASSWORD": "secret"}

        self.assertTrue(dashboard_auth_enabled(env))
        self.assertTrue(valid_dashboard_auth(basic_header("hawknetic", "secret"), env))

    def test_dashboard_auth_rejects_wrong_password(self) -> None:
        env = {"DASHBOARD_AUTH_USERNAME": "owner", "DASHBOARD_AUTH_PASSWORD": "secret"}

        self.assertFalse(valid_dashboard_auth(basic_header("owner", "wrong"), env))
        self.assertFalse(valid_dashboard_auth(basic_header("hawknetic", "secret"), env))

    def test_dashboard_auth_enabled_without_password_rejects_all(self) -> None:
        env = {"DASHBOARD_AUTH_ENABLED": "true"}

        self.assertTrue(dashboard_auth_enabled(env))
        self.assertFalse(valid_dashboard_auth(basic_header("hawknetic", "secret"), env))

    def test_hosted_dashboard_requires_auth_by_default(self) -> None:
        env = {"RAILWAY_PROJECT_ID": "project-id"}

        self.assertTrue(hosted_runtime(env))
        self.assertTrue(dashboard_auth_enabled(env))
        self.assertFalse(valid_dashboard_auth(None, env))

    def test_hosted_auth_requirement_can_be_explicitly_disabled(self) -> None:
        env = {
            "RAILWAY_PROJECT_ID": "project-id",
            "DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED": "false",
        }

        self.assertFalse(dashboard_auth_enabled(env))

    def test_refresh_action_requires_same_origin_custom_header(self) -> None:
        self.assertTrue(valid_refresh_action({"X-Research-Action": "refresh-dashboard"}))
        self.assertFalse(valid_refresh_action({}))

    def test_dashboard_security_headers_block_embedding_and_sniffing(self) -> None:
        headers = dashboard_security_headers()

        self.assertEqual(headers["X-Frame-Options"], "DENY")
        self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_basic_fallback_has_explicit_role(self) -> None:
        env = {
            "DASHBOARD_AUTH_PASSWORD": "secret",
            "DASHBOARD_AUTH_USERNAME": "owner",
            "DASHBOARD_BASIC_FALLBACK_ENABLED": "true",
            "DASHBOARD_BASIC_AUTH_ROLE": "read_only",
        }
        principal = authenticate_dashboard_request(basic_header("owner", "secret"), env=env)
        self.assertEqual(principal.role, "read_only")
        self.assertEqual(principal.auth_method, "basic_fallback")

    def test_password_only_basic_fallback_preserves_owner_access(self) -> None:
        principal = authenticate_dashboard_request(
            basic_header("owner", "secret"),
            env={"DASHBOARD_AUTH_PASSWORD": "secret", "DASHBOARD_AUTH_USERNAME": "owner"},
        )
        disabled = authenticate_dashboard_request(
            basic_header("owner", "secret"),
            env={
                "DASHBOARD_AUTH_PASSWORD": "secret",
                "DASHBOARD_AUTH_USERNAME": "owner",
                "DASHBOARD_BASIC_FALLBACK_ENABLED": "false",
            },
        )

        self.assertTrue(dashboard_auth_configured({"DASHBOARD_AUTH_PASSWORD": "secret"}))
        # Access is what this test guards, and it is preserved: a principal, not
        # None, and disabling the fallback still yields None. The role is no
        # longer admin -- this env is precisely an unset DASHBOARD_BASIC_AUTH_ROLE,
        # which is the production configuration, and privilege there is now
        # something the deployment asks for.
        self.assertEqual(principal.role, "read_only")
        self.assertEqual(principal.auth_method, "basic_fallback")
        self.assertIsNone(disabled)

    def test_user_session_authentication_does_not_require_basic_password(self) -> None:
        store = LocalAuthStore(self.settings)
        store.create_user("researcher", "long-safe-password-123", role="researcher")
        principal = store.authenticate_password("researcher", "long-safe-password-123")
        token, _ = store.create_session(principal)
        resolved = authenticate_dashboard_request(
            None,
            f"hawknetic_research_session={token}",
            env={"DASHBOARD_USER_AUTH_ENABLED": "true"},
            auth_store=store,
        )
        self.assertEqual(resolved.username, "researcher")
        self.assertEqual(resolved.role, "researcher")

    def test_hosted_session_cookie_is_secure_and_http_only(self) -> None:
        cookie = build_session_cookie("opaque-token", secure=True)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=Strict", cookie)
        self.assertIn("Secure", cookie)

    def test_login_page_is_minimal_and_has_no_trading_controls(self) -> None:
        page = render_login_page()
        self.assertIn('autocomplete="current-password"', page)
        # The sign-in script is served as a file so the CSP can refuse inline
        # script, so the token handling lives in that asset, not the markup.
        self.assertIn('<script src="/assets/login.', page)
        self.assertIn("research_csrf_token", LOGIN_SCRIPT.body.decode("utf-8"))
        self.assertIn("Hawknetic<strong>Predictions</strong>", page)
        self.assertIn("Fresh source evidence", page)
        self.assertIn("Manual review only", page)
        self.assertNotIn("Place order", page)
        self.assertNotIn("API key", page)



class OperatorMessageCsrfTests(unittest.TestCase):
    """Queueing an operator message was forgeable from another site.

    ``valid_session_csrf`` returns True for a Basic-authenticated principal --
    there is no session to bind a token to. Browsers cache Basic credentials and
    attach them to cross-origin requests, so the session token alone protects
    nothing there. What actually protects ``/refresh`` is its custom
    ``X-Research-Action`` header: a browser cannot attach one cross-origin
    without a preflight, and this server sends no CORS headers, so the preflight
    fails.

    ``/internal/operator-messages`` had no such header requirement, and it
    accepted the three content types that skip the preflight entirely. A page on
    any other origin could queue instructions into the operator inbox, which is
    the documented channel a human reads and acts on.
    """

    SIMPLE_CONTENT_TYPES = (
        "text/plain",
        "application/x-www-form-urlencoded",
        "multipart/form-data",
    )

    def headers(self, **overrides: str) -> dict[str, str]:
        base = {
            "Content-Type": "application/json",
            "X-Research-Action": OPERATOR_ACTION_VALUE,
        }
        base.update(overrides)
        return base

    def test_the_ui_request_shape_is_accepted(self) -> None:
        headers = self.headers()
        self.assertTrue(valid_research_action(headers, OPERATOR_ACTION_VALUE))
        self.assertTrue(valid_json_content_type(headers))

    def test_a_missing_action_header_is_refused(self) -> None:
        headers = {"Content-Type": "application/json"}
        self.assertFalse(valid_research_action(headers, OPERATOR_ACTION_VALUE))

    def test_another_operation_s_action_value_is_refused(self) -> None:
        """The header must name *this* operation, not merely be present."""

        headers = self.headers(**{"X-Research-Action": REFRESH_ACTION_VALUE})
        self.assertFalse(valid_research_action(headers, OPERATOR_ACTION_VALUE))
        self.assertTrue(valid_research_action(headers, REFRESH_ACTION_VALUE))

    def test_every_preflight_free_content_type_is_refused(self) -> None:
        """These three are exactly what a cross-site form can send unpreflighted."""

        for content_type in self.SIMPLE_CONTENT_TYPES:
            self.assertFalse(
                valid_json_content_type({"Content-Type": content_type}), content_type
            )

    def test_a_charset_parameter_does_not_defeat_the_check(self) -> None:
        self.assertTrue(
            valid_json_content_type({"Content-Type": "application/json; charset=utf-8"})
        )
        self.assertTrue(valid_json_content_type({"Content-Type": "APPLICATION/JSON"}))

    def test_absent_headers_are_refused_rather_than_defaulted(self) -> None:
        self.assertFalse(valid_research_action(None, OPERATOR_ACTION_VALUE))
        self.assertFalse(valid_json_content_type(None))
        self.assertFalse(valid_json_content_type({}))


class PrivilegeIsOptInTests(unittest.TestCase):
    """Every path that mints a principal, and the role it hands out.

    These construct the environment explicitly and pass no auth store, so they
    touch no database and run everywhere -- which matters for a check on who
    gets operator access.
    """

    BASIC = {
        "DASHBOARD_AUTH_ENABLED": "true",
        "DASHBOARD_AUTH_USERNAME": "hawknetic",
        "DASHBOARD_AUTH_PASSWORD": "secret",
        "DASHBOARD_BASIC_FALLBACK_ENABLED": "true",
    }
    CREDENTIALS = basic_header("hawknetic", "secret")

    def role_for(self, env: dict[str, str], header: str | None = None) -> str | None:
        principal = authenticate_dashboard_request(header, None, env=env)
        return None if principal is None else principal.role

    def test_a_value_that_is_not_a_role_takes_the_floor(self) -> None:
        """A misspelling is a typo, not a request for privilege."""
        for label, value in (
            ("misspelled", "reader"),
            ("not a role", "superuser"),
            ("numeric", "1"),
        ):
            with self.subTest(value=label):
                env = {**self.BASIC, "DASHBOARD_BASIC_AUTH_ROLE": value}
                self.assertEqual(self.role_for(env, self.CREDENTIALS), "read_only")

    def test_the_shared_credential_does_not_outrank_real_accounts(self) -> None:
        """With user accounts configured, an unset role must not mean admin.

        Basic auth is a fallback beside per-user logins there, so its one
        credential is the shareable one. Defaulting it to admin handed operator
        access to whoever it was passed to, and outranked the read-only accounts
        someone had deliberately created.
        """
        for label, extra in (
            ("unset", {}),
            ("empty", {"DASHBOARD_BASIC_AUTH_ROLE": ""}),
            ("whitespace", {"DASHBOARD_BASIC_AUTH_ROLE": "   "}),
        ):
            with self.subTest(value=label):
                env = {**self.BASIC, "DASHBOARD_USER_AUTH_ENABLED": "true", **extra}
                self.assertEqual(self.role_for(env, self.CREDENTIALS), "read_only")

    def test_a_single_owner_instance_also_has_to_ask(self) -> None:
        """The default no longer turns on whether user accounts exist.

        Treating the password as the owner's identity is a fair argument that
        fails on the deployment it matters for: production has no user accounts
        and no `DASHBOARD_BASIC_AUTH_ROLE`, so this was the branch returning
        admin, and the split stayed inert exactly where it was introduced to
        apply. An owner gets their controls back by setting one variable;
        forgetting costs a button rather than handing a stranger the operator
        panel.
        """
        env = {**self.BASIC}
        self.assertFalse(user_auth_enabled(env))
        self.assertEqual(self.role_for(env, self.CREDENTIALS), "read_only")

    def test_the_owner_gets_operator_access_by_asking_for_it(self) -> None:
        env = {**self.BASIC, "DASHBOARD_BASIC_AUTH_ROLE": "admin"}
        self.assertEqual(self.role_for(env, self.CREDENTIALS), "admin")

    def test_a_named_role_is_honoured(self) -> None:
        for requested in ("read_only", "researcher", "admin"):
            with self.subTest(role=requested):
                env = {**self.BASIC, "DASHBOARD_BASIC_AUTH_ROLE": requested}
                self.assertEqual(self.role_for(env, self.CREDENTIALS), requested)
        # Case and padding are operator typos, not different roles.
        env = {**self.BASIC, "DASHBOARD_BASIC_AUTH_ROLE": "  ADMIN  "}
        self.assertEqual(self.role_for(env, self.CREDENTIALS), "admin")

    def test_bad_credentials_get_no_principal_at_all(self) -> None:
        self.assertIsNone(self.role_for(self.BASIC, basic_header("hawknetic", "wrong")))
        self.assertIsNone(self.role_for(self.BASIC, None))

    def test_an_unauthenticated_hosted_runtime_never_yields_an_operator(self) -> None:
        """The hole this closes: a public URL with no login and full admin.

        `DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED=false` turns authentication off
        entirely. On a laptop that is a convenience. On a hosted runtime it means
        anyone who finds the URL is unauthenticated, and the principal handed out
        used to be `admin` -- every operator route open to the public. Auth-off
        deployments stay reachable so a staging box still works; they just get
        the reader view.
        """
        for label, env in (
            ("railway", {"RAILWAY_ENVIRONMENT": "production"}),
            ("app_env staging", {"APP_ENV": "staging"}),
            ("app_env production", {"APP_ENV": "production"}),
        ):
            with self.subTest(runtime=label):
                off = {**env, "DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED": "false"}
                self.assertTrue(hosted_runtime(off), f"{label} should read as hosted")
                self.assertFalse(dashboard_auth_enabled(dict(off)), "this case is auth-disabled")
                self.assertEqual(self.role_for(off), "read_only")

    def test_a_hosted_runtime_still_demands_credentials_by_default(self) -> None:
        # The escape hatch above is opt-in; without it a hosted runtime forces
        # authentication and an anonymous request gets no principal.
        self.assertIsNone(self.role_for({"RAILWAY_ENVIRONMENT": "production"}))

    def test_an_unprotected_local_run_is_still_an_operator(self) -> None:
        # Deliberately unchanged: auth off on your own machine should give you
        # the full view, and nothing is exposed to anyone else.
        self.assertFalse(hosted_runtime({}))
        self.assertEqual(self.role_for({}), "admin")

    def test_the_role_helper_only_ever_returns_a_real_role(self) -> None:
        from kalshi_research_bot.auth import ROLES
        from kalshi_research_bot.paper_server import basic_auth_role

        for value in ("", "   ", "admin", "ADMIN", "reader", "root", "1", "None"):
            with self.subTest(value=value):
                self.assertIn(basic_auth_role({"DASHBOARD_BASIC_AUTH_ROLE": value}), ROLES)
        self.assertIn(basic_auth_role({}), ROLES)



class RoleGatedPanelRenderTests(unittest.TestCase):
    """What each role actually sees, rendered rather than reasoned about.

    `role_allows(viewer_role, "admin")` gates three things in `render_dashboard`:
    the refresh control, the exception-class diagnostics, and the operations
    panels. All three keyed off a role that used to default to admin, so the
    gate was inert wherever the default applied. Asserting the role alone would
    not have caught that -- these assert the pixels.
    """

    def render(self, role: str) -> str:
        from kalshi_research_bot.auth import AuthPrincipal
        from kalshi_research_bot.browser_fixtures import make_verified_fixture_payload
        from kalshi_research_bot.paper_server import render_dashboard

        return render_dashboard(
            make_verified_fixture_payload(),
            principal=AuthPrincipal(username="v", role=role, auth_method="basic_fallback"),
        )

    def test_only_admin_gets_the_refresh_control(self) -> None:
        self.assertIn('id="refresh-slip"', self.render("admin"))
        for role in ("read_only", "researcher"):
            with self.subTest(role=role):
                self.assertNotIn('id="refresh-slip"', self.render(role))

    def test_the_operations_panels_are_admin_only(self) -> None:
        # Asserted present for admin first, so this cannot pass by the marker
        # being absent from every render.
        self.assertIn("Track Record", self.render("admin"))
        for role in ("read_only", "researcher"):
            with self.subTest(role=role):
                self.assertNotIn("Track Record", self.render(role))

    def test_a_reader_still_gets_the_product(self) -> None:
        """The gate withholds operator panels, not the thing they came for."""

        self.assertIn("Estimate vs. price", self.render("read_only"))

    def test_the_production_configuration_renders_as_a_reader(self) -> None:
        """End to end: an unset role variable, through to what is on screen."""

        principal = authenticate_dashboard_request(
            basic_header("owner", "secret"),
            env={
                "DASHBOARD_AUTH_PASSWORD": "secret",
                "DASHBOARD_AUTH_USERNAME": "owner",
                "DASHBOARD_BASIC_FALLBACK_ENABLED": "true",
            },
        )
        self.assertEqual(principal.role, "read_only")
        rendered = self.render(principal.role)
        self.assertNotIn('id="refresh-slip"', rendered)
        self.assertNotIn("Track Record", rendered)


class BlankRoleVariableTests(unittest.TestCase):
    """A cleared environment variable arrives as "", not as absent.

    Railway hands through a variable set to empty string, and `or` treats it
    like absence -- which is right here, but only by accident unless it is
    pinned.
    """

    ENV = {
        "DASHBOARD_AUTH_PASSWORD": "secret",
        "DASHBOARD_AUTH_USERNAME": "owner",
        "DASHBOARD_BASIC_FALLBACK_ENABLED": "true",
    }

    def role_for(self, value: str) -> str:
        principal = authenticate_dashboard_request(
            basic_header("owner", "secret"),
            env={**self.ENV, "DASHBOARD_BASIC_AUTH_ROLE": value},
        )
        return principal.role

    def test_blank_and_whitespace_are_read_only(self) -> None:
        for blank in ("", " ", "\t", "\n"):
            with self.subTest(value=repr(blank)):
                self.assertEqual(self.role_for(blank), "read_only")

    def test_a_recognised_role_survives_surrounding_space(self) -> None:
        self.assertEqual(self.role_for("  ADMIN "), "admin")

    def test_a_near_miss_is_read_only(self) -> None:
        for typo in ("administrator", "adm1n", "root", "readonly", "read-only", "owner"):
            with self.subTest(value=typo):
                self.assertEqual(self.role_for(typo), "read_only")


# Keep this last. Anything defined below it is not yet bound when
# `unittest.main()` runs under direct execution, so those tests are
# silently skipped -- which is how this file lost seven of them once already.
if __name__ == "__main__":
    unittest.main()
