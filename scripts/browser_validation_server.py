"""Serve the dashboard against a deterministic fixture, for looking at it.

    python3 scripts/browser_validation_server.py
    python3 scripts/browser_validation_server.py --role read_only --state stale

Works from a clean checkout with no arguments. That was not true before, and
the three ways it failed were all quiet enough to be mistaken for defects in
the dashboard itself:

* It read `data/today_paper_view.json` by default. `data/` is gitignored down
  to a `.gitkeep`, so that file does not exist until a collector run has
  written one, and a clean checkout got a `FileNotFoundError`.
* `load_current_payload` reads `DASHBOARD_PAYLOAD_SOURCE`, which defaults to
  `postgres`. Without a database the fixture on disk was never opened at all
  and every page rendered the blocked state -- no error, just a dashboard
  reporting zero games and hidden slips.
* The fixture is stamped four minutes old, and the dashboard blocks a payload
  older than 1800s. Written once at startup, it aged out 26 minutes in and the
  page went blocked mid-session, which reads as an intermittent bug.

So the fixture is now built in-process, rebuilt per request, and the payload
source is pinned to the file this script controls.

`--role` renders the page a given role actually receives. The local
unprotected path resolves to `admin`, so before this the customer-facing
`read_only` surface could not be previewed at all -- every screenshot and
accessibility run this project has taken was of the operator's page.
"""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from kalshi_research_bot.auth import AuthPrincipal
from kalshi_research_bot.browser_fixtures import (
    BROWSER_FIXTURE_STATES,
    browser_fixture_refresh_status,
    build_browser_fixture_payload,
    make_verified_fixture_payload,
)
from kalshi_research_bot.paper_server import PaperHandler, ROLES, role_allows


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--state", choices=BROWSER_FIXTURE_STATES, default="live")
    parser.add_argument("--role", choices=sorted(ROLES), default="admin", help="render as this role")
    parser.add_argument(
        "--source",
        default=None,
        help="a collector payload to shape the fixture from; omit to build one in-process",
    )
    return parser


def build_fixture(source: Path | None, state: str) -> dict:
    """The payload to serve, freshly stamped every time this is called.

    `make_verified_fixture_payload` is the one place that knows how to assemble
    the per-leg exact-contract evidence the freshness and combo gates require,
    so a fixture built any other way renders the blocked page and teaches
    nothing.
    """
    base = json.loads(source.read_text(encoding="utf-8")) if source else make_verified_fixture_payload()
    return build_browser_fixture_payload(base, state)


def publish_fixture(fixture_path: Path, source: Path | None, state: str) -> None:
    """Write the fixture beside the target, then rename it into place.

    This server is threaded and one page load is many requests, so a plain
    `write_text` truncates the file while another thread is reading it:
    measured at 26 of 60 concurrent loads rendering the blocked page, because a
    half-written payload does not parse. A rename publishes the whole file at
    once, so a reader gets either the previous fixture or the new one and both
    are fresh.
    """
    payload = json.dumps(build_fixture(source, state), indent=2, sort_keys=True)
    descriptor, name = tempfile.mkstemp(dir=fixture_path.parent, prefix=".payload-", suffix=".json")
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
        os.replace(name, fixture_path)
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise


def preview_principal(role: str) -> AuthPrincipal:
    """The viewer this server stands in for.

    `local_unprotected` and not `session`: that is what this actually is, an
    unprotected local dashboard, and it is also what keeps the page usable.
    `valid_session_csrf` only checks a token for `session` principals, and a
    synthetic principal has no session to check against -- so claiming one made
    every POST fail with "Session CSRF validation failed", the admin refresh
    control included.
    """
    return AuthPrincipal(username=role, role=role, auth_method="local_unprotected")


def main() -> int:
    arguments = build_parser().parse_args()
    source = Path(arguments.source) if arguments.source else None
    if source is not None and not source.exists():
        raise SystemExit(f"{source} does not exist; omit --source to build a fixture in-process")

    # The handler asks `load_current_payload` for data, and that reads this
    # variable before it reads any path. Left at its default it goes to
    # PostgreSQL and ignores the file below entirely.
    os.environ["DASHBOARD_PAYLOAD_SOURCE"] = "file"

    with tempfile.TemporaryDirectory(prefix="kalshi-browser-fixture-") as directory:
        fixture_path = Path(directory) / "payload.json"

        def write_fixture() -> None:
            publish_fixture(fixture_path, source, arguments.state)

        write_fixture()

        class FixtureHandler(PaperHandler):
            data_path = fixture_path
            refresh_seconds = 0
            refresh_config: dict = {}
            refresh_status = browser_fixture_refresh_status(arguments.state)

            @classmethod
            def run_refresh(cls, reason: str, async_run: bool) -> dict:
                return dict(cls.refresh_status)

            def handle_one_request(self):
                # Restamped per request so a server left running does not drift
                # past the freshness window and start serving the blocked page.
                write_fixture()
                return super().handle_one_request()

            def authorize_request(self, *, required_role: str = "read_only") -> bool:
                # Stand in for a signed-in viewer of exactly `--role`. The
                # unprotected local path resolves to admin, which is why the
                # reader's page was never previewable.
                principal = preview_principal(arguments.role)
                if not role_allows(principal.role, required_role):
                    self.send_json({"error": "role_forbidden"}, status_code=403)
                    return False
                self.principal = principal
                return True

            def log_message(self, format: str, *values) -> None:
                return

        server = ThreadingHTTPServer((arguments.host, arguments.port), FixtureHandler)
        origin = "in-process fixture" if source is None else str(source)
        print(
            f"Browser fixture '{arguments.state}' as '{arguments.role}' from {origin}\n"
            f"  http://{arguments.host}:{arguments.port}"
        )
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
