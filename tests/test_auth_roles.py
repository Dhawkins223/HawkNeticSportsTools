from __future__ import annotations

from kalshi_research_bot.auth import LocalAuthStore, role_allows, session_token_from_cookie

from tests.postgres_support import PostgresTestCase


class AuthRoleTests(PostgresTestCase):
    def test_password_hash_and_role_hierarchy(self) -> None:
        store = LocalAuthStore(self.settings)
        created = store.create_user("Researcher.One", "long-safe-password-123", role="researcher")
        principal = store.authenticate_password("researcher.one", "long-safe-password-123")

        self.assertEqual(created["username"], "researcher.one")
        self.assertEqual(principal.role, "researcher")
        self.assertIsNone(store.authenticate_password("researcher.one", "incorrect-password"))
        self.assertTrue(role_allows("admin", "researcher"))
        self.assertFalse(role_allows("researcher", "admin"))

    def test_session_csrf_revocation_and_account_disable(self) -> None:
        store = LocalAuthStore(self.settings)
        store.create_user("owner", "long-safe-password-123", role="admin")
        principal = store.authenticate_password("owner", "long-safe-password-123")
        self.assertIsNotNone(principal)
        token, session = store.create_session(principal, duration_minutes=10)

        self.assertEqual(store.resolve_session(token).username, "owner")
        self.assertTrue(store.validate_csrf(token, session.csrf_token))
        self.assertFalse(store.validate_csrf(token, "incorrect"))
        self.assertTrue(store.set_disabled("owner", disabled=True))
        self.assertIsNone(store.resolve_session(token))
        self.assertIsNone(store.authenticate_password("owner", "long-safe-password-123"))

    def test_failed_login_audit_and_lock_are_retained(self) -> None:
        store = LocalAuthStore(self.settings)
        store.create_user("locked", "long-safe-password-123", role="read_only")
        self.assertIsNone(store.authenticate_password("locked", "incorrect-password", maximum_failures=2))
        self.assertIsNone(store.authenticate_password("locked", "incorrect-password", maximum_failures=2))
        self.assertIsNone(store.authenticate_password("locked", "long-safe-password-123"))

        user = self.query_one("SELECT failed_login_count, locked_until FROM auth.app_users WHERE username = %s", ("locked",))
        audit_count = self.query_one("SELECT COUNT(*) AS total FROM auth.login_audit WHERE username = %s", ("locked",))
        self.assertEqual(user["failed_login_count"], 2)
        self.assertIsNotNone(user["locked_until"])
        self.assertEqual(audit_count["total"], 3)

    def test_cookie_parser_uses_only_named_session(self) -> None:
        self.assertEqual(
            session_token_from_cookie("other=one; hawknetic_research_session=token-value"),
            "token-value",
        )
        self.assertIsNone(session_token_from_cookie(None))

    def test_password_material_is_hashed_and_plaintext_is_absent(self) -> None:
        store = LocalAuthStore(self.settings)
        password = "long-safe-password-123"
        store.create_user("hash-check", password, role="researcher")
        row = self.query_one(
            "SELECT password_hash, password_salt, password_algorithm FROM auth.app_users WHERE username = %s",
            ("hash-check",),
        )
        self.assertNotEqual(row["password_hash"], password)
        self.assertNotEqual(row["password_salt"], password)
        self.assertEqual(row["password_algorithm"], "scrypt")

    def test_expired_session_cannot_be_resolved(self) -> None:
        store = LocalAuthStore(self.settings)
        store.create_user("expiry", "long-safe-password-123", role="researcher")
        principal = store.authenticate_password("expiry", "long-safe-password-123")
        token, _ = store.create_session(principal, duration_minutes=5)
        with store.connection() as connection:
            connection.execute(
                "UPDATE auth.app_sessions SET expires_at = %s WHERE session_id_hash IS NOT NULL",
                ("2020-01-01T00:00:00+00:00",),
            )
        self.assertIsNone(store.resolve_session(token))

    def test_read_only_role_cannot_meet_researcher_or_admin_requirement(self) -> None:
        self.assertTrue(role_allows("admin", "admin"))
        self.assertTrue(role_allows("admin", "researcher"))
        self.assertFalse(role_allows("read_only", "researcher"))
        self.assertFalse(role_allows("read_only", "admin"))
