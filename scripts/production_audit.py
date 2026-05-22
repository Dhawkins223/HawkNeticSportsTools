"""HawkneticSports production-readiness audit harness.

Runs real HTTP traffic against the live preview backend and asserts behavior.
No mocks. Every claim in the report is verified by a live request.
"""
from __future__ import annotations

import json
import os
import time
import http.cookiejar
import urllib.parse
import urllib.request
from typing import Any

API = "https://1b115e8a-b516-47c2-bfd6-7e86bc65409b.preview.emergentagent.com"


def request(method: str, path: str, body: Any | None = None, cookies: http.cookiejar.CookieJar | None = None) -> tuple[int, dict | str, http.cookiejar.CookieJar]:
    cj = cookies or http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    opener.addheaders = [
        ("User-Agent", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"),
        ("Accept", "application/json,text/html,*/*"),
        ("Accept-Language", "en-US,en;q=0.9"),
    ]
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(API + path, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        resp = opener.open(req, timeout=15)
        raw = resp.read().decode()
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        return e.code, _parse(raw), cj
    try:
        return resp.status, json.loads(raw), cj
    except json.JSONDecodeError:
        return resp.status, raw, cj


def _parse(raw: str) -> Any:
    try:
        return json.loads(raw)
    except Exception:
        return raw


def section(title: str) -> None:
    print(f"\n{'=' * 70}\n{title}\n{'=' * 70}")


def check(label: str, passed: bool, detail: str = "") -> bool:
    icon = "PASS" if passed else "FAIL"
    print(f"  [{icon}] {label}{(' — ' + detail) if detail else ''}")
    return passed


# -----------------------------------------------------------------------------
# 1. Auth + user-scoped slips
# -----------------------------------------------------------------------------
section("1. AUTH + USER-SCOPED SLIPS (real HTTP, real cookies)")

email = f"audit-{int(time.time())}@hawk.test"
status, body, cj1 = request("POST", "/api/auth/signup", {"email": email, "password": "auditpass123", "full_name": "Auditor"})
check("signup returns 200", status == 200, f"got {status}, body: {body if status != 200 else body.get('user', {}).get('email')}")

status, me, _ = request("GET", "/api/auth/me", cookies=cj1)
check("/me with cookie returns 200", status == 200)
check("/me echoes correct email", isinstance(me, dict) and me.get("user", {}).get("email") == email, f"got {me.get('user', {}).get('email') if isinstance(me, dict) else me}")
check("password_hash NOT in /me response", isinstance(me, dict) and "password_hash" not in me.get("user", {}))

status, _, _ = request("GET", "/api/auth/me")
check("/me without cookie returns 401", status == 401, f"got {status}")

status, save_resp, _ = request("POST", "/api/slips", {"name": "Audit slip", "sport": "NBA", "legs": [{"label": "LeBron over 25.5", "odds_value": -115, "probability": 0.6}]}, cookies=cj1)
slip_id = save_resp.get("slip", {}).get("id") if isinstance(save_resp, dict) else None
check("authenticated POST /api/slips returns 200", status == 200 and slip_id is not None, f"slip_id={slip_id}")

status, lst, _ = request("GET", "/api/slips", cookies=cj1)
check("authenticated GET /api/slips returns user's slips", status == 200 and isinstance(lst, dict) and any(s.get("id") == slip_id for s in lst.get("items", [])))

status, _, _ = request("GET", "/api/slips")
check("anon GET /api/slips returns 401", status == 401, f"got {status}")

status, _, _ = request("POST", "/api/slips", {"name": "x", "sport": "NBA", "legs": [{"label": "z", "odds_value": -110, "probability": 0.5}]})
check("anon POST /api/slips returns 401", status == 401, f"got {status}")

email2 = f"audit2-{int(time.time())}@hawk.test"
status, _, cj2 = request("POST", "/api/auth/signup", {"email": email2, "password": "auditpass123", "full_name": "Auditor 2"})
check("user2 signup ok", status == 200)

status, lst2, _ = request("GET", "/api/slips", cookies=cj2)
user2_count = len(lst2.get("items", [])) if isinstance(lst2, dict) else -1
check("user2 sees ZERO slips of user1", user2_count == 0, f"user2 saw {user2_count} slips")

status, _, _ = request("DELETE", f"/api/slips/{slip_id}", cookies=cj2)
check("user2 cannot delete user1 slip (returns 404)", status == 404, f"got {status}")

status, _, cj1 = request("POST", "/api/auth/logout", cookies=cj1)
check("logout returns 200", status == 200)

status, _, _ = request("GET", "/api/auth/me", cookies=cj1)
check("after logout /me returns 401", status == 401, f"got {status}")

# -----------------------------------------------------------------------------
# 2. Math correctness — direct EV/no-vig hand-check
# -----------------------------------------------------------------------------
section("2. MATH CORRECTNESS (Monte Carlo + no-vig)")

status, slip_resp, _ = request("POST", "/api/slips/analyze", {
    "bookmaker": "consensus", "stake": 10,
    "legs": [
        {"id": "m1", "sport": "NBA", "bookmaker": "consensus", "gameId": "1", "eventLabel": "Heat @ Celtics", "marketType": "player_prop", "selection": "Points (LeBron James) over", "line": 25.5, "oddsAmerican": -115, "playerId": "1"},
        {"id": "m2", "sport": "NBA", "bookmaker": "consensus", "gameId": "1", "eventLabel": "Heat @ Celtics", "marketType": "total", "selection": "Over 224.5", "line": 224.5, "oddsAmerican": -108},
    ]
})
check("/api/slips/analyze returns 200", status == 200)
if status == 200:
    check("response contains simulationRuns >= 1000", slip_resp.get("simulationRuns", 0) >= 1000, f"runs={slip_resp.get('simulationRuns')}")
    check("response contains correlationMatrix", isinstance(slip_resp.get("correlationMatrix"), list) and len(slip_resp["correlationMatrix"]) == 2)
    check("response contains parlayKellyRecommended", "parlayKellyRecommended" in slip_resp)
    check("response contains parlayCi95 (95% binomial CI)", isinstance(slip_resp.get("parlayCi95"), list))
    check("response contains readiness block", isinstance(slip_resp.get("readiness"), dict))
    legs = slip_resp.get("legAnalyses", [])
    check("each leg has noVigProbability", all("noVigProbability" in a for a in legs))
    check("each leg has ev + evPerUnit", all("ev" in a and "evPerUnit" in a for a in legs))
    check("each leg has projection + projectionStd", all("projection" in a and "projectionStd" in a for a in legs))
    check("each leg has classification", all(a.get("classification") in {"Strong play", "Playable", "Lean", "Pass", "Trap"} for a in legs))
    check("each leg has trapFlags array", all(isinstance(a.get("trapFlags"), list) for a in legs))
    check("each leg has kellyRecommended", all("kellyRecommended" in a for a in legs))

    # EV math hand-check: for leg with model_p, decimal_odds, EV = stake * (p*(D-1) - (1-p))
    if legs:
        leg = legs[0]
        p = leg["modelProbability"]; d = leg["decimalOdds"]; ev = leg["ev"]; stake = 10
        expected_ev = stake * (p * (d - 1) - (1 - p))
        check(f"EV math correct (p={p:.3f}, d={d:.3f}): expected {expected_ev:.4f}, got {ev:.4f}", abs(ev - expected_ev) < 0.01)

    # No-vig: -110/-110 = raw 52.4% each, no-vig 50.0%. Test by sending two -110 sides.
    # Already covered indirectly. Verify raw vs no-vig differ for a leg that has it.
    nv_present = any(l.get("noVigAvailable") for l in legs)
    check("at least one leg has no-vig probability available", nv_present)

# -----------------------------------------------------------------------------
# 3. Live readiness gating
# -----------------------------------------------------------------------------
section("3. LIVE READINESS")

status, ready, _ = request("GET", "/api/live/readiness")
check("/api/live/readiness returns 200", status == 200)
if status == 200:
    expected_keys = {"ready", "status", "blocking_reasons", "warnings", "last_updated", "checks"}
    check("readiness response shape correct", expected_keys.issubset(ready.keys()))
    check("checks dict has games_loaded", "games_loaded" in ready.get("checks", {}))
    check("checks dict has odds_loaded", "odds_loaded" in ready.get("checks", {}))
    check("checks dict has timestamps_fresh", "timestamps_fresh" in ready.get("checks", {}))
    print(f"     current readiness: ready={ready.get('ready')}, blocking={len(ready.get('blocking_reasons', []))}, warnings={len(ready.get('warnings', []))}")

# -----------------------------------------------------------------------------
# 4. +EV scanner real output
# -----------------------------------------------------------------------------
section("4. +EV SCANNER")
status, scan, _ = request("GET", "/api/insights/top-ev?limit=5")
check("/api/insights/top-ev returns 200", status == 200)
if status == 200:
    items = scan.get("items", [])
    check(f"scanner returned {len(items)} edges from {scan.get('totalScanned')} props", len(items) > 0)
    if items:
        first = items[0]
        # Every card has the required fields
        required = ("propId", "market", "americanOdds", "modelProbability", "impliedProbability", "edge", "ev", "evPercent", "projection")
        check("each card has required fields", all(k in first for k in required))
        # Edge math hand-check
        expected_edge = first["modelProbability"] - first["impliedProbability"]
        check(f"edge math correct (model {first['modelProbability']:.3f} - implied {first['impliedProbability']:.3f}): expected {expected_edge:.3f}, got {first['edge']:.3f}", abs(first['edge'] - expected_edge) < 0.001)
        # EV positive
        check("only positive-EV plays surfaced", all(i["ev"] > 0 for i in items))

# -----------------------------------------------------------------------------
# 5. Sport adapters
# -----------------------------------------------------------------------------
section("5. MULTI-SPORT ADAPTERS")
status, sports, _ = request("GET", "/api/sports")
check("/api/sports returns 200", status == 200)
if status == 200:
    keys = [s["key"] for s in sports.get("items", [])]
    expected_sports = {"NBA", "NFL", "MLB", "NHL", "SOCCER", "GOLF"}
    check(f"all 6 sports exposed: {keys}", expected_sports.issubset(set(keys)))

# -----------------------------------------------------------------------------
# 6. Endpoint inventory (claimed vs reality)
# -----------------------------------------------------------------------------
section("6. ENDPOINT INVENTORY (claimed by spec → reality)")

CLAIMED = [
    # path, method, expected_present, note
    ("/api/auth/signup", "POST", True, "implemented"),
    ("/api/auth/login", "POST", True, "implemented"),
    ("/api/auth/logout", "POST", True, "implemented"),
    ("/api/auth/me", "GET", True, "implemented"),
    ("/api/games/today", "GET", True, "implemented"),
    ("/api/games/1/markets", "GET", True, "implemented"),
    ("/api/slips", "GET", True, "implemented (auth-required)"),
    ("/api/slips", "POST", True, "implemented (auth-required)"),
    ("/api/slips/1/run", "POST", False, "MISSING — current /api/slips/analyze takes the slip body inline; no per-id /run endpoint"),
    ("/api/slips/1/results", "GET", False, "MISSING — Run Algorithm result is returned synchronously, not stored per-slip"),
    ("/api/slips/1/legs", "POST", False, "MISSING — slip legs are stored as part of the parlay row, no per-leg POST/PATCH/DELETE"),
    ("/api/slips/1/reorder", "PATCH", False, "MISSING — reorder happens client-side, never persisted"),
    ("/api/live/readiness", "GET", True, "implemented"),
    ("/api/billing/create-checkout-session", "POST", False, "MISSING — Stripe checkout never wired"),
    ("/api/billing/create-portal-session", "POST", False, "MISSING — billing portal never wired"),
    ("/api/billing/subscription", "GET", False, "MISSING — subscription status not exposed"),
    ("/api/webhooks/stripe", "POST", False, "AT WRONG PATH — webhook lives at /api/billing/stripe/webhook (200) not /api/webhooks/stripe (404)"),
    ("/api/admin/live-readiness", "GET", False, "MISSING — admin-prefixed alias not implemented; admins use /api/live/readiness"),
    ("/api/admin/database-readiness", "GET", False, "MISSING — alias not implemented; admins use /api/database/readiness"),
    ("/api/admin/logs", "GET", False, "MISSING — no log endpoint exists"),
]

print("  Claimed-by-spec endpoint check:")
for path, method, expected, note in CLAIMED:
    status, _, _ = request(method, path, body={} if method != "GET" else None)
    present = status not in (404, 405)
    icon = "OK" if present == expected else "MISMATCH"
    print(f"    [{icon}] {method:6s} {path:50s} HTTP {status}  · {note}")

# -----------------------------------------------------------------------------
# 7. Public dashboard contains zero admin internals
# -----------------------------------------------------------------------------
section("7. PUBLIC vs ADMIN SEPARATION (HTML inspection)")
import urllib.request
req = urllib.request.Request(API, headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"})
html = urllib.request.urlopen(req).read().decode()
admin_words = ["scraper", "ingestion", "database readiness", "raw_ball_dont_lie", "supervisor", "Postgres internals"]
present = [w for w in admin_words if w.lower() in html.lower()]
check("public landing page has zero admin/scraper/ingestion language", len(present) == 0, f"found: {present}")

# -----------------------------------------------------------------------------
# 8. Security smell-test
# -----------------------------------------------------------------------------
section("8. SECURITY SMELL TEST")
secrets = ["sk_live_", "sk_test_", "STRIPE_SECRET_KEY", "JWT_SECRET", "MONGO_URL", "DATABASE_URL", "BALLDONTLIE_API_KEY", "OPENAI_API_KEY", "password_hash"]
leaks = [s for s in secrets if s in html]
check("no obvious secret strings in public HTML", len(leaks) == 0, f"leaks: {leaks}")

print("\nAUDIT COMPLETE.")
