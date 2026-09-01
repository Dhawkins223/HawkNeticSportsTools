"""What each route hands out, proved by asking it.

The bug this file exists for: PRs #91 and #92 made five dashboard panels
operator-only, but the JSON endpoints serving the same data kept the blanket
`read_only` gate. A signed-in customer could fetch by hand exactly what had been
removed from their page. Hiding a panel is not withholding data when the data
has its own URL.

That class of mistake is invisible to a render-level assertion -- the page really
did stop showing it -- so these tests speak HTTP: a real server, real
credentials, real status codes. They use basic-auth with an explicit role rather
than user accounts, so they need no database and run everywhere.
"""

from __future__ import annotations

import ast
import base64
import json
import os
import pathlib
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from kalshi_research_bot.browser_fixtures import make_verified_fixture_payload
from kalshi_research_bot.paper_server import PaperHandler

SERVER_SOURCE = pathlib.Path(PaperHandler.__module__.replace(".", "/") + ".py")
if not SERVER_SOURCE.exists():  # running from the repo root
    import kalshi_research_bot.paper_server as _ps

    SERVER_SOURCE = pathlib.Path(_ps.__file__)

# The role each route demands. `None` means "reachable by any authenticated
# viewer"; a role name means require_role rejects anything below it. Adding a
# route without adding it here fails test_every_route_declares_its_gate, which
# is the point: a new endpoint should not inherit the blanket read_only gate by
# default and go unnoticed.
EXPECTED_GATES: dict[str, str | None] = {
    # public, before the blanket gate
    "/assets/": None,
    "/login": None,
    "/healthz": None,
    "/readyz": None,
    # any authenticated viewer
    "/": None,
    "/index.html": None,
    "/auth/me": None,
    "/auth/login": None,
    "/data.json": None,
    "/api/v1": None,
    "/games.json": None,
    "/api/v1/games": None,
    "/markets.json": None,
    "/api/v1/markets": None,
    "/refresh-status": None,
    "/freshness.json": None,
    # research output
    "/review-packets.json": "researcher",
    "/review-packet.json": "researcher",
    "/review-packet.txt": "researcher",
    "/slip-analysis.json": "researcher",
    # operator surfaces, and the data behind operator-only panels
    "/ops": "admin",
    "/internal/status.json": "admin",
    "/internal/operator-messages": "admin",
    "/internal/operator-messages.json": "admin",
    "/quality.json": "admin",
    "/research-record.json": "admin",
    "/sports.json": "admin",
    "/sports-clv.json": "admin",
    "/api/v1/source-data": "admin",
    "/api/v1/source-data/entities": "admin",
    "/api/v1/source-data/markets": "admin",
    "/api/v1/source-data/live": "admin",
    "/api/v1/source-data/refresh": "admin",
    "/api/v1/source-data/refresh/": "admin",
    "/refresh": "admin",
    "/auth/logout": "admin",
}

# Exercised over HTTP. POST routes are covered by the declaration guard rather
# than by status codes, because their action-header and CSRF checks interleave
# with the role check and would make a bare status ambiguous.
GET_PROBES = {
    "/": "/",
    "/index.html": "/index.html",
    "/auth/me": "/auth/me",
    "/ops": "/ops",
    "/internal/status.json": "/internal/status.json",
    "/internal/operator-messages.json": "/internal/operator-messages.json",
    "/data.json": "/data.json",
    "/api/v1": "/api/v1",
    "/games.json": "/games.json",
    "/api/v1/games": "/api/v1/games?limit=50&offset=0",
    "/markets.json": "/markets.json",
    "/api/v1/markets": "/api/v1/markets?limit=50&offset=0",
    "/refresh-status": "/refresh-status",
    "/freshness.json": "/freshness.json",
    "/review-packets.json": "/review-packets.json",
    "/review-packet.json": "/review-packet.json",
    "/review-packet.txt": "/review-packet.txt",
    "/slip-analysis.json": "/slip-analysis.json",
    "/quality.json": "/quality.json",
    "/research-record.json": "/research-record.json",
    "/sports.json": "/sports.json",
    "/sports-clv.json": "/sports-clv.json",
    "/api/v1/source-data": "/api/v1/source-data",
    "/api/v1/source-data/entities": "/api/v1/source-data/entities",
    "/api/v1/source-data/markets": "/api/v1/source-data/markets",
    "/api/v1/source-data/live": "/api/v1/source-data/live",
    "/api/v1/source-data/refresh/": "/api/v1/source-data/refresh/some-id",
}

ROLES = ("read_only", "researcher", "admin")
RANK = {role: index for index, role in enumerate(ROLES, start=1)}


def route_literals() -> set[str]:
    """Every path the handler compares against, read out of the source.

    Grepping for `path == "..."` missed the `path in {"/games.json", ...}` form
    and four routes with it, so this walks the syntax tree instead of matching
    text.
    """
    tree = ast.parse(SERVER_SOURCE.read_text(encoding="utf-8"))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Compare) and ast.unparse(node.left) == "path":
            for op, comparator in zip(node.ops, node.comparators):
                if isinstance(op, ast.Eq) and isinstance(comparator, ast.Constant):
                    found.add(comparator.value)
                elif isinstance(op, ast.In) and isinstance(comparator, (ast.Set, ast.Tuple, ast.List)):
                    found.update(e.value for e in comparator.elts if isinstance(e, ast.Constant))
        if isinstance(node, ast.Call) and ast.unparse(node.func).endswith("path.startswith"):
            found.update(a.value for a in node.args if isinstance(a, ast.Constant))
    return found


class RouteAuthorizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._env = {
            "DASHBOARD_PAYLOAD_SOURCE": "file",
            "DASHBOARD_AUTH_ENABLED": "true",
            "DASHBOARD_AUTH_USERNAME": "owner",
            "DASHBOARD_AUTH_PASSWORD": "secret",
            "DASHBOARD_BASIC_FALLBACK_ENABLED": "true",
            "DASHBOARD_USER_AUTH_ENABLED": "false",
            "DASHBOARD_REQUIRE_AUTH_WHEN_HOSTED": "false",
        }
        cls._saved = {k: os.environ.get(k) for k in list(cls._env) + ["DASHBOARD_BASIC_AUTH_ROLE"]}
        os.environ.update(cls._env)
        cls._hosted = {k: os.environ.pop(k, None) for k in ("RAILWAY_ENVIRONMENT", "APP_ENV")}

        payload_path = pathlib.Path(tempfile.mkdtemp()) / "payload.json"
        payload_path.write_text(json.dumps(make_verified_fixture_payload()), encoding="utf-8")

        class Handler(PaperHandler):
            data_path = payload_path
            refresh_seconds = 0
            refresh_config: dict = {}
            refresh_status: dict = {"state": "idle", "message": "Ready"}

            def log_message(self, *args: object) -> None:
                return

        cls._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls._thread = threading.Thread(target=cls._server.serve_forever, daemon=True)
        cls._thread.start()
        cls.base = f"http://127.0.0.1:{cls._server.server_address[1]}"
        cls.credentials = "Basic " + base64.b64encode(b"owner:secret").decode("ascii")

    @classmethod
    def tearDownClass(cls) -> None:
        cls._server.shutdown()
        cls._server.server_close()
        cls._thread.join(timeout=5)
        for key, value in {**cls._saved, **cls._hosted}.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def request(self, path: str, role: str) -> tuple[int, bytes]:
        os.environ["DASHBOARD_BASIC_AUTH_ROLE"] = role
        request = urllib.request.Request(self.base + path, headers={"Authorization": self.credentials})
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                return response.status, response.read()
        except urllib.error.HTTPError as error:
            return error.code, error.read()

    def test_every_route_declares_its_gate(self) -> None:
        """A new route must say what it requires, rather than inheriting one.

        Everything after the blanket gate in `do_GET` is reachable by any
        authenticated viewer unless it says otherwise, so an endpoint added
        without a `require_role` is readable by customers and nothing complains.
        Declaring the whole surface here turns that silence into a failure.
        """
        self.assertEqual(
            sorted(route_literals() - set(EXPECTED_GATES)),
            [],
            "route(s) in paper_server.py with no declared gate in EXPECTED_GATES",
        )
        self.assertEqual(
            sorted(set(EXPECTED_GATES) - route_literals()),
            [],
            "EXPECTED_GATES names route(s) that no longer exist",
        )

    def test_each_route_refuses_exactly_the_roles_below_its_gate(self) -> None:
        """403 if and only if the role is insufficient.

        The upper bound is deliberately loose: an authorised call may still fail
        for its own reasons (503 with no database, 404 when a feature is off).
        What matters is that authorisation, and only authorisation, produces 403.
        """
        for route, probe in GET_PROBES.items():
            required = EXPECTED_GATES[route]
            for role in ROLES:
                allowed = required is None or RANK[role] >= RANK[required]
                with self.subTest(route=route, role=role, requires=required or "any"):
                    status, _ = self.request(probe, role)
                    if allowed:
                        self.assertNotEqual(status, 403, f"{route} refused {role}, which it should allow")
                    else:
                        self.assertEqual(status, 403, f"{route} served {role}, which is below {required}")

    def test_the_slip_feed_withholds_the_operator_only_tier(self) -> None:
        # The research-scout tier is operator-only on the page. Leaving it in
        # this feed let a reader fetch the one tier their dashboard withholds.
        for role in ("read_only", "researcher"):
            with self.subTest(role=role):
                status, body = self.request("/data.json", role)
                self.assertEqual(status, 200)
                self.assertNotIn("research_edge_slip", json.loads(body))
        status, body = self.request("/data.json", "admin")
        self.assertIn("research_edge_slip", json.loads(body))

    def test_the_catalog_lists_only_what_the_caller_may_fetch(self) -> None:
        """A directory that advertises a 403 is worse than one that omits it."""
        seen = {}
        for role in ROLES:
            status, body = self.request("/api/v1", role)
            self.assertEqual(status, 200)
            seen[role] = set(json.loads(body)["collections"])
        self.assertNotIn("source_data", seen["read_only"])
        self.assertNotIn("sports", seen["read_only"])
        self.assertNotIn("slip_analysis", seen["read_only"])
        self.assertIn("slip_analysis", seen["researcher"])
        self.assertIn("source_data", seen["admin"])
        # Advertised is a subset of reachable, checked rather than assumed.
        for role, collections in seen.items():
            for name in collections:
                href = json.loads(self.request("/api/v1", role)[1])["collections"][name]["href"]
                with self.subTest(role=role, collection=name):
                    self.assertNotEqual(self.request(href, role)[0], 403, f"{role} shown unreachable {href}")

    def test_the_customer_dashboard_still_renders(self) -> None:
        # Gating the data must not take the page with it.
        for role in ROLES:
            with self.subTest(role=role):
                status, body = self.request("/", role)
                self.assertEqual(status, 200)
                self.assertIn(b"Review Kalshi markets", body)


if __name__ == "__main__":
    unittest.main()
