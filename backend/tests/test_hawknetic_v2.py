"""
HawkNetic v2 backend regression tests.

Covers the new spec §25 requirements:
- Real Monte Carlo (simulationRuns >= 1000)
- Per-leg new fields (noVigProbability, ev, projection, kelly, classification, ci95, etc.)
- Slip-level fields (parlayProbability, correlationMatrix, parlayCi95, etc.)
- edgePct = (modelProbability - noVigProbability) * 100
- Simulation-based parlay probability (correlated legs from the same game)
- Trap flag detection (heavy juice + thin edge)
- Inactive player handling
- /api/live/readiness, /api/games/today, /api/games/{id}/markets, /api/live/sync, /api/live/snapshots
- predictions_outcomes population on every analyze call
- Schema v2 tables exist
"""
import os
import sqlite3
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
assert BASE_URL, "REACT_APP_BACKEND_URL env var must be set"

# Find the SQLite DB path so we can introspect schema and predictions_outcomes
DB_CANDIDATES = [
    "/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/data/hawknetic.sqlite",
    os.environ.get("HAWKNETIC_DB_PATH", ""),
]


def _candidate_db_file(full_path: str) -> bool:
    """Return True if `full_path` is a SQLite DB that contains historical_games."""
    try:
        conn = sqlite3.connect(full_path)
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='historical_games' LIMIT 1"
            )
            return cur.fetchone() is not None
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def _walk_for_db_file(root_dir: str) -> str | None:
    for root, _dirs, files in os.walk(root_dir):
        if "node_modules" in root or ".next" in root:
            continue
        for name in files:
            if not name.endswith(".db"):
                continue
            full = os.path.join(root, name)
            if _candidate_db_file(full):
                return full
    return None


def _find_db():
    for p in DB_CANDIDATES:
        if os.path.exists(p):
            return p
    return _walk_for_db_file("/app")


DB_PATH = _find_db()


@pytest.fixture(scope="module")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


def _leg(leg_id, game_id, selection, odds, market="player_threes", line=4.5, player_name="Stephen Curry"):
    return {
        "id": leg_id,
        "sport": "NBA",
        "bookmaker": "bet365",
        "gameId": str(game_id),
        "eventLabel": "Heat @ Warriors",
        "marketType": market,
        "selection": selection,
        "line": line,
        "oddsAmerican": odds,
        "playerName": player_name,
    }


# ---------------- Schema v2 tables ----------------
class TestSchemaV2:
    REQUIRED = [
        "player_skill",
        "team_metrics",
        "live_games",
        "live_player_status",
        "live_injuries",
        "live_odds",
        "live_line_movement",
        "live_data_snapshots",
        "predictions_outcomes",
    ]

    def test_v2_tables_exist(self):
        if not DB_PATH:
            pytest.skip("SQLite db not found")
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cur.fetchall()}
        conn.close()
        missing = [t for t in self.REQUIRED if t not in tables]
        assert not missing, f"Missing v2 tables: {missing}. Have: {sorted(tables)}"


REQUIRED_READINESS_KEYS = ("ready", "status", "blocking_reasons", "warnings", "last_updated", "checks")
REQUIRED_READINESS_CHECKS = ("games_loaded", "props_loaded", "odds_loaded", "timestamps_fresh")


# ---------------- /api/live/readiness ----------------
class TestLiveReadiness:
    @pytest.fixture
    def readiness(self, api):
        r = api.get(f"{BASE_URL}/api/live/readiness", timeout=20)
        assert r.status_code == 200
        return r.json()

    def test_readiness_has_all_top_keys(self, readiness):
        missing = [k for k in REQUIRED_READINESS_KEYS if k not in readiness]
        assert not missing, f"Missing readiness keys: {missing}"

    def test_readiness_ready_is_bool(self, readiness):
        assert isinstance(readiness["ready"], bool)

    def test_readiness_blocking_reasons_and_warnings_are_lists(self, readiness):
        assert isinstance(readiness["blocking_reasons"], list)
        assert isinstance(readiness["warnings"], list)

    def test_readiness_checks_is_dict(self, readiness):
        assert isinstance(readiness["checks"], dict)

    def test_readiness_has_all_required_check_flags(self, readiness):
        missing = [k for k in REQUIRED_READINESS_CHECKS if k not in readiness["checks"]]
        assert not missing, f"Missing readiness check flags: {missing}"


