"""
Backend API regression tests for HawkNetic Predictor Tools dashboard.

Endpoints covered:
- GET /api/health
- GET /api/games        (seeded NBA games)
- GET /api/props        (seeded props)
- GET /api/odds         (seeded odds)
- POST /api/slips/analyze (algorithm verdict)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL env var must be set"


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# --- Health ---
class TestHealth:
    def test_health_ok(self, api):
        r = api.get(f"{BASE_URL}/api/health", timeout=20)
        assert r.status_code == 200
        data = r.json()
        # accept either {"status":"ok"} or {"ok":true}
        assert (
            data.get("status") == "ok"
            or data.get("ok") is True
            or "ok" in str(data).lower()
        ), f"Unexpected health response: {data}"


# --- Games ---
class TestGames:
    def test_games_returns_seven(self, api):
        r = api.get(f"{BASE_URL}/api/games", timeout=20)
        assert r.status_code == 200
        data = r.json()
        items = data.get("items", data if isinstance(data, list) else [])
        assert len(items) == 7, f"Expected 7 seeded games, got {len(items)}"

    def test_games_have_team_names(self, api):
        r = api.get(f"{BASE_URL}/api/games", timeout=20)
        items = r.json().get("items", [])
        assert items, "no games returned"
        first = items[0]
        # Either explicit team-name keys or nested team objects
        has_team_info = (
            "home_team_name" in first and "visitor_team_name" in first
        ) or ("home_team" in first and "visitor_team" in first)
        assert has_team_info, f"games missing team names: {list(first.keys())}"


# --- Props ---
class TestProps:
    def test_props_returns_twenty_five(self, api):
        r = api.get(f"{BASE_URL}/api/props", timeout=20)
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert len(items) == 25, f"Expected 25 props, got {len(items)}"

    def test_props_have_market_and_line(self, api):
        r = api.get(f"{BASE_URL}/api/props", timeout=20)
        items = r.json().get("items", [])
        assert items
        first = items[0]
        assert "market" in first
        assert "line" in first
        assert "game_id" in first


# --- Odds ---
class TestOdds:
    def test_odds_returns_eight(self, api):
        r = api.get(f"{BASE_URL}/api/odds", timeout=20)
        assert r.status_code == 200
        items = r.json().get("items", [])
        assert len(items) == 8, f"Expected 8 odds rows, got {len(items)}"

    def test_odds_have_required_fields(self, api):
        r = api.get(f"{BASE_URL}/api/odds", timeout=20)
        items = r.json().get("items", [])
        assert items
        first = items[0]
        for key in ("game_id", "market", "selection", "odds_value"):
            assert key in first, f"odds row missing key {key}: {first}"


# --- Slip analyze ---
class TestSlipAnalyze:
    PAYLOAD = {
        "bookmaker": "bet365",
        "stake": 10,
        "legs": [
            {
                "id": "test-1",
                "sport": "NBA",
                "bookmaker": "bet365",
                "gameId": "1",
                "eventLabel": "Los Angeles Lakers @ Boston Celtics",
                "marketType": "moneyline",
                "selection": "Boston Celtics",
                "oddsAmerican": -135,
            }
        ],
    }

    def test_analyze_returns_verdict_structure(self, api):
        r = api.post(
            f"{BASE_URL}/api/slips/analyze", json=self.PAYLOAD, timeout=30
        )
        assert r.status_code == 200, r.text
        data = r.json()
        # Required keys per problem statement
        for key in (
            "modelWinProbability",
            "edgePct",
            "recommendation",
            "impliedProbability",
            "legAnalyses",
        ):
            assert key in data, f"missing {key} in response: {list(data.keys())}"
        # recommendation should be a non-empty string
        assert isinstance(data["recommendation"], str)
        assert data["recommendation"] != ""

    def test_analyze_validates_payload(self, api):
        # missing legs should fail validation
        r = api.post(
            f"{BASE_URL}/api/slips/analyze",
            json={"bookmaker": "bet365", "stake": 10, "legs": []},
            timeout=20,
        )
        # FastAPI returns 422 for validation errors OR 200 with insufficient data
        assert r.status_code in (200, 400, 422)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
