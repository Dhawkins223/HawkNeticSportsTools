from __future__ import annotations

import base64
import os
import unittest
from unittest.mock import patch

from kalshi_research_bot.auth import LocalAuthStore
from kalshi_research_bot.database import production_safety_status
from kalshi_research_bot.paper_server import (
    authenticate_dashboard_request,
    build_session_cookie,
    dashboard_auth_configured,
    render_login_page,
    dashboard_auth_enabled,
    dashboard_security_headers,
    hosted_runtime,
    valid_dashboard_auth,
    valid_refresh_action,
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
        self.assertEqual(principal.role, "admin")
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
        self.assertIn("research_csrf_token", page)
        self.assertNotIn("Place order", page)
        self.assertNotIn("API key", page)


if __name__ == "__main__":
    unittest.main()