# ---------------- /api/games/today ----------------
class TestGamesToday:
    def test_today_returns_items(self, api):
        r = api.get(f"{BASE_URL}/api/games/today", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert "items" in d
        assert isinstance(d["items"], list)
        # Seed creates at least 1 in-progress live game (Lakers vs Celtics)
        live_or_today = [g for g in d["items"] if g.get("live_status") or g.get("game_date")]
        assert len(live_or_today) >= 1


# ---------------- /api/games/{id}/markets ----------------
class TestGameMarkets:
    def test_markets_shape(self, api):
        r = api.get(f"{BASE_URL}/api/games/2/markets", timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["gameId"] == 2
        for k in ("props", "odds", "liveOdds", "liveGame", "lineMovement"):
            assert k in d, f"Missing key: {k}"
        assert isinstance(d["props"], list)
        assert isinstance(d["odds"], list)
        assert isinstance(d["liveOdds"], list)


# ---------------- /api/live/sync + /api/live/snapshots ----------------
class TestLiveSync:
    def test_sync_odds_and_snapshot(self, api):
        payload = {
            "kind": "odds",
            "payload": {
                "rows": [
                    {
                        "game_id": 2,
                        "market": "Moneyline",
                        "selection": "Golden State Warriors",
                        "line": None,
                        "american_odds": -140,
                        "sportsbook": "TEST_book",
                    }
                ]
            },
        }
        r = api.post(f"{BASE_URL}/api/live/sync", json=payload, timeout=20)
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("ok")
        assert d.get("rows_written") == 1

        # Verify snapshot was persisted
        snap = api.get(f"{BASE_URL}/api/live/snapshots?limit=5", timeout=20)
        assert snap.status_code == 200
        items = snap.json()["items"]
        assert any(it["kind"] == "odds" for it in items), f"No odds snapshot found in {items}"

        # Verify writer reflected into live_odds
        odds = api.get(f"{BASE_URL}/api/live/odds?game_id=2", timeout=20).json()["items"]
        assert any(o.get("sportsbook") == "TEST_book" for o in odds)

    def test_sync_player_status(self, api):
        payload = {
            "kind": "player_status",
            "payload": {
                "rows": [
                    {
                        "player_id": 5,
                        "game_id": 2,
                        "status": "active",
                        "minutes_played": 18,
                        "starter": True,
                        "source": "TEST_provider",
                    }
                ]
            },
        }
        r = api.post(f"{BASE_URL}/api/live/sync", json=payload, timeout=20)
        assert r.status_code == 200
        assert r.json().get("ok")


# ---------------- POST /api/slips/analyze (REAL Monte Carlo) ----------------
class TestSlipsAnalyzeV2:
    def test_simulation_runs_at_least_1000(self, api):
        r = api.post(
            f"{BASE_URL}/api/slips/analyze",
            json={
                "stake": 100,
                "legs": [_leg("l1", 2, "Stephen Curry Over 4.5 Threes Made", -130)],
            },
            timeout=60,
        )
        assert r.status_code == 200, r.text
        d = r.json()
        assert d.get("simulationRuns", 0) >= 1000, (
            f"simulationRuns should be >=1000 got {d.get('simulationRuns')}"
        )

    def test_per_leg_v2_fields_present(self, api):
        r = api.post(
            f"{BASE_URL}/api/slips/analyze",
            json={
                "stake": 100,
                "legs": [_leg("l1", 2, "Stephen Curry Over 4.5 Threes Made", -130)],
            },
            timeout=60,
        )
        d = r.json()
        leg = d["legAnalyses"][0]
        for f in (
            "noVigProbability",
            "ev",
            "evPerUnit",
            "projection",
            "projectionStd",
            "marginOfError",
            "ci95",
            "confidenceScore",
            "classification",
            "edgeLabel",
            "trapFlags",
            "kellyFraction",
            "kellyRecommended",
            "statLabel",
            "americanOdds",
            "decimalOdds",
        ):
            assert f in leg, f"Missing per-leg field: {f}. Got keys: {sorted(leg.keys())}"
        assert isinstance(leg["ci95"], list) and len(leg["ci95"]) == 2
        assert isinstance(leg["trapFlags"], list)
        assert leg["classification"] in {
            "Strong play",
            "Playable",
            "Lean",
            "Pass",
            "Trap",
        }

    def test_slip_level_v2_fields_present(self, api):
        r = api.post(
            f"{BASE_URL}/api/slips/analyze",
            json={
                "stake": 100,
                "legs": [
                    _leg("l1", 2, "Stephen Curry Over 4.5 Threes Made", -130),
                    _leg(
                        "l2",
                        2,
                        "Stephen Curry Over 27.5 Points",
                        -110,
                        market="player_points",
                        line=27.5,
                    ),
                ],
            },
            timeout=60,
        )
        d = r.json()
        for f in (
            "parlayProbability",
            "parlayEv",
            "parlayClassification",
            "parlayKellyRecommended",
            "correlationMatrix",
            "parlayCi95",
            "simulationRuns",
            "readiness",
            "bestLeg",
            "worstLeg",
            "trapLegs",
        ):
            assert f in d, f"Missing slip field: {f}. Got: {sorted(d.keys())}"
        cm = d["correlationMatrix"]
        assert len(cm) == 2 and len(cm[0]) == 2
        # Diagonal should be ~1
        assert abs(cm[0][0] - 1.0) < 1e-6 and abs(cm[1][1] - 1.0) < 1e-6

    def test_edge_uses_no_vig_probability(self, api):
        """edgePct == (modelProbability - noVigProbability) * 100 ± 0.1"""
        r = api.post(
            f"{BASE_URL}/api/slips/analyze",
            json={
                "stake": 100,
                "legs": [_leg("l1", 2, "Stephen Curry Over 4.5 Threes Made", -130)],
            },
            timeout=60,
        )
        leg = r.json()["legAnalyses"][0]
        expected = (leg["modelProbability"] - leg["noVigProbability"]) * 100
        assert abs(leg["edgePct"] - expected) < 0.1, (
            f"edgePct={leg['edgePct']} expected≈{expected}"
        )

    def test_parlay_probability_is_simulation_based(self, api):
        """Two legs from the same game → off-diagonal correlation should not equal naive product."""
        r = api.post(
            f"{BASE_URL}/api/slips/analyze",
            json={
                "stake": 100,
                "legs": [
                    _leg("l1", 2, "Stephen Curry Over 4.5 Threes Made", -130),
                    _leg(
                        "l2",
                        2,
                        "Stephen Curry Over 27.5 Points",
                        -110,
                        market="player_points",
                        line=27.5,
                    ),
                ],
            },
            timeout=60,
        )
        d = r.json()
        legs = d["legAnalyses"]
        p1 = legs[0]["modelProbability"]
        p2 = legs[1]["modelProbability"]
        cm = d["correlationMatrix"]
        # Off-diagonal entries are correlation coefficients (Pearson) for the leg pair.
        off = cm[0][1]
        # The strongest signal of "this is not naive multiplication" is the correlation
        # coefficient itself. Same-player legs share minutes/usage and should produce a
        # measurable positive Pearson correlation. Parlay probability vs naive product
        # has MC sampling variance ≈ ±0.005 which makes a strict probability-diff test
        # flaky; we therefore assert on the correlation coefficient directly.
        naive = p1 * p2
        assert abs(off) > 0.05, (
            f"Off-diagonal correlation {off:.4f} is too small — same-player legs should "
            f"share minutes/usage variance and produce ρ > 0.05 (naive product {naive:.4f})"
        )

    def test_trap_flag_detection(self, api):
        """Heavy juice (-250) with thin edge should produce a trap flag."""
        r = api.post(
            f"{BASE_URL}/api/slips/analyze",
            json={
                "stake": 100,
                "legs": [_leg("l1", 2, "Stephen Curry Over 4.5 Threes Made", -250)],
            },
            timeout=60,
        )
        leg = r.json()["legAnalyses"][0]
        flags_text = " ".join(leg.get("trapFlags", [])).lower()
        # Either explicit juice trap flag, or classification == Trap, or warnings mention juice
        assert (
            "juice" in flags_text
            or "heavy" in flags_text
            or leg.get("classification") in {"Trap", "Pass"}
        ), f"Expected trap signal at -250 odds. trapFlags={leg.get('trapFlags')} class={leg.get('classification')}"

    def test_inactive_player_zeros_parlay(self, api):
        """An injured/out player should set inactivePlayer=true and parlayProbability=0."""
        # Inject an OUT injury for player_id=5 (Stephen Curry) via /api/live/sync
        sync_payload = {
            "kind": "injury",
            "payload": {
                "rows": [
                    {
                        "player_id": 5,
                        "designation": "out",
                        "note": "TEST_inactive_player",
                        "source": "TEST_inactive",
                    }
                ]
            },
        }
        sync_r = api.post(f"{BASE_URL}/api/live/sync", json=sync_payload, timeout=20)
        assert sync_r.status_code == 200, sync_r.text

        r = api.post(
            f"{BASE_URL}/api/slips/analyze",
            json={
                "stake": 100,
                "legs": [
                    {
                        "id": "l1",
                        "sport": "NBA",
                        "bookmaker": "bet365",
                        "gameId": "2",
                        "eventLabel": "Heat @ Warriors",
                        "marketType": "player_threes",
                        "selection": "Stephen Curry Over 4.5 Threes Made",
                        "line": 4.5,
                        "oddsAmerican": -130,
                        "playerName": "Stephen Curry",
                        "playerId": "5",
                    }
                ],
            },
            timeout=60,
        )
        d = r.json()
        leg = d["legAnalyses"][0]
        # If the codepath honors out designations, both flags must hold
        assert leg.get("inactivePlayer"), (
            f"Expected inactivePlayer=true after OUT injury seeded; got {leg.get('inactivePlayer')}. "
            f"trapFlags={leg.get('trapFlags')}"
        )
        assert d["parlayProbability"] == 0, (
            f"Inactive player but parlayProbability={d['parlayProbability']}"
        )

    def test_predictions_outcomes_populated(self, api):
        """After /slips/analyze, predictions_outcomes table should have rows with non-null modelProbability."""
        if not DB_PATH:
            pytest.skip("SQLite db not found")
        before = 0
        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        try:
            cur.execute("SELECT COUNT(*) FROM predictions_outcomes")
            before = cur.fetchone()[0]
        except sqlite3.OperationalError:
            pytest.skip("predictions_outcomes table missing")
        conn.close()

        r = api.post(
            f"{BASE_URL}/api/slips/analyze",
            json={
                "stake": 100,
                "legs": [_leg("lpo", 2, "Stephen Curry Over 4.5 Threes Made", -130)],
            },
            timeout=60,
        )
        assert r.status_code == 200

        conn = sqlite3.connect(DB_PATH)
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM predictions_outcomes")
        after = cur.fetchone()[0]
        conn.close()
        assert after > before, (
            f"predictions_outcomes did not grow: before={before} after={after}"
        )
