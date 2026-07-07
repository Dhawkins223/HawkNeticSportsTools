from __future__ import annotations

import base64

from kalshi_research_bot.paper_server import dashboard_auth_enabled, valid_dashboard_auth


def basic_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def test_dashboard_auth_disabled_without_password() -> None:
    env = {}

    assert dashboard_auth_enabled(env) is False
    assert valid_dashboard_auth(None, env) is True


def test_dashboard_auth_enabled_by_password() -> None:
    env = {"DASHBOARD_AUTH_PASSWORD": "secret"}

    assert dashboard_auth_enabled(env) is True
    assert valid_dashboard_auth(basic_header("hawknetic", "secret"), env) is True


def test_dashboard_auth_rejects_wrong_password() -> None:
    env = {"DASHBOARD_AUTH_USERNAME": "owner", "DASHBOARD_AUTH_PASSWORD": "secret"}

    assert valid_dashboard_auth(basic_header("owner", "wrong"), env) is False
    assert valid_dashboard_auth(basic_header("hawknetic", "secret"), env) is False


def test_dashboard_auth_enabled_without_password_rejects_all() -> None:
    env = {"DASHBOARD_AUTH_ENABLED": "true"}

    assert dashboard_auth_enabled(env) is True
    assert valid_dashboard_auth(basic_header("hawknetic", "secret"), env) is False
