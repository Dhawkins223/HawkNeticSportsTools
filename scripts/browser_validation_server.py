from __future__ import annotations

import argparse
import json
import tempfile
from http.server import ThreadingHTTPServer
from pathlib import Path

from kalshi_research_bot.browser_fixtures import (
    BROWSER_FIXTURE_STATES,
    browser_fixture_refresh_status,
    build_browser_fixture_payload,
)
from kalshi_research_bot.config import repo_path
from kalshi_research_bot.paper_server import PaperHandler


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="serve deterministic private dashboard browser fixtures")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8780)
    parser.add_argument("--state", choices=BROWSER_FIXTURE_STATES, default="live")
    parser.add_argument("--source", default=str(repo_path("data", "today_paper_view.json")))
    return parser


def main() -> int:
    args = build_parser().parse_args()
    source = Path(args.source)
    payload = json.loads(source.read_text(encoding="utf-8"))
    fixture = build_browser_fixture_payload(payload, args.state)
    with tempfile.TemporaryDirectory(prefix="kalshi-browser-fixture-") as directory:
        fixture_path = Path(directory) / "payload.json"
        fixture_path.write_text(json.dumps(fixture, indent=2, sort_keys=True), encoding="utf-8")

        class FixtureHandler(PaperHandler):
            data_path = fixture_path
            refresh_seconds = 0
            refresh_config = {}
            refresh_status = browser_fixture_refresh_status(args.state)

            @classmethod
            def run_refresh(cls, reason: str, async_run: bool) -> dict:
                return dict(cls.refresh_status)

            def log_message(self, format: str, *values) -> None:
                return

        server = ThreadingHTTPServer((args.host, args.port), FixtureHandler)
        print(f"Browser fixture '{args.state}' running at http://{args.host}:{args.port}")
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
