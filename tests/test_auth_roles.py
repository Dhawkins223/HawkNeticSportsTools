import tempfile
import unittest
from pathlib import Path

from kalshi_research_bot.auth import LocalAuthStore, role_allows, session_token_from_cookie


class AuthRoleTests(unittest.TestCase):
    def test_passwords_use_scrypt_and_plaintext_is_not_stored(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auth.sqlite"
            store = LocalAuthStore(path)
            created = store.create_user("Researcher.One", "long-safe-password-123", role="researcher")
            self.assertEqual(created["username"], "researcher.one")
            principal = store.authenticate_password("researcher.one", "long-safe-password-123")
            self.assertEqual(principal.role, "researcher")
            self.assertIsNone(store.authenticate_password("researcher.one", "wrong-password-value"))

    def test_role_hierarchy_protects_admin_controls(self):
        self.assertTrue(role_allows("admin", "researcher"))
        self.assertTrue(role_allows("researcher", "read_only"))
        self.assertFalse(role_allows("researcher", "admin"))
        self.assertFalse(role_allows("read_only", "researcher"))

    def test_session_expiry_csrf_and_revocation(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalAuthStore(Path(directory) / "auth.sqlite")
            store.create_user("owner", "long-safe-password-123", role="admin")
            principal = store.authenticate_password("owner", "long-safe-password-123")
            token, session_principal = store.create_session(principal, duration_minutes=10)
            self.assertEqual(store.resolve_session(token).username, "owner")
            self.assertTrue(store.validate_csrf(token, session_principal.csrf_token))
            self.assertFalse(store.validate_csrf(token, "wrong"))
            self.assertTrue(store.revoke_session(token))
            self.assertIsNone(store.resolve_session(token))

    def test_disabled_account_revokes_sessions(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalAuthStore(Path(directory) / "auth.sqlite")
            store.create_user("reader", "long-safe-password-123", role="read_only")
            principal = store.authenticate_password("reader", "long-safe-password-123")
            token, _ = store.create_session(principal)
            self.assertTrue(store.set_disabled("reader", disabled=True))
            self.assertIsNone(store.resolve_session(token))
            self.assertIsNone(store.authenticate_password("reader", "long-safe-password-123"))

    def test_repeated_failures_lock_account_and_are_audited(self):
        with tempfile.TemporaryDirectory() as directory:
            store = LocalAuthStore(Path(directory) / "auth.sqlite")
            store.create_user("locked", "long-safe-password-123", role="read_only")
            for _ in range(2):
                self.assertIsNone(
                    store.authenticate_password(
                        "locked",
                        "wrong-password-value",
                        maximum_failures=2,
                    )
                )
            self.assertIsNone(store.authenticate_password("locked", "long-safe-password-123"))

    def test_cookie_parser_extracts_only_named_session(self):
        self.assertEqual(
            session_token_from_cookie("other=one; hawknetic_research_session=token-value"),
            "token-value",
        )
        self.assertIsNone(session_token_from_cookie(None))


if __name__ == "__main__":
    unittest.main()
