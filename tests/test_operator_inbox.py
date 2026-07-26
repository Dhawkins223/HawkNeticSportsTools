from __future__ import annotations

import concurrent.futures
from pathlib import Path

from kalshi_research_bot.operator_inbox import OperatorInbox
from kalshi_research_bot.paper_server import render_operator_page

from tests.postgres_support import PostgresTestCase


class OperatorInboxTests(PostgresTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.inbox = OperatorInbox(self.settings)

    def test_queue_claim_complete_preserves_manual_boundary(self) -> None:
        queued = self.inbox.add(
            message_id="review-worker-health",
            title="Review worker health",
            body="Inspect and propose a safe patch.",
            created_by="owner",
            priority="high",
        )
        claimed = self.inbox.claim(queued["message_id"], agent="codex")
        completed = self.inbox.complete(
            queued["message_id"], agent="codex", summary="Reviewed without automatic action."
        )

        self.assertTrue(queued["requires_approval"])
        self.assertFalse(queued["execution_allowed"])
        self.assertEqual(claimed["status"], "claimed")
        self.assertEqual(completed["status"], "completed")
        self.assertFalse(completed["execution_allowed"])

    def test_idempotent_message_rejects_changed_content(self) -> None:
        first = self.inbox.add(message_id="same", title="Same", body="Same", created_by="owner")
        repeated = self.inbox.add(message_id="same", title="Same", body="Same", created_by="owner")
        with self.assertRaisesRegex(ValueError, "message_id_conflict"):
            self.inbox.add(message_id="same", title="Changed", body="Different", created_by="owner")
        self.assertEqual(first["message_id"], repeated["message_id"])

    def test_other_agent_cannot_complete_claim(self) -> None:
        message = self.inbox.add(title="Task", body="Body", created_by="owner")
        self.inbox.claim(message["message_id"], agent="codex")
        with self.assertRaisesRegex(ValueError, "message_claimed_by_another_agent"):
            self.inbox.complete(message["message_id"], agent="other", summary="Done")

    def test_page_and_environment_document_manual_review_only(self) -> None:
        page = render_operator_page()
        environment = Path(".env.example").read_text(encoding="utf-8")
        self.assertIn("Private operator inbox", page)
        self.assertIn("never run commands", page)
        self.assertNotIn("Place order", page)
        self.assertIn("never executes commands", environment)

    def test_concurrent_same_message_id_returns_one_queued_message(self) -> None:
        def add_message(_: int) -> dict:
            return self.inbox.add(
                message_id="concurrent-message",
                title="Review",
                body="Review without execution.",
                created_by="owner",
            )

        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
            messages = list(executor.map(add_message, range(2)))
        count = self.query_one(
            "SELECT COUNT(*) AS total FROM ops.operator_messages WHERE message_id = %s",
            ("concurrent-message",),
        )
        self.assertEqual({message["message_id"] for message in messages}, {"concurrent-message"})
        self.assertEqual(count["total"], 1)

    def test_invalid_priority_target_and_source_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "invalid_priority"):
            self.inbox.add(title="Task", body="Body", created_by="owner", priority="immediate")
        with self.assertRaisesRegex(ValueError, "invalid_target"):
            self.inbox.add(title="Task", body="Body", created_by="owner", target="execution")
        with self.assertRaisesRegex(ValueError, "invalid_source"):
            self.inbox.add(title="Task", body="Body", created_by="owner", source="remote")
