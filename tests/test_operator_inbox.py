from __future__ import annotations

import base64
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from kalshi_research_bot.operator_inbox import OperatorInbox
from kalshi_research_bot.paper_server import PaperHandler, render_operator_page


def _basic_header(username: str, password: str) -> str:
    token = base64.b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
    return f"Basic {token}"


def _request(url: str, *, method: str = "GET", role_auth: bool = False, payload: dict | None = None):
    headers = {"Accept": "application/json"}
    if role_auth:
        headers["Authorization"] = _basic_header("owner", "secret")
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(request, timeout=5) as response:
        body = response.read().decode("utf-8")
        return response.status, response.headers.get_content_type(), body


class OperatorInboxTests(unittest.TestCase):
    def test_queue_claim_complete_flow_never_allows_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = OperatorInbox(Path(directory) / "operator.sqlite")
            queued = inbox.add(
                message_id="msg_fixture",
                title="Review worker health",
                body="Inspect the status and propose a safe patch.",
                created_by="owner",
                priority="high",
                target="codex",
            )
            claimed = inbox.claim("msg_fixture", agent="codex")
            completed = inbox.complete(
                "msg_fixture",
                agent="codex",
                summary="Reviewed; no automatic action was taken.",
            )

        self.assertEqual(queued["status"], "queued")
        self.assertTrue(queued["requires_approval"])
        self.assertFalse(queued["execution_allowed"])
        self.assertEqual(claimed["status"], "claimed")
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(completed["execution_allowed"])

    def test_add_is_idempotent_for_same_message_id_and_rejects_conflicts(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = OperatorInbox(Path(directory) / "operator.sqlite")
            first = inbox.add(
                message_id="msg_idempotent",
                title="Same",
                body="Same body",
                created_by="owner",
            )
            repeated = inbox.add(
                message_id="msg_idempotent",
                title="Same",
                body="Same body",
                created_by="owner",
            )
            with self.assertRaisesRegex(ValueError, "message_id_conflict"):
                inbox.add(
                    message_id="msg_idempotent",
                    title="Changed",
                    body="Different body",
                    created_by="owner",
                )

        self.assertEqual(first["message_id"], repeated["message_id"])

    def test_agent_cannot_complete_another_agents_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            inbox = OperatorInbox(Path(directory) / "operator.sqlite")
            message = inbox.add(title="Task", body="Body", created_by="owner")
            inbox.claim(message["message_id"], agent="codex")
            with self.assertRaisesRegex(ValueError, "message_claimed_by_another_agent"):
                inbox.complete(message["message_id"], agent="other-model", summary="Done")

    def test_operator_page_explains_manual_review_boundary(self):
        page = render_operator_page()
        self.assertIn("Private operator inbox", page)
        self.assertIn("never run commands", page)
        self.assertIn('value="normal" selected', page)
        self.assertNotIn("Place order", page)
        self.assertNotIn("automatic trading", page.lower())

    def test_env_example_documents_private_inbox_without_enabling_execution(self):
        env_text = Path(".env.example").read_text(encoding="utf-8")
        self.assertIn("DATABASE_URL=", env_text)
        self.assertNotIn("OPERATOR_INBOX_DB_PATH=", env_text)
        self.assertIn("never executes commands", env_text)

    def test_admin_can_queue_message_but_read_only_cannot(self):
        with tempfile.TemporaryDirectory() as directory:
            database = Path(directory) / "operator.sqlite"

            class Handler(PaperHandler):
                @property
                def operator_inbox(self):
                    return OperatorInbox(database)

                def log_message(self, format, *args):
                    return

            server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"
            try:
                env = {
                    "DASHBOARD_AUTH_ENABLED": "true",
                    "DASHBOARD_AUTH_USERNAME": "owner",
                    "DASHBOARD_AUTH_PASSWORD": "secret",
                    "DASHBOARD_BASIC_AUTH_ROLE": "read_only",
                }
                with patch.dict(os.environ, env, clear=False):
                    with self.assertRaises(urllib.error.HTTPError) as forbidden:
                        _request(
                            base + "/internal/operator-messages",
                            method="POST",
                            role_auth=True,
                            payload={"title": "No", "body": "No"},
                        )
                    self.assertEqual(forbidden.exception.code, 403)
                    forbidden.exception.close()

                    os.environ["DASHBOARD_BASIC_AUTH_ROLE"] = "admin"
                    status, content_type, body = _request(
                        base + "/internal/operator-messages",
                        method="POST",
                        role_auth=True,
                        payload={
                            "title": "Inspect collection",
                            "body": "Review the collector without changing model logic.",
                            "priority": "high",
                            "target": "codex",
                        },
                    )
                    response = json.loads(body)
                    self.assertEqual(status, 201)
                    self.assertEqual(content_type, "application/json")
                    self.assertFalse(response["execution_allowed"])
                    self.assertEqual(response["next_action"], "manual_agent_review")

                    status, _, body = _request(
                        base + "/internal/operator-messages.json",
                        role_auth=True,
                    )
                    messages = json.loads(body)["messages"]
                    self.assertEqual(status, 200)
                    self.assertEqual(len(messages), 1)
                    self.assertFalse(messages[0]["execution_allowed"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
