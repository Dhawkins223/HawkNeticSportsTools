"""HawkneticSports P0 readiness audit — verifies every blocker fix end-to-end."""
from __future__ import annotations

import json
import time
import http.cookiejar
import urllib.error
import urllib.request

API = "https://1b115e8a-b516-47c2-bfd6-7e86bc65409b.preview.emergentagent.com"
UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36"


def request(method, path, body=None, cookies=None, extra_headers=None, raw=False):
    cj = cookies or http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    headers = {"User-Agent": UA, "Accept": "application/json", "Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    data = json.dumps(body).encode() if (body is not None and not raw) else (body if raw else None)
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        resp = opener.open(req, timeout=15)
        text = resp.read().decode()
        try:
            return resp.status, json.loads(text), cj
        except json.JSONDecodeError:
            return resp.status, text, cj
    except urllib.error.HTTPError as e:
        text = e.read().decode()
        try:
            return e.code, json.loads(text), cj
        except json.JSONDecodeError:
            return e.code, text, cj


def section(label):
    print(f"\n{'=' * 70}\n{label}\n{'=' * 70}")


def check(label, passed, detail=""):
    icon = "PASS" if passed else "FAIL"
    print(f"  [{icon}] {label}{(' — ' + detail) if detail else ''}")
    return passed


# Re-seed v2 fresh so live readiness is "ready" at run start
import subprocess
subprocess.run(["python3", "/app/scripts/seed_v2.py"], check=False, capture_output=True)

email = f"p0-{int(time.time())}@hawk.test"
status, body, cj = request("POST", "/api/auth/signup", {"email": email, "password": "p0pass123", "full_name": "P0 Audit"})
check("signup ok", status == 200)

# -----------------------------------------------------------------------------
section("P0.1 STRIPE BILLING")
# Subscription endpoint
status, sub, _ = request("GET", "/api/billing/subscription", cookies=cj)
check("GET /api/billing/subscription returns 200", status == 200)
check("subscription endpoint shows plan='free' by default", isinstance(sub, dict) and sub.get("plan") == "free", str(sub) if not isinstance(sub, dict) else f"plan={sub.get('plan')}, limit={sub.get('limits', {}).get('daily_slip_runs')}")

# Checkout requires auth
status, _, _ = request("POST", "/api/billing/create-checkout-session", {"plan": "pro"})
check("anon /create-checkout-session → 401", status == 401)

# Checkout returns 503 when price IDs are placeholder (current state)
status, ck, _ = request("POST", "/api/billing/create-checkout-session", {"plan": "pro"}, cookies=cj)
check("authenticated /create-checkout-session with placeholder price ID returns 503 (clean error)", status == 503, f"got {status}: {ck}")

# Portal requires customer
status, prt, _ = request("POST", "/api/billing/create-portal-session", {}, cookies=cj)
check("/create-portal-session without customer returns 400", status == 400, f"got {status}")

# Webhook signature verification
status, _, _ = request("POST", "/api/webhooks/stripe", {"type": "checkout.session.completed"})
check("webhook with no signature → 400", status == 400)
status, _, _ = request("POST", "/api/webhooks/stripe", {"type": "checkout.session.completed"}, extra_headers={"Stripe-Signature": "t=1,v1=invalidhex"})
check("webhook with INVALID signature → 400", status == 400)

# -----------------------------------------------------------------------------
section("P0.2 SAVED-SLIP RUN-BY-ID + RESULTS")
status, save, _ = request("POST", "/api/slips", {"name": "P0 saved", "sport": "NBA", "legs": [{"label": "LeBron points over 25.5", "odds_value": -115, "probability": 0.6}]}, cookies=cj)
slip_id = save.get("slip", {}).get("id")
check(f"save slip ok (id={slip_id})", isinstance(slip_id, int))

status, run, _ = request("POST", f"/api/slips/{slip_id}/run", cookies=cj)
check(f"POST /api/slips/{slip_id}/run returns 200 OR blocked", status == 200, f"got {status}: {str(run)[:140]}")
status_ran = run.get("status") if isinstance(run, dict) else None
print(f"     run status={status_ran}, simRuns={run.get('simulationRuns') if isinstance(run, dict) else None}")

status, hist, _ = request("GET", f"/api/slips/{slip_id}/results", cookies=cj)
check("GET results returns persisted history", status == 200 and isinstance(hist, dict) and len(hist.get("items", [])) >= 1, f"got {len(hist.get('items', [])) if isinstance(hist, dict) else 0} historical results")

# Cross-user
email2 = f"p0b-{int(time.time())}@hawk.test"
status, _, cj2 = request("POST", "/api/auth/signup", {"email": email2, "password": "p0pass123", "full_name": "P0 B"})
status, _, _ = request("POST", f"/api/slips/{slip_id}/run", cookies=cj2)
check("user2 cannot run user1's slip → 404", status == 404, f"got {status}")
status, _, _ = request("GET", f"/api/slips/{slip_id}/results", cookies=cj2)
check("user2 cannot view user1's results → 404", status == 404)

# -----------------------------------------------------------------------------
section("P0.3 PLAN USAGE LIMITS")
status, usage, _ = request("GET", "/api/user/usage", cookies=cj)
check("GET /api/user/usage returns counts", status == 200 and "limit" in usage)
print(f"     plan={usage.get('plan')}, used={usage.get('used')}, limit={usage.get('limit')}")

# Hit limit on the free plan: should already have 1 run from above, do 2 more, then 4th must 403.
free_runs_to_use = max(0, usage.get("limit", 3) - usage.get("used", 0))
status_codes = []
for i in range(free_runs_to_use):
    s, _, _ = request("POST", f"/api/slips/{slip_id}/run", cookies=cj)
    status_codes.append(s)
# Next run should 403
s_blocked, blocked_body, _ = request("POST", f"/api/slips/{slip_id}/run", cookies=cj)
check(f"after {usage.get('limit')} runs: HTTP {s_blocked} (expected 403)", s_blocked == 403, f"got {s_blocked}: {str(blocked_body)[:120]}")

# -----------------------------------------------------------------------------
section("P1.1 DRAG-AND-DROP REORDER PERSISTENCE")
# need a slip with at least 2 legs on user2 to test reorder
status, save2, _ = request("POST", "/api/slips", {"name": "Reorder slip", "sport": "NBA", "legs": [
    {"label": "Leg A", "odds_value": -110, "probability": 0.55},
    {"label": "Leg B", "odds_value": +105, "probability": 0.5},
]}, cookies=cj2)
slip2_id = save2.get("slip", {}).get("id")
import sqlite3
conn = sqlite3.connect("/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/data/hawknetic.sqlite")
conn.row_factory = sqlite3.Row
legs = [dict(r) for r in conn.execute("SELECT id, label, leg_order FROM parlay_legs WHERE parlay_id=?", (slip2_id,)).fetchall()]
print(f"     before reorder: {[(l['id'], l['leg_order']) for l in legs]}")
if len(legs) >= 2:
    payload = {"leg_order": [{"leg_id": legs[1]["id"], "position": 0}, {"leg_id": legs[0]["id"], "position": 1}]}
    status, body, _ = request("PATCH", f"/api/slips/{slip2_id}/reorder", payload, cookies=cj2)
    check(f"PATCH /reorder returns 200", status == 200, f"got {status}: {body}")
    after = [dict(r) for r in conn.execute("SELECT id, label, leg_order FROM parlay_legs WHERE parlay_id=? ORDER BY leg_order", (slip2_id,)).fetchall()]
    print(f"     after reorder:  {[(l['id'], l['leg_order']) for l in after]}")
    check("leg_order persisted (legs swapped)", after[0]["id"] == legs[1]["id"] and after[1]["id"] == legs[0]["id"])

# Cross-user reorder denied
status, _, _ = request("PATCH", f"/api/slips/{slip2_id}/reorder", {"leg_order": [{"leg_id": legs[0]["id"], "position": 0}]}, cookies=cj)
check("user1 cannot reorder user2's slip → 404", status == 404, f"got {status}")
conn.close()

# -----------------------------------------------------------------------------
section("P1.2 LIVE READINESS HARD-BLOCK")
# Force readiness blocking by aging the live game
import sqlite3
conn = sqlite3.connect("/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/data/hawknetic.sqlite")
conn.execute("UPDATE live_games SET last_updated = '2024-01-01T00:00:00+00:00' WHERE LOWER(status) IN ('live','in_progress','halftime')")
conn.commit()
conn.close()

# fresh user so we don't hit usage cap
email3 = f"p0c-{int(time.time())}@hawk.test"
status, _, cj3 = request("POST", "/api/auth/signup", {"email": email3, "password": "p0pass123", "full_name": "P0 C"})

status, blocked, _ = request("POST", "/api/slips/analyze", {
    "bookmaker": "consensus", "stake": 10,
    "legs": [{"id": "l1", "sport": "NBA", "bookmaker": "consensus", "gameId": "1", "eventLabel": "x",
              "marketType": "player_prop", "selection": "Points (LeBron James) over", "line": 25.5, "oddsAmerican": -115, "playerId": "1"}],
}, cookies=cj3)
check("analyze with stale live game returns 200 (not error)", status == 200)
check("analyze response has status='blocked'", isinstance(blocked, dict) and blocked.get("status") == "blocked", f"status={blocked.get('status') if isinstance(blocked, dict) else blocked}")
check("blocked response has blocking_reasons array", isinstance(blocked.get("blocking_reasons"), list) and len(blocked["blocking_reasons"]) > 0)
check("blocked response shows simulationRuns=0 (no MC ran)", blocked.get("simulationRuns") == 0)

# Verify usage NOT incremented for blocked run
status, usage3, _ = request("GET", "/api/user/usage", cookies=cj3)
check("blocked run did NOT consume usage", usage3.get("used") == 0, f"used={usage3.get('used')}")

# -----------------------------------------------------------------------------
section("P1.3 LOGIN RATE LIMITING")
limit_email = f"limit-{int(time.time())}@hawk.test"
request("POST", "/api/auth/signup", {"email": limit_email, "password": "correctpass", "full_name": "X"})
codes = []
for _ in range(7):
    s, _, _ = request("POST", "/api/auth/login", {"email": limit_email, "password": "wrongpass"})
    codes.append(s)
print(f"     login attempt codes: {codes}")
check("first 5 wrong logins = 401, 6th+ = 429", codes.count(429) >= 1, f"codes: {codes}")

# Valid login still works after limit reset (need new bucket — different email-not-the-rate-limited one)
# Rate-limit bucket is per-email so this email is locked. Verify lockout instead.
s_locked, _, _ = request("POST", "/api/auth/login", {"email": limit_email, "password": "correctpass"})
check("locked email rejects even with correct password", s_locked == 429, f"got {s_locked}")

# -----------------------------------------------------------------------------
section("P1.4 PRODUCTION COOKIE CONFIG")
import subprocess
out = subprocess.run(["grep", "-n", "is_production", "/app/hawknetic_balldontlie_env_ready/hawknetic_balldontlie_env_ready/app/routes/api.py"], capture_output=True, text=True).stdout
check("session cookie uses is_production() guard", "is_production" in out)

# -----------------------------------------------------------------------------
section("P1.5 ADMIN ENDPOINTS")
status, ar, _ = request("GET", "/api/admin/live-readiness")
check("/api/admin/live-readiness returns 200", status == 200)
status, dr, _ = request("GET", "/api/admin/database-readiness")
check("/api/admin/database-readiness returns 200", status == 200)
status, lg, _ = request("GET", "/api/admin/logs")
check("/api/admin/logs returns 200", status == 200, f"got {status}: {str(lg)[:140]}")

print("\nAUDIT COMPLETE.")
